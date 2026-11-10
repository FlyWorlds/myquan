"""Isolated stop-rule study, not a portfolio or execution backtest."""
from pathlib import Path
import hashlib, json, math
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sources=['strategy1_open_stop_20261105','strategy16_run_20261105']
rows=[]; excluded=[]; manifest=[]; seen={}; conflicts=[]
for source in sources:
 for path in sorted((ROOT/'reports'/source/'minutes').glob('*.parquet')):
  if '_daily' in path.stem: continue
  d=pd.read_parquet(path); ts=pd.to_datetime(d.ts)
  if ts.dt.tz is not None: ts=ts.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
  d=d.assign(ts=ts).sort_values('ts')
  manifest.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
  for day,g in d.groupby(d.ts.dt.strftime('%Y-%m-%d')):
   if not '2026-10-27'<=day<='2026-11-05':continue
   g=g.copy();g['clock']=g.ts.dt.strftime('%H:%M'); g=g.set_index('clock')
   required=list(pd.date_range(day+' 09:31',day+' 10:00',freq='min').strftime('%H:%M'))+['15:00']
   key=(path.stem,day)
   if g.index.duplicated().any() or any(t not in g.index for t in required):
    excluded.append({'symbol':key[0],'day':day,'source':source,'reason':'duplicate or missing required minute'});continue
   sig=g.loc[required,['open','high','low','close']].to_json()
   if key in seen:
    if seen[key]!=sig:conflicts.append({'symbol':key[0],'day':day,'source':source})
    continue
   seen[key]=sig
   opening=float(g.loc['09:30','close']) if '09:30' in g.index else float(g.loc['09:31','open'])
   ref=float(g.loc['09:35','close']); close10=float(g.loc['10:00','close']); close15=float(g.loc['15:00','close'])
   assert min(opening,ref,close10,close15)>0
   r=dict(symbol=key[0],day=day,source=source,opening=opening,ref0935=ref,close10=close10,close15=close15)
   for mode,anchor,start in [('original',opening,'09:31'),('delay_only',opening,'09:35'),('ref0935',ref,'09:36')]:
    threshold=math.floor((anchor*.99+1e-10)*100)/100
    window=g[(g.index>=start)&(g.index<'10:00')]
    hit=window[window.close<=threshold+1e-9]
    stopped=not hit.empty; px=float(hit.iloc[0].close) if stopped else close10
    r.update({mode+'_hit':stopped,mode+'_time':hit.index[0] if stopped else '',mode+'_px':px,
              mode+'_return10':(px/opening-1)*100,
              mode+'_return15':((px if stopped else close15)/opening-1)*100})
   rows.append(r)
f=pd.DataFrame(rows);f.to_csv(OUT/'stock_days.csv',index=False)
summary={'scope':'isolated stop rule; hypothetical equal exposure to each stock-day; NOT actual positions or portfolio returns',
 'dates':sorted(f.day.unique()),'stocks':f.symbol.nunique(),'stock_days':len(f),'excluded':excluded,'conflicts_first_source_kept':conflicts,
 'modes':{},'early_original':{},'assumptions':['minute close proxy, no tick paths','no fees, slippage, limit-down liquidity, T+1 or other exit rules modeled','no stop by 10:00: mark at 10:00 or hold to 15:00 for separate sensitivity','current frozen pools: selection bias; short period; days and symbols correlated','09:30 auction close as official open proxy, otherwise first 09:31 bar open','09:35 close only used after completion; new anchor remains fixed until 10:00']}
for mode in ['original','delay_only','ref0935']:
 delta=f[mode+'_return10']-f.original_return10
 delta15=f[mode+'_return15']-f.original_return15
 summary['modes'][mode]={'stops':int(f[mode+'_hit'].sum()),'mean_return10_pct':f[mode+'_return10'].mean(),'mean_delta10_pp':delta.mean(),'mean_delta15_pp':delta15.mean(),'better10':int((delta>1e-9).sum()),'worse10':int((delta< -1e-9).sum()),'worst_delta10_pp':delta.min(),'best_delta10_pp':delta.max(),'avoided_original_stops':int((f.original_hit & ~f[mode+'_hit']).sum()),'new_stops':int((~f.original_hit & f[mode+'_hit']).sum())}
early=f[f.original_hit & (f.original_time<'09:35')]
summary['early_original']={'count':len(early),'recovered_above_sale_at_0935':int((early.ref0935>early.original_px).sum()),'recovered_above_sale_at_1000':int((early.close10>early.original_px).sum()),'ref0935_no_stop':int((~early.ref0935_hit).sum())}
f['delta10_pp']=f.ref0935_return10-f.original_return10
f['delta15_pp']=f.ref0935_return15-f.original_return15
f.groupby('day')[['delta10_pp','delta15_pp']].mean().to_csv(OUT/'daily_deltas.csv')
f.sort_values('delta10_pp').to_csv(OUT/'ranked_cases.csv',index=False)
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
(OUT/'sources.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
print(f.sort_values('delta10_pp').iloc[[0,1,-2,-1]][['symbol','day','opening','ref0935','original_time','original_px','ref0935_time','ref0935_px','delta10_pp']].to_string(index=False))
