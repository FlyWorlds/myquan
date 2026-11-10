"""Paired first-five-minute exit-price scenario requested by user; no production changes."""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
prior=ROOT/'reports/morning_0935_reference_20261109'
manifest=json.loads((prior/'sources.json').read_text()); paths={m['path']:m for m in manifest}
records=[]; cache={}
for r in pd.read_csv(prior/'stock_days.csv').itertuples():
 path=ROOT/'reports'/r.source/'minutes'/f'{r.symbol}.parquet'
 if path not in cache:
  assert hashlib.sha256(path.read_bytes()).hexdigest()==paths[str(path.relative_to(ROOT))]['sha256']
  d=pd.read_parquet(path); t=pd.to_datetime(d.ts)
  if t.dt.tz is not None:t=t.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
  cache[path]=d.assign(ts=t)
 d=cache[path]; g=d[(d.ts>=pd.Timestamp(r.day+' 09:31'))&(d.ts<=pd.Timestamp(r.day+' 09:35'))].sort_values('ts')
 assert len(g)==5 and g.ts.nunique()==5
 assert (g.low>0).all() and (g.low<=g[['open','close']].min(axis=1)).all() and (g.high>=g[['open','close']].max(axis=1)).all()
 opening=r.opening; line=opening*.99; low=float(g.low.min()); close=float(g.iloc[-1].close)
 assert abs(close-r.ref0935)<1e-8
 hit=low<line-1e-10
 records.append(dict(symbol=r.symbol,day=r.day,opening=opening,first5_low=low,close0935=close,stop_px=line,triggered=hit,
  triggered_before0935=bool((g.iloc[:4].low<line-1e-10).any()),
  first_breach=str(g[g.low<line-1e-10].iloc[0].ts) if hit else '',
  stop_return_pct=-1.,close_return_pct=(close/opening-1)*100,delta_pp=(close-line)/opening*100,
  tick_floor_line=np.floor((line+1e-10)*100)/100))
f=pd.DataFrame(records); h=f[f.triggered].copy()
def summary(g):
 return dict(n=len(g),close_better=int((g.delta_pp>1e-9).sum()),close_worse=int((g.delta_pp< -1e-9).sum()),same=int((g.delta_pp.abs()<=1e-9).sum()),mean_close_return_pct=float(g.close_return_pct.mean()),mean_delta_pp=float(g.delta_pp.mean()),median_delta_pp=float(g.delta_pp.median()),best_delta_pp=float(g.delta_pp.max()),worst_delta_pp=float(g.delta_pp.min()))
s={'all_stock_days':len(f),'stocks':int(f.symbol.nunique()),'dates':sorted(f.day.unique()),'triggered':summary(h),'strict_before_0935_sensitivity':summary(f[f.triggered_before0935]),'mean_delta_all_stock_days_pp':float(h.delta_pp.sum()/len(f)), 'method':'low(09:31..09:35)<open*0.99; A exact theoretical open*0.99 fill; B same triggered cohort exit at completed 09:35 close; normalize by open; hypothetical equal opening notional; not portfolio return', 'limitations':['No fees/slippage/liquidity or other exit rules; exact threshold fill is user-specified ideal assumption','No actual position filter, no T+1 execution simulation, frozen historical pools and short correlated sample','09:30 auction close as open proxy, else 09:31 open; first completed 5m ends at09:35','Exact 99% price can be off tick; tick-floor sensitivity separately shown']}
floor=f[f.first5_low < f.tick_floor_line-1e-10].copy();floor['delta_pp']=(floor.close0935-floor.tick_floor_line)/floor.opening*100
s['tick_floor_sensitivity']=summary(floor)
daily=h.groupby('day').apply(lambda g:pd.Series(summary(g)),include_groups=False)
f.to_csv(OUT/'all_stock_days.csv',index=False);h.sort_values('delta_pp').to_csv(OUT/'triggered_cases.csv',index=False);daily.to_csv(OUT/'daily.csv')
(OUT/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2));(OUT/'sources.json').write_text(json.dumps(manifest,indent=2))
assert len(f)==440 and len(f.drop_duplicates(['symbol','day']))==440
assert np.allclose(h.close_return_pct-h.stop_return_pct,h.delta_pp)
assert s['triggered']['close_better']+s['triggered']['close_worse']+s['triggered']['same']==len(h)
print(json.dumps(s,ensure_ascii=False,indent=2));print(daily.to_string());print(h.sort_values('delta_pp').iloc[[0,-1]][['symbol','day','opening','first5_low','stop_px','close0935','delta_pp']].to_string(index=False))
