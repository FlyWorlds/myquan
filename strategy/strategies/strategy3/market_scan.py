"""不依赖策略16的主板日线扫描。缓存覆盖与当日信号分开，过期行情不发信号。"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
from .reversal import ROOT, load_daily, Policy
from .factor_mining import features
from .combo_config import config_from_bindings, compose_entry
from strategy.abalone_risk import entry_plan
from strategy.costs import SLIPPAGE_VALUE

OUT=ROOT/'backtest/strategy3_abalone/market_scan'
DAILY_DIRS=('data_cache','data_cache/ai_concept','backtest/universe_wide/daily_cache',
            'backtest/universe_zz500_1000/daily_cache','backtest/universe_abc/daily_cache',
            'backtest/strategy3_abalone/daily')


def mainboard(symbol):
    return len(symbol)==8 and symbol[2:].isdigit() and symbol.startswith(('sh600','sh601','sh603','sh605','sz000','sz001','sz002','sz003'))


def completed_day(now=None):
    now=pd.Timestamp.now(tz='Asia/Shanghai') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:now=now.tz_localize('Asia/Shanghai')
    else:now=now.tz_convert('Asia/Shanghai')
    d=now.normalize().tz_localize(None)
    if (now.hour,now.minute)<(15,15):d-=pd.Timedelta(days=1)
    while d.weekday()>=5:d-=pd.Timedelta(days=1)
    return d


def config_hash(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def local_names():
    # 复用本地数据库/文件名称缓存，不在扫描热路径逐票联网补名称。
    sys.path.insert(0,str(ROOT/'holdingStocks')) if str(ROOT/'holdingStocks') not in sys.path else None
    from stock_names import _read_name_cache
    return _read_name_cache()


def discover(names):
    paths={}
    for folder in DAILY_DIRS:
        for p in (ROOT/folder).glob('*_daily_qfq.parquet'):
            s=p.name.split('_daily')[0]
            if mainboard(s):paths.setdefault(s,[]).append(p)
    symbols=set(paths)
    for code in names:
        s=('sh' if code.startswith('6') else 'sz')+code
        if mainboard(s):symbols.add(s)
    return [(s,names.get(s[2:],s[2:]),paths.get(s,[])) for s in sorted(symbols)]


def eligibility(d,as_of):
    if d.empty:return 'missing'
    if d.date.max()!=as_of:return 'stale'
    if len(d)<120:return 'short_history'
    if not float(d.volume.iloc[-1])>0:return 'no_volume'
    return 'ready'


def cache_dates(path):
    ds=pd.to_datetime(pd.read_parquet(path,columns=['date']).date)
    if ds.dt.tz is not None:ds=ds.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    return ds.dt.normalize()


def _one(symbol,name,as_of,config,feature_dir=None):
    date=pd.Timestamp(as_of)
    d,meta=load_daily(symbol)
    if not d.empty:d=d[d.date<=date].reset_index(drop=True)
    status=eligibility(d,date)
    rec=dict(symbol=symbol,code=symbol[2:],name=name,status=status,
             data_end=str(d.date.max().date()) if len(d) else None,rows=len(d),meta=meta)
    if status!='ready':return rec,None
    # 固定输入哈希缓存，不能在源行情变更后继续使用旧结构快照。
    key=hashlib.sha256(pd.util.hash_pandas_object(d,index=False).values.tobytes()).hexdigest()
    cache=(feature_dir if feature_dir is not None else OUT/'features')/f'{symbol}.parquet';signature=cache.with_suffix('.sha256')
    engine_hash=hashlib.sha256(Path(features.__code__.co_filename).read_bytes()).hexdigest()
    key+=engine_hash
    if cache.exists() and signature.exists() and signature.read_text()==key:
        f=pd.read_parquet(cache)
    else:
        f=features(d,symbol);cache.parent.mkdir(parents=True,exist_ok=True)
        f.to_parquet(cache,index=False);signature.write_text(key)
    g=compose_entry({symbol:f},config['rule'])[symbol];r=g.iloc[-1]
    plan=entry_plan(r,float(r.close)*(1+SLIPPAGE_VALUE),config['policy'])
    rec.update(candidate=bool(r.stabilize and plan['allowed']),broken=bool(r.broken),
               event_id=r.event_id,anchor=float(r.anchor) if pd.notna(r.anchor) else None,
               prior_high=float(r.peak) if pd.notna(r.peak) else None,
               event_low=float(r.trough) if pd.notna(r.trough) else None,
               close=float(r.close),depth=float(r.depth),vol_ratio=float(r.vol_ratio),
               break_volume=float(r.break_volume),plan=plan,input_hash=key)
    return rec,g


def run_scan(*,as_of=None,workers=4,backtest=False,refresh=False):
    from .bindings import FACTOR_BINDINGS
    cfg=config_from_bindings(FACTOR_BINDINGS)
    cutoff=pd.Timestamp(as_of).normalize() if as_of else completed_day()
    if cutoff>completed_day():raise ValueError('不能扫描未来或未完成的日线')
    OUT.mkdir(parents=True,exist_ok=True)
    names=local_names();items=discover(names)
    records=[];jobs=[];refresh_errors=[]
    for s,name,paths in items:
        if 'ST' in name.upper() or '退' in name:
            records.append(dict(symbol=s,code=s[2:],name=name,status='excluded_name'));continue
        if refresh:
            # 显式全范围更新；失败仍保留缺失/过期状态，绝不伪装成已扫描。
            from strategy.data import fetch_daily
            try:fetch_daily(s,'20200101',cutoff.strftime('%Y%m%d'))
            except Exception as exc:refresh_errors.append(dict(symbol=s,error=type(exc).__name__))
        if not paths and not refresh:
            records.append(dict(symbol=s,code=s[2:],name=name,status='missing'));continue
        ends=[]
        for p in paths if not refresh else [p for folder in DAILY_DIRS for p in [(ROOT/folder/f'{s}_daily_qfq.parquet')] if p.exists()]:
            try:
                ds=cache_dates(p)
                ds=ds[ds<=cutoff]
                if len(ds):ends.append(ds.max())
            except Exception:pass
        if not ends or max(ends)!=cutoff:
            records.append(dict(symbol=s,code=s[2:],name=name,status='stale' if ends else 'missing',
                                data_end=str(max(ends).date()) if ends else None));continue
        jobs.append((s,name,str(cutoff.date()),cfg))
    print('universe',len(items),'fresh jobs',len(jobs),flush=True)
    frames={}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(_one,*args):args[0] for args in jobs}
        for i,fu in enumerate(as_completed(futures),1):
            try:
                rec,g=fu.result();records.append(rec)
                if g is not None:frames[rec['symbol']]=g
            except Exception as exc:
                records.append(dict(symbol=futures[fu],status='error',error=f'{type(exc).__name__}: {exc}'))
            if i%20==0:print('scanned',i,'/',len(jobs),flush=True)
    records.sort(key=lambda r:r['symbol'])
    counts=pd.Series([r['status'] for r in records]).value_counts().to_dict()
    candidates=[dict(code=r['code'],name=r['name'],symbol=r['symbol'],signal_date=str(cutoff.date()),
                     event_id=r['event_id']) for r in records if r.get('candidate')]
    payload=dict(as_of=str(cutoff.date()),generated_at=str(pd.Timestamp.now(tz='Asia/Shanghai')),
                 scope='mainboard_cached_market',universe_count=len(items),counts=counts,
                 scanned_count=len(frames),candidate_count=len(candidates),picks=candidates,
                 config=cfg,config_hash=config_hash(cfg),rows=records,refresh_errors=refresh_errors,
                 research_only=True,auto_trade=False)
    # 扫描产物与旧30股研究分开，不能把全市场范围字样套到旧回测上。
    temporary=OUT/'snapshot.json.tmp'
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
    temporary.replace(OUT/'snapshot.json')
    pd.DataFrame([{k:v for k,v in r.items() if k not in ('meta','plan')} for r in records]).to_csv(OUT/'coverage.csv',index=False)
    if backtest and frames:
        from .research import simulate
        # 按代码排序并使用引擎原候选排序，避免进程完成次序影响资金分配。
        stats,eq,orders,tr=simulate(dict(sorted(frames.items())),Policy(**cfg['policy']),
                                  start=f'{cutoff.year}-01-01',end=str(cutoff.date()))
        stats.update(universe_count=len(frames),scope='current_fresh_cache_subset',
                     scan_generated_at=payload['generated_at'],
                     warning='仅当前行情齐备子集，含当前名单/数据覆盖偏差，不是全A股历史回测')
        (OUT/'backtest_summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
        for tag,df in [('equity',eq),('orders',orders),('trades',tr)]:df.to_csv(OUT/f'{tag}.csv',index=False)
    report=['# 鲍鱼捞饭：主板动态扫描','',f'完整日线目标日期：{cutoff.date()}；范围内{len(items)}只，实际完成结构扫描{len(frames)}只，当日符合绑定条件{len(candidates)}只。',
            f'覆盖状态：{json.dumps(counts,ensure_ascii=False)}。',
            '不再要求来自策略16；每天重新按因子30/31/32筛选。主板范围与当前10%涨跌停引擎一致；按本地名称排除ST/退市标识，名称缓存并非历史逐日风险标识。',
            '缺行情、过期、历史不足、无成交量均不作为当日候选；未自动下单。候选只代表完整日线条件满足，下一交易日开盘仍须按价格、资金、整手、涨跌停和风险约束重新评估。',
            '扫描范围来自本地名称缓存与日线缓存并集，存在名称过期与覆盖缺口，不能称作已完成全A扫描。历史回测单独标记为当前齐备子集，不复用原30股成绩冒充扩池成绩。',
            '', '## 当日候选',*([f'- {r["code"]} {r["name"]}' for r in candidates] or ['无。']),
            '', '## 复现', '`python -m strategy.strategies.strategy3.market_scan --backtest`',
            '显式补齐整个范围的行情：`python -m strategy.strategies.strategy3.market_scan --refresh --backtest`（逐票请求，耗时较长，供应商失败会记入产物）。']
    if backtest and frames:
        report+=['','## 本次年内回放',
                 f'2026年初空仓起算，当前齐备的{len(frames)}只股票子集：收益{stats["total_return_pct"]:.2f}%，日线最大回撤{stats["max_drawdown_pct"]:.2f}%，闭环{stats["n_trades"]}笔，胜率{stats["win_rate"]*100:.1f}%。该子集存在当前覆盖偏差，不能代表全市场。']
    (OUT/'REPORT.md').write_text('\n'.join(report)+'\n')
    print(json.dumps({k:v for k,v in payload.items() if k not in ('rows','config','picks','refresh_errors')},ensure_ascii=False,indent=2),flush=True)
    return payload


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--as-of');ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--refresh',action='store_true');ap.add_argument('--backtest',action='store_true')
    run_scan(**vars(ap.parse_args()))
