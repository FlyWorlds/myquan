"""当前中证1000主板池的恐慌度分层研究；固定持有期事件研究，非组合回测。"""
from __future__ import annotations
import json
import math
import pandas as pd
from .manual_scan import OUT, SCOPE, read_json, write_json
from .combo_config import compose_entry, config_from_bindings
from .bindings import FACTOR_BINDINGS
from .market_scan import config_hash
from strategy.abalone_risk import entry_plan
from strategy.costs import ENGINE_COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE_VALUE


def current_panic(scan, valid):
    total=int(scan.get('scanned_count',0)); universe=int(scan.get('universe_count',0))
    warnings=sum(r.get('status')=='ready' and bool(r.get('warning')) for r in scan.get('rows',[]))
    return dict(rate=warnings/total if valid and total else None,warningCount=warnings,
                monitoredCount=total,coverage=total/universe if universe else None)


def summarize(samples):
    buckets=[]
    for low in range(0,100,10):
        for horizon in (5,10,20):
            rows=[r for r in samples if low<=r['panic_pct'] and (r['panic_pct']<low+10 or low==90 and r['panic_pct']==100) and r['horizon']==horizon]
            values=[r['return_pct'] for r in rows]; n=len(values); wins=sum(v>0 for v in values)
            p=wins/n if n else None
            # Wilson区间仅反映事件样本数量，不假设同日股票相互独立。
            interval=None
            if n:
                z=1.96; center=(p+z*z/(2*n))/(1+z*z/n); half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
                interval=[max(0,center-half),min(1,center+half)]
            buckets.append(dict(label=f'{low}–{low+10}%',horizon=horizon,n=n,days=len({r['signal_date'] for r in rows}),
                                winRate=p,meanReturnPct=sum(values)/n if n else None,interval=interval))
    return buckets


def run(*, scan=None, output=None):
    output=output or OUT
    scan=scan if scan is not None else read_json(output/'snapshot.json',{})
    if scan.get('scope')!=SCOPE:raise ValueError('没有中证1000手动扫描快照')
    cfg=config_from_bindings(FACTOR_BINDINGS)
    if scan.get('config_hash')!=config_hash(cfg):raise ValueError('扫描配置已改变，请重新扫描')
    frames={}; missing=[]
    for r in scan['rows']:
        if r['status']!='ready':continue
        path=output/'features'/f"{r['symbol']}.parquet"
        if not path.exists():missing.append(r['symbol']);continue
        f=pd.read_parquet(path); f=f[f.date<=pd.Timestamp(scan['as_of'])].reset_index(drop=True)
        frames[r['symbol']]=f
    if missing:raise ValueError(f'缺少{len(missing)}份特征缓存，请重新扫描')
    # 预热120根日线后才计入当日有效分母；不把未上市/历史不足补为无预警。
    all_rows=pd.concat([f.iloc[119:][['date','broken']] for f in frames.values()],ignore_index=True)
    daily=all_rows.groupby('date').agg(monitored=('broken','size'),warnings=('broken','sum'))
    daily['panic_pct']=daily.warnings/daily.monitored*100
    daily['coverage']=daily.monitored/scan['universe_count']
    samples=[]
    for symbol,f in frames.items():
        g=compose_entry({symbol:f},cfg['rule'])[symbol]; seen=set()
        for i,r in enumerate(g.itertuples()):
            if i<119 or i+1>=len(g) or not r.broken or not r.stabilize or not r.event_id or r.event_id in seen:continue
            date=pd.Timestamp(r.date)
            if date not in daily.index or daily.loc[date,'coverage']<.95:continue
            entry=g.iloc[i+1]; price=float(entry.open)*(1+SLIPPAGE_VALUE)
            if not .902<float(entry.open)/float(r.close)<1.098:continue
            if not entry_plan(r,price,cfg['policy'])['allowed']:continue
            seen.add(r.event_id)
            for horizon in (5,10,20):
                end=i+horizon
                if end>=len(g):continue  # 尚未走完持有期的样本不计失败。
                sell=float(g.iloc[end].close)*(1-SLIPPAGE_VALUE)
                ret=(sell*(1-ENGINE_COMMISSION_RATE-STAMP_TAX_RATE)/(price*(1+ENGINE_COMMISSION_RATE))-1)*100
                samples.append(dict(symbol=symbol,event_id=r.event_id,signal_date=str(date.date()),entry_date=str(entry.date.date()),
                                    exit_date=str(g.iloc[end].date.date()),horizon=horizon,panic_pct=float(daily.loc[date,'panic_pct']),return_pct=ret))
    result=dict(asOf=scan['as_of'],configHash=config_hash(cfg),scope=SCOPE,universeCount=scan['universe_count'],
                period=[min((r['signal_date'] for r in samples),default=scan['as_of']),max((r['signal_date'] for r in samples),default=scan['as_of'])],buckets=summarize(samples),
                recentBuckets=summarize([r for r in samples if r['signal_date']>='2025-01-01']),
                earlierBuckets=summarize([r for r in samples if r['signal_date']<'2025-01-01']),
                note='当前成分股回溯，存在存活及选股偏差；覆盖率≥95%，预热120根日线，同股票同结构事件仅首个可买信号。次开买入，持有5/10/20根个股日线收盘卖出，扣双边费税及滑点；不执行策略止损/减仓，不等于实际策略胜率。同日样本相关，区间仅供描述，未做样本外验证。')
    write_json(output/'panic_study.json',result)
    pd.DataFrame(samples).to_csv(output/'panic_samples.csv',index=False)
    daily.to_csv(output/'panic_daily.csv')
    return result


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,allow_nan=False))
