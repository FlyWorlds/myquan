"""Frozen-pool paired replay: one additional stop, same initial portfolio and quotes."""
from backtest.compare_strategy1_pools import *
from strategy.minute import standardize_minute_1m

OUT=ROOT/'reports/strategy1_open_stop_20261105'
DAYS=['2026-10-30','2026-11-02','2026-11-03','2026-11-04','2026-11-05']

def collect_current(w):
    path=OUT/'minutes'/f'{w["sina"]}.parquet'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        raw=pd.read_parquet(path)
    else:
        raw=pull_akshare_1m(em_symbol=w['code'],sina_symbol=w['sina'],adjust='',retries=1)
        raw.to_parquet(path,index=False)
    m=normalize(raw,'ts')
    # Provider's auction snapshots have missing open=0, but a single observed price.
    # This does not invent a range or interpolate an absent minute.
    fixed=(m.open==0)&(m.high==m.low)&(m.low==m.close)&(m.close>0)
    m.loc[fixed,'open']=m.loc[fixed,'close']
    good=(m.low>0)&(m.low<=m[['open','close']].min(axis=1))&(m.high>=m[['open','close']].max(axis=1))
    bad=m[~good]
    m=m[good].copy()
    daily=normalize(pd.read_parquet(ROOT/'data_cache'/f'{w["sina"]}_daily_qfq.parquet'),'date')
    agg=[dict(date=pd.Timestamp(day)+pd.Timedelta(hours=15),open=float(b.iloc[0].open),high=float(b.high.max()),low=float(b.low.min()),close=float(b.iloc[-1].close)) for day,b in m.groupby(m.ts.dt.strftime('%Y-%m-%d')) if day in complete_days(m)]
    daily=normalize(pd.concat([daily,pd.DataFrame(agg)],ignore_index=True),'date')
    daily.to_parquet(OUT/'minutes'/f'{w["sina"]}_daily.parquet',index=False)
    cov=dict(code=w['code'],name=w['name'],complete=sorted(complete_days(m)),usable=sorted(usable_days(m)),auction_open_zero_fixed=int(fixed.sum()),invalid_removed=len(bad),invalid_times=bad.ts.astype(str).tolist(),source='strategy.minute.pull_akshare_1m: Eastmoney + Sina, unadjusted',first=str(m.ts.min()),last=str(m.ts.max()))
    print(w['code'],cov['complete'], 'fixed',int(fixed.sum()),'bad',len(bad),flush=True)
    return dict(w=w,minutes=m,daily=daily),cov

def main():
    pool=json.loads((OUT/'pool_snapshot.json').read_text())
    stocks=[]; coverage=[]
    for w in pool:
        s,c=collect_current(w);stocks.append(s);coverage.append(c)
        (OUT/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))
    common=sorted(set.intersection(*(set(c['complete']) for c in coverage)))
    missing=set(DAYS)-set(common)
    if missing: raise RuntimeError(f'Incomplete pool coverage: {missing}; see coverage.json')
    warm=[d for d in common if '2026-10-27'<=d<DAYS[0]]
    calendar=warm+DAYS
    runs={name:simulate(stocks,calendar,current_attack_wave=True,morning_open_stop=flag,morning_stop_start=DAYS[0]) for name,flag in [('baseline',False),('with_stop',True)]}
    for name,r in runs.items():
        (OUT/f'{name}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
        pd.DataFrame(r['trades']).to_csv(OUT/f'{name}_trades.csv',index=False,encoding='utf-8-sig')
    rows=[]
    base={name:next((e['equity'] for e in reversed(r['equity']) if e['date']<DAYS[0]),300000.) for name,r in runs.items()}
    assert base['baseline']==base['with_stop']
    previous=dict(base)
    for day in DAYS:
        row={'date':day}
        for name,r in runs.items():
            e=next(e['equity'] for e in r['equity'] if e['date']==day)
            row.update({name+'_equity':e,name+'_pnl':e-previous[name],name+'_daily_pct':(e/previous[name]-1)*100,name+'_cumulative_pct':(e/base[name]-1)*100})
            previous[name]=e
        row['pnl_difference']=row['with_stop_pnl']-row['baseline_pnl']
        rows.append(row)
    table=pd.DataFrame(rows)
    table.to_csv(OUT/'daily_comparison.csv',index=False,encoding='utf-8-sig')
    meta=dict(days=DAYS,warmup=warm,initial_cash=300000,period_initial_equity=base['baseline'],pool_size=len(pool),current_attack_wave=True,auction_factor29='excluded: historical auction tick paths unavailable',execution='completed 1m close observation; new stop fills at observed close, not threshold',fees='existing _buy_outlay/_sell_credit incl fees/slippage',selection_bias='current frozen pool and thresholds replayed backwards',limits='5 slots, 20% per slot, 2 new + 1 reentry/day; T+1',new_stop_trades=[t for t in runs['with_stop']['trades'] if t.get('exit_reason')=='s1_morning_open_stop'])
    (OUT/'methodology.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    print(table.to_string(index=False));print(json.dumps(meta,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
