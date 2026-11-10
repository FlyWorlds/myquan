"""Different trigger conditions: close confirmation A versus intrabar stop B."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
f=pd.read_csv(ROOT/'reports/first5m_stop_vs_close_20261109/all_stock_days.csv')
p=pd.read_csv(ROOT/'reports/morning_0935_reference_20261109/stock_days.csv')
f=f.merge(p[['symbol','day','close10','close15']],on=['symbol','day'],validate='one_to_one')
assert len(f)==440
results={}
for scenario in ['exact','tick_floor']:
 g=f.copy(); line=g.stop_px if scenario=='exact' else g.tick_floor_line
 g['a_sell']=g.close0935<line-1e-10
 g['b_sell']=g.first5_low<line-1e-10
 assert (~g.a_sell | g.b_sell).all()
 g['cohort']=np.where(g.a_sell,'both_sell',np.where(g.b_sell,'b_only_sell','neither_sell'))
 for horizon,mark in [('0935',g.close0935),('1000',g.close10),('1500',g.close15)]:
  g['a_px_'+horizon]=np.where(g.a_sell,g.close0935,mark)
  g['b_px_'+horizon]=np.where(g.b_sell,line,mark)
  for arm in ['a','b']:g[arm+'_ret_'+horizon]=(g[arm+'_px_'+horizon]/g.opening-1)*100
  g['delta_'+horizon]=(g['a_px_'+horizon]-g['b_px_'+horizon])/g.opening*100
  assert np.allclose(g['delta_'+horizon],g['a_ret_'+horizon]-g['b_ret_'+horizon])
 def metrics(x):
  r={'n':len(x),'a_sells':int(x.a_sell.sum()),'b_sells':int(x.b_sell.sum())}
  for h in ['0935','1000','1500']:
   d=x['delta_'+h]
   r[h]={'a_mean_pct':float(x['a_ret_'+h].mean()),'b_mean_pct':float(x['b_ret_'+h].mean()),'a_minus_b_pp':float(d.mean()),'better':int((d>1e-9).sum()),'worse':int((d< -1e-9).sum()),'equal':int((d.abs()<=1e-9).sum()),'worst_delta_pp':float(d.min()),'best_delta_pp':float(d.max())}
  return r
 results[scenario]={'all':metrics(g),'cohorts':{c:metrics(x) for c,x in g.groupby('cohort')}}
 daily=g.groupby('day')[[f'{a}_ret_{h}' for h in ['1000','1500'] for a in ['a','b']]+['delta_1000','delta_1500']].mean()
 daily.to_csv(OUT/f'{scenario}_daily.csv');g.to_csv(OUT/f'{scenario}_cases.csv',index=False)
 results[scenario]['daily']=daily.reset_index().to_dict('records')
 if scenario=='exact':
  print('EXAMPLES',g[g.cohort=='b_only_sell'].sort_values('delta_1500').iloc[[0,-1]][['symbol','day','opening','first5_low','close0935','close10','close15','delta_1500']].to_string(index=False))
results['method']={'dates':sorted(f.day.unique()),'stocks':int(f.symbol.nunique()),'scope':'same hypothetical equal opening notional for each stock-day; not actual holdings or portfolio returns','A':'09:35 close < open*0.99 -> sell at 09:35 close; otherwise hold','B':'09:30-09:35 low < open*0.99 -> ideal sell at open*0.99; otherwise hold','after0935':'no further exits or entries; mark remaining holdings at09:35,10:00,15:00 for separate horizon sensitivities','caveats':['exact threshold fill idealized; no fees slippage liquidity or other exits','short frozen-pool sample, selection bias and correlated stock-days','first5 low from completed09:31..09:35 1m bars; no tick path','tick_floor changes both threshold trigger membership and fill price']}
(OUT/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps({k:{'all':v['all'],'cohorts':v['cohorts']} for k,v in results.items() if k!='method'},ensure_ascii=False,indent=2))
