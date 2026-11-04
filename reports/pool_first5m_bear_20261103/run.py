"""Frozen current-pool retrospective: first 5-minute bearish candle vs daily body."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pandas as pd

ROOT=Path(__file__).resolve().parent
START, END='2026-10-03','2026-11-02'
pool=json.loads((ROOT/'pool.json').read_text())
(ROOT/'raw').mkdir(exist_ok=True)
def fetch(w):
    code=w['code']; path=ROOT/'raw'/f'{code}.json'
    if path.exists(): return
    u='https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_k=/CN_MarketDataService.getKLineData'
    response=requests.get(u,params=dict(symbol=w['sina'],scale=5,ma='no',datalen=1970),timeout=25)
    response.raise_for_status();body=response.text
    bars=json.loads(body[body.index('([')+1:body.rindex('])')+1])
    u='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    response=requests.get(u,params={'param':f"{w['sina']},day,2026-10-01,2026-11-02,100,"},timeout=25)
    response.raise_for_status();daily=response.json()['data'][w['sina']]['day']
    path.write_text(json.dumps(dict(bars=bars,daily=daily),ensure_ascii=False,indent=2))

errors={}
with ThreadPoolExecutor(max_workers=4) as executor:
    futures={executor.submit(fetch,w):w for w in pool}
    for f in as_completed(futures):
        w=futures[f]
        try: f.result(); print('fetched',w['code'],flush=True)
        except Exception as exc: errors[w['code']]=str(exc); print('ERROR',w['code'],str(exc),flush=True)
if errors:
    (ROOT/'errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2))
    raise RuntimeError(errors)

rows=[];excluded=[];expected=0
for w in pool:
    raw=json.loads((ROOT/'raw'/f"{w['code']}.json").read_text())
    bars=pd.DataFrame(raw['bars']);bars['date']=bars.day.str[:10]
    bars['clock']=bars.day.str[11:19]
    for c in ['open','high','low','close']: bars[c]=bars[c].astype(float)
    assert not bars.day.duplicated().any()
    for day in raw['daily']:
        date=day[0]
        if not START<=date<=END: continue
        expected+=1
        op,cl,hi,lo=map(float,day[1:5])
        block=bars[bars.date==date]
        first=block[block.clock=='09:35:00']
        last=block[block.clock=='15:00:00']
        reason=None
        if len(first)!=1 or len(last)!=1: reason='missing_0935_or_1500'
        elif abs(float(first.iloc[0].open)-op)>.010001: reason='daily_open_mismatch'
        elif abs(float(last.iloc[0].close)-cl)>.010001: reason='daily_close_mismatch'
        if reason:
            excluded.append(dict(code=w['code'],date=date,reason=reason));continue
        f=first.iloc[0]
        # Compare in integer cents, so equal-price candles remain neutral.
        sign=lambda a,b: (round(a*100)>round(b*100))-(round(a*100)<round(b*100))
        rows.append(dict(code=w['code'],name=w['name'],pool_source=w['pool_src'],date=date,
                         day_open=op,day_close=cl,first_open=float(f.open),first_close=float(f.close),
                         first_sign=sign(float(f.close),float(f.open)),day_sign=sign(cl,op),
                         first_body_pct=(float(f.close)/float(f.open)-1)*100,
                         body_pct=(cl/op-1)*100,after0935_pct=(cl/float(f.close)-1)*100,
                         bar_count=len(block)))
df=pd.DataFrame(rows)
def summarize(x):
    return dict(n=len(x),bear=int((x.day_sign<0).sum()),bull=int((x.day_sign>0).sum()),flat=int((x.day_sign==0).sum()),
                bear_pct=float((x.day_sign<0).mean()*100) if len(x) else None,
                bull_pct=float((x.day_sign>0).mean()*100) if len(x) else None,
                mean_body=float(x.body_pct.mean()) if len(x) else None,
                median_body=float(x.body_pct.median()) if len(x) else None,
                bear_body=float(x.loc[x.day_sign<0,'body_pct'].mean()) if (x.day_sign<0).any() else None,
                bull_body=float(x.loc[x.day_sign>0,'body_pct'].mean()) if (x.day_sign>0).any() else None,
                after0935_mean=float(x.after0935_pct.mean()) if len(x) else None)
selected=df[df.first_sign<0]
summary={name:summarize(x) for name,x in [('全部有效股票日',df),('首5分钟阴线',selected),('首5分钟阳线',df[df.first_sign>0]),('首5分钟平盘',df[df.first_sign==0])]}
by_stock=[]
for w in pool:
    x=selected[selected.code==w['code']]
    by_stock.append(dict(code=w['code'],name=w['name'],**summarize(x)))
result=dict(start=START,end=END,pool_count=len(pool),trading_days=sorted(df.date.unique()),expected_stock_days=expected,
            valid_stock_days=len(df),excluded=excluded,summary=summary,by_stock=by_stock,
            source_groups={s:summarize(selected[selected.pool_source==s]) for s in sorted(df.pool_source.unique())},
            events=rows)
(ROOT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
fmt=lambda v:'—' if v is None else f'{v:+.2f}%'
lines=['# 股票池首根5分钟收阴与当日日K实体统计','',
       f'区间：{START}至{END}。当前strategy1合并自选池共{len(pool)}只；固定当前名单回看，非历史逐日选股池。',
       f'数据：新浪5分钟不复权K线，腾讯日线交叉检查开盘/收盘。预期{expected}股票日，有效{len(df)}，排除{len(excluded)}。',
       '首根定义：09:30–09:35，以09:35结束标签识别；收盘小于开盘为阴，等于为平。日K阴阳也以开盘为基准，不看昨收。',
       '平均实体涨跌幅=(日收盘/日开盘−1)×100%，各股票日等权。包含已发生的首5分钟，不是09:35入场收益。',
       '', '|条件|样本|日阴|日阳|平|日阴率|日阳率|平均实体|中位数|阴线平均实体|阳线平均实体|09:35至收盘均值|',
       '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for name,s in summary.items():
    lines.append(f"|{name}|{s['n']}|{s['bear']}|{s['bull']}|{s['flat']}|{fmt(s['bear_pct'])}|{fmt(s['bull_pct'])}|{fmt(s['mean_body'])}|{fmt(s['median_body'])}|{fmt(s['bear_body'])}|{fmt(s['bull_body'])}|{fmt(s['after0935_mean'])}|")
lines+=['','|股票|首5分钟阴线次数|日阴|日阳|平|日阴率|平均实体|','|---|---:|---:|---:|---:|---:|---:|']
for s in by_stock:
    lines.append(f"|{s['name']} {s['code']}|{s['n']}|{s['bear']}|{s['bull']}|{s['flat']}|{fmt(s['bear_pct'])}|{fmt(s['mean_body'])}|")
lines+=['','样本集中于同一月份，同日股票相关，不视为独立试验。缺失/不一致数据不算未触发。排除明细和全部股票日见results.json。',
        '复现：项目环境执行本目录run.py；已缓存输入时不请求行情。']
(ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['events','by_stock']},ensure_ascii=False,indent=2))
