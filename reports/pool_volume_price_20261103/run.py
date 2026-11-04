"""Point-in-time daily volume-price event study, current fixed universe."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
POOL=json.loads((ROOT/'pool.json').read_text())
HORIZONS=[1,2,3,5,10,20]
START,END='2025-01-01','2026-11-02'
BUY_FEE=.000096; SELL_FEE=.000596; SLIP=.001
(ROOT/'raw').mkdir(exist_ok=True)
def fetch(w):
    path=ROOT/'raw'/f"{w['code']}.json"
    if path.exists(): return
    r=requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                   params={'param':f"{w['sina']},day,2024-07-01,{END},900,qfq"},timeout=30)
    r.raise_for_status();j=r.json()['data'][w['sina']]
    bars=j.get('qfqday',j.get('day'))
    assert bars and bars[0][0]<'2024-10-01'
    path.write_text(json.dumps(bars,ensure_ascii=False,indent=2))
with ThreadPoolExecutor(max_workers=4) as pool:
    futures={pool.submit(fetch,w):w for w in POOL}
    for f in as_completed(futures):
        f.result();print('fetched',futures[f]['code'],flush=True)

def wilder_rsi(c,n=14):
    change=c.diff(); gain=change.clip(lower=0); loss=-change.clip(upper=0)
    out=pd.Series(np.nan,index=c.index);ag=al=None
    for i in range(n,len(c)):
        if i==n: ag=float(gain.iloc[1:n+1].mean());al=float(loss.iloc[1:n+1].mean())
        else: ag=(ag*(n-1)+gain.iloc[i])/n;al=(al*(n-1)+loss.iloc[i])/n
        out.iloc[i]=50 if ag==0 and al==0 else 100 if al==0 else 100-100/(1+ag/al)
    return out

frames=[]
for w in POOL:
    raw=json.loads((ROOT/'raw'/f"{w['code']}.json").read_text())
    d=pd.DataFrame([r[:6] for r in raw],columns=['date','open','close','high','low','volume'])
    d=d.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    for c in ['open','close','high','low','volume']:d[c]=d[c].astype(float)
    assert d.date.iloc[-1]==END and (d.volume>0).all()
    d['code']=w['code'];d['name']=w['name']
    d['body']=(d.close/d.open-1)*100
    d['change']=(d.close/d.close.shift()-1)*100
    d['volume_ratio']=d.volume/d.volume.shift().rolling(20).mean()
    d['volume_day_ratio']=d.volume/d.volume.shift()
    d['low60']=d.volume<=d.volume.rolling(60).min()
    d['high60']=d.volume>=d.volume.rolling(60).max()
    d['rsi14']=wilder_rsi(d.close)
    d['bias20']=(d.close/d.close.rolling(20).mean()-1)*100
    d['close_position']=(d.close-d.low)/(d.high-d.low).replace(0,np.nan)
    d['above_ma20']=d.close>d.close.rolling(20).mean()
    anchor=None;used=set();full=[];anchors=[];ages=[];ratios=[]
    for i,r in d.iterrows():
        age=i-anchor if anchor is not None else None
        eligible=anchor is not None and 1<=age<=10
        ratio=r.volume/d.iloc[anchor].volume if eligible else None
        hit=bool(eligible and ratio>=2 and r.body>=5-1e-9 and anchor not in used)
        full.append(hit);anchors.append(d.iloc[anchor].date if eligible else None)
        ages.append(age if eligible else None);ratios.append(ratio)
        if hit:used.add(anchor)
        if r.low60:anchor=i
    d['signal']=full;d['anchor_date']=anchors;d['anchor_age']=ages;d['anchor_volume_ratio']=ratios
    d['big_yang']=d.body>=5-1e-9
    d['volume_surge']=d.volume_ratio>=2
    d['entry_open']=d.open.shift(-1)
    # Conservative exclusion of possible opening limit-up; not a liquidity guarantee.
    d['entry_blocked']=d.entry_open/d.close-1>=.097
    for h in HORIZONS:
        d[f'close_forward_{h}']=(d.close.shift(-h)/d.close-1)*100
        # Buy next session open, H held trading sessions, minimum T+1 sell on session 2.
        if h>=2:
            d[f'net_{h}']=(d.close.shift(-h)*(1-SLIP)*(1-SELL_FEE)/(d.entry_open*(1+SLIP)*(1+BUY_FEE))-1)*100
            d.loc[d.entry_blocked,f'net_{h}']=np.nan
    frames.append(d[(d.date>=START)&(d.date<=END)])
allrows=pd.concat(frames,ignore_index=True)

def stats(x,col):
    v=x[col].dropna()
    return dict(n=len(v),mean=float(v.mean()) if len(v) else None,median=float(v.median()) if len(v) else None,
                win=float((v>0).mean()*100) if len(v) else None,min=float(v.min()) if len(v) else None)

masks={'全池股票日':pd.Series(True,index=allrows.index),
       '放量≥前20日均量2倍':allrows.volume_ratio>=2,
       '缩量≤前20日均量一半':allrows.volume_ratio<=.5,
       '60日天量':allrows.high60,'60日地量':allrows.low60,
       'RSI14≤30':allrows.rsi14<=30,'RSI14≥70':allrows.rsi14>=70,
       '实体≥5%大阳线':allrows.big_yang,
       '放量≥均量2倍且大阳线':allrows.volume_surge&allrows.big_yang,
       '地量后10日内2倍量大阳线首次':allrows.signal}
relations={};holding={}
for name,mask in masks.items():
    x=allrows[mask]
    relations[name]=dict(count=len(x),body=stats(x,'body'),change=stats(x,'change'),future5=stats(x,'close_forward_5'))
    holding[name]={str(h):stats(x,f'net_{h}') for h in HORIZONS if h>=2}
signal=allrows[allrows.signal]
forward={str(h):stats(signal,f'close_forward_{h}') for h in HORIZONS}
by_year={y:{str(h):stats(signal[signal.date.str.startswith(y)],f'net_{h}') for h in HORIZONS if h>=2} for y in ['2025','2026']}
common=signal[signal.net_20.notna()]
common_holding={str(h):stats(common,f'net_{h}') for h in HORIZONS if h>=2}
filters={'全部':signal,'RSI≤30':signal[signal.rsi14<=30],'30<RSI<70':signal[(signal.rsi14>30)&(signal.rsi14<70)],
         'RSI≥70':signal[signal.rsi14>=70],'收盘在日内上四分之一':signal[signal.close_position>=.75],
         '收盘高于MA20':signal[signal.above_ma20]}
filter_stats={name:stats(x,'net_5') for name,x in filters.items()}
# Independent per-stock, fixed-horizon trades: skip new signals until after exit.
nonoverlap={}
for h in [2,3,5,10,20]:
    picked=[]
    for frame in frames:
        free=-1
        for i in range(len(frame)):
            r=frame.iloc[i]
            if i<=free or not r.signal or pd.isna(r[f'net_{h}']):continue
            picked.append(r);free=i+h
    nonoverlap[str(h)]=stats(pd.DataFrame(picked),f'net_{h}') if picked else dict(n=0,mean=None,median=None,win=None,min=None)
result=dict(start=START,end=END,pool_count=len(POOL),stock_days=len(allrows),signal_count=len(signal),
            blocked_signal_entries=int(signal.entry_blocked.sum()),relations=relations,holding=holding,
            signal_forward=forward,by_year=by_year,common_holding=common_holding,filters=filter_stats,nonoverlap=nonoverlap)
(ROOT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
signal.to_json(ROOT/'signal_events.json',orient='records',force_ascii=False,indent=2)
allrows.to_json(ROOT/'all_stock_days.json',orient='records',force_ascii=False)
fmt=lambda v:'—' if v is None else f'{v:+.2f}%'
lines=['# 当前池量价与地量转放量研究','',
       f'{START}至{END}，当前固定池{len(POOL)}只，{len(allrows)}股票日；腾讯前复权日线，2024-07起预热。当前名单回看有选股偏差。',
       '地量/天量：含当日在内60个交易日最小/最大成交量（相等也算）。一般放量/缩量：相对前20个交易日均量≥2倍/≤0.5倍。',
       '用户信号：此前最近一次60日地量，距今1–10个交易日，今天成交量≥该日2倍，今日收盘/开盘−1≥5%；每个地量锚仅首次触发。',
       'RSI为Wilder RSI14；≤30为超卖分组，≥70为超买分组，非买卖保证。',
       '收盘信号当日无法在收盘前完整确认。可执行代理使用下一交易日开盘买，持有H个交易日在第H日收盘卖；最短H=2以遵守T+1。',
       '净收益扣双边佣金杂费0.0096%、卖出印花0.05%、双边各0.1%滑点；未含最低佣金、股数取整、资金槽位、冲击成本。',
       '下一开盘相对信号收盘≥9.7%不计入买入样本；退出仍为收盘可成交假设，未建模盘口排队。事件平均收益非组合收益。',
       '', '|条件|样本|当天平均实体|当天平均较昨收涨幅|后5日收盘均值（描述性）|', '|---|---:|---:|---:|---:|']
for name,s in relations.items(): lines.append(f"|{name}|{s['count']}|{fmt(s['body']['mean'])}|{fmt(s['change']['mean'])}|{fmt(s['future5']['mean'])}|")
lines+=['','## 地量后放量大阳线：下一开盘买入','',f'信号{len(signal)}个，开盘近涨停排除{int(signal.entry_blocked.sum())}个。每期限有效样本仅含完整前瞻窗口。',
        '|持有交易日|有效样本|平均净收益|中位数|盈利比例|最差单次|2025均值|2026均值|去重叠均值|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for h,s in holding['地量后10日内2倍量大阳线首次'].items():
    lines.append(f"|{h}|{s['n']}|{fmt(s['mean'])}|{fmt(s['median'])}|{fmt(s['win'])}|{fmt(s['min'])}|{fmt(by_year['2025'][h]['mean'])}|{fmt(by_year['2026'][h]['mean'])}|{fmt(nonoverlap[h]['mean'])}|")
lines+=['','## 同样本持有期对照（均有完整20日数据）','', '|持有日|样本|均值|中位数|盈利比例|','|---|---:|---:|---:|---:|']
for h,s in common_holding.items(): lines.append(f"|{h}|{s['n']}|{fmt(s['mean'])}|{fmt(s['median'])}|{fmt(s['win'])}|")
lines+=['','## 5日净收益的状态分组（探索性，不据此选最优）','', '|条件|样本|均值|中位数|盈利比例|','|---|---:|---:|---:|---:|']
for name,s in filter_stats.items(): lines.append(f"|{name}|{s['n']}|{fmt(s['mean'])}|{fmt(s['median'])}|{fmt(s['win'])}|")
lines+=['','结果仅为研究。收益相关于市场阶段和当前选股池；2025/2026分段也不是无偏盲测。全体信号及锚点日期、成交量倍数、RSI和前瞻结果保存在signal_events.json。',
        '下一步尾盘验证需14:55时点的累计量、现价、截至当时高低价；使用下一根可成交价格，不能用最终日量或收盘价倒推买点。']
(ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:result[k] for k in ['stock_days','signal_count','blocked_signal_entries','signal_forward','common_holding','by_year','filters']},ensure_ascii=False,indent=2))
