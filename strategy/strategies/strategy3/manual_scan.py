"""策略3手动监控扫描：中证1000主板范围，破前低预警与鲍鱼标记分开。"""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
import io,json,os,sys,time,subprocess,fcntl
from pathlib import Path
import pandas as pd
import requests
from .reversal import ROOT,load_daily
from .market_scan import completed_day,mainboard,local_names,config_hash,_one
from .combo_config import config_from_bindings
from .intraday_scan import scan_context, fetch_scan_quotes, live_daily, QuoteUnavailable

OUT=ROOT/'backtest/strategy3_abalone/manual_scan'
URL='https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000852cons.xls'
SCOPE='csi1000_mainboard_manual'
WORKERS=6


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False));tmp.replace(path)


def read_json(path,default):
    try:return json.loads(path.read_text())
    except (FileNotFoundError,ValueError):return default


def parse_constituents(df,names):
    code_col=next(c for c in df if 'Constituent Code' in str(c) or '成份券代码' in str(c))
    name_col=next(c for c in df if ('Constituent Name' in str(c) or '成份券名称' in str(c)) and 'Eng' not in str(c))
    rows=[];seen=set();excluded=0
    for _,r in df.iterrows():
        c=str(r[code_col]).split('.')[0].zfill(6);official=str(r[name_col]).strip();name=names.get(c,official)
        s=('sh' if c.startswith('6') else 'sz')+c
        if c in seen:continue
        seen.add(c)
        if not mainboard(s) or any('ST' in n.upper() or '退' in n for n in (name,official)):
            excluded+=1;continue
        rows.append(dict(symbol=s,code=c,name=name))
    return rows,excluded


def universe():
    r=requests.get(URL,timeout=30);r.raise_for_status();df=pd.read_excel(io.BytesIO(r.content))
    codes=next(c for c in df if 'Constituent Code' in str(c) or '成份券代码' in str(c))
    if not 900<=df[codes].nunique()<=1100:raise ValueError('中证1000成分表数量异常，不扩大到其它股票代替')
    rows,excluded=parse_constituents(df,local_names())
    date_col=next((c for c in df if '日期' in str(c)),None)
    meta=dict(source=URL,index='000852',index_count=int(df[codes].nunique()),excluded_count=excluded,
              constituent_date=str(df[date_col].iloc[0]) if date_col else None,fetched_at=str(pd.Timestamp.now(tz='Asia/Shanghai')))
    return rows,meta


def empty_snapshot():
    return dict(scope=SCOPE,as_of=None,rows=[],picks=[],universe_count=0,scanned_count=0,
                candidate_count=0,warning_count=0,counts={},research_only=True,auto_trade=False)


def status():
    state=read_json(OUT/'job.json',dict(state='idle',message='尚未扫描，点击按钮开始',done=0,total=0))
    if state.get('state')=='running' and state.get('pid'):
        try:os.kill(int(state['pid']),0)
        except ProcessLookupError:state.update(state='error',message='扫描进程已退出，请重试')
    return state


def start():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'start.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old=status()
        if old.get('state')=='running' or (old.get('state')=='starting' and time.time()-old.get('started_ts',0)<60):return old
        write_json(OUT/'snapshot.json',empty_snapshot())
        job=dict(state='starting',message='正在启动中证1000手动扫描',done=0,total=0,started_ts=time.time())
        write_json(OUT/'job.json',job)
        with (OUT/'worker.log').open('a') as log:
            try:subprocess.Popen([sys.executable,'-m','strategy.strategies.strategy3.manual_scan'],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            except Exception:
                job.update(state='error',message='扫描进程启动失败');write_json(OUT/'job.json',job);raise
        return job


def classify(rec):
    # 监控预警不限于10日入场窗口；native broken仅在当前相邻下笔有效窗口内为真。
    warning=bool(rec.get('broken'))
    return warning,bool(warning and rec.get('candidate'))


def _scan_stock(item,as_of,cfg,context=None,quote=None):
    from strategy.data import fetch_daily
    # 完整日线已经齐备时不再重复联网；已有结构特征由输入哈希缓存复用。
    refresh_error=None
    cached,_=load_daily(item['symbol'])
    context=context or dict(mode='daily',history_as_of=as_of)
    cutoff=pd.Timestamp(context['history_as_of'])
    usable=cached[cached.date<=cutoff] if not cached.empty else cached
    cache_ready=bool(len(usable)>=120 and usable.date.max()==cutoff)
    if not cache_ready:
        try:fetch_daily(item['symbol'],'20200101',cutoff.strftime('%Y%m%d'))
        except Exception as exc:refresh_error=type(exc).__name__
    if context['mode']=='intraday':
        history,meta=load_daily(item['symbol'])
        try:daily,quote_meta=live_daily(history,quote,context)
        except QuoteUnavailable as exc:
            return dict(**item,status=exc.status,warning=False,candidate=False,used_daily_cache=cache_ready)
        rec,g=_one(item['symbol'],item['name'],as_of,cfg,feature_dir=OUT/'intraday_features',
                   daily=daily,metadata=meta,auction=quote_meta['price_basis']=='auction_open')
        rec.update(quote_meta)
        if g is not None:
            # 盘中恐慌度按当次价格是否仍在前低之下判定，收复后退出盘中预警。
            r=g.iloc[-1]
            rec['broken']=bool(r.broken and float(r.close)<float(r.anchor))
    else:
        rec,_=_one(item['symbol'],item['name'],as_of,cfg,feature_dir=OUT/'features')
    rec['used_daily_cache']=cache_ready
    if refresh_error:rec['refresh_error']=refresh_error
    warn,badge=classify(rec);rec.update(warning=warn,candidate=badge)
    return rec


def _pool(workers):
    # AkShare/V8的进程内全局锁保留；独立进程各自安全串行，进程之间真正并发。
    # spawn避免从已有线程/V8运行时fork，日线更新和CZSC计算均可并行。
    return ProcessPoolExecutor(max_workers=workers,mp_context=get_context('spawn'))


def run():
    from .bindings import FACTOR_BINDINGS
    job=dict(state='running',pid=os.getpid(),started_ts=time.time(),done=0,total=0,workers=WORKERS,executor='process',message=f'正在获取中证1000最新成分股（{WORKERS}路并发）')
    write_json(OUT/'job.json',job)
    try:
        items,meta=universe();cfg=config_from_bindings(FACTOR_BINDINGS);context=scan_context();as_of=context['as_of']
        quotes={}
        if context['mode']=='intraday':
            job.update(message='正在读取本次扫描的盘中报价（9:25起支持正式开盘价）');write_json(OUT/'job.json',job)
            quotes=fetch_scan_quotes([it['symbol'] for it in items])
        job.update(total=len(items),message=f'{WORKERS}路并发更新完整日线并识别结构前低');write_json(OUT/'job.json',job)
        rows=[]
        with _pool(WORKERS) as pool:
            pending={pool.submit(_scan_stock,it,as_of,cfg,context,quotes.get(it['symbol'])):it for it in items}
            for f in as_completed(pending):
                it=pending[f]
                try:rec=f.result()
                except Exception as exc:rec=dict(**it,status='error',error=type(exc).__name__)
                rows.append(rec);job.update(done=len(rows),message=f'{WORKERS}路并发：已处理 {len(rows)}/{len(items)}，前低破位 {sum(bool(x.get("warning")) for x in rows)} 只')
                write_json(OUT/'job.json',job)
        rows.sort(key=lambda r:r['symbol']);watch=[r for r in rows if r.get('warning') or r.get('candidate')]
        picks=[dict(code=r['code'],symbol=r['symbol'],name=r['name'],warning=True,abalone=bool(r['candidate'])) for r in watch]
        snap=dict(scope=SCOPE,as_of=as_of,scan_mode=context['mode'],history_as_of=context['history_as_of'],scan_started_at=context['started_at'],generated_at=str(pd.Timestamp.now(tz='Asia/Shanghai')),config=cfg,config_hash=config_hash(cfg),
                  universe_count=len(items),scanned_count=sum(r['status']=='ready' for r in rows),warning_count=len(watch),
                  candidate_count=sum(bool(r.get('candidate')) for r in rows),rows=rows,picks=picks,
                  counts=pd.Series([r['status'] for r in rows]).value_counts().to_dict(),constituents=meta,research_only=True,auto_trade=False)
        write_json(OUT/'snapshot.json',snap)
        job.update(message='扫描完成，正在更新恐慌度历史分组');write_json(OUT/'job.json',job)
        try:
            if context['mode']=='daily':
                from .panic_study import run as study_panic
                study_panic(scan=snap,output=OUT)
        except Exception as exc:
            job['panic_study_error']=f'{type(exc).__name__}: {exc}'
        job.update(state='done',message=('盘中' if context['mode']=='intraday' else '')+f'扫描完成：监控 {len(watch)} 只，鲍鱼捞饭 {snap["candidate_count"]} 只',as_of=as_of)
    except Exception as exc:
        job.update(state='error',message=f'扫描失败：{type(exc).__name__}: {exc}')
    job.update(finished_ts=time.time(),elapsed_seconds=round(time.time()-job['started_ts'],1))
    write_json(OUT/'job.json',job)


if __name__=='__main__':run()
