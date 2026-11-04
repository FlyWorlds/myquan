"""Independent audit: registered factor signals, T+1, fees, non-overlap, NAV."""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]))
from strategy.factors.factor34 import compute
from strategy.costs import ENGINE_COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE_VALUE

BUY=(1+SLIPPAGE_VALUE)*(1+ENGINE_COMMISSION_RATE)
SELL=(1-SLIPPAGE_VALUE)*(1-ENGINE_COMMISSION_RATE-STAMP_TAX_RATE)
results=json.loads((ROOT/'results.json').read_text())
pools=json.loads((ROOT/'pools.json').read_text())
raw={};feature_cache={}
for f in (ROOT/'raw').glob('*.json'):
    d=pd.DataFrame([r[:6] for r in json.loads(f.read_text())],columns=['date','open','close','high','low','volume'])
    for c in ['open','close','high','low','volume']:d[c]=d[c].astype(float)
    raw[f.stem]=d
calendar=raw['000300_index'].date.tolist()
checked=0
for pool_id,result in results.items():
    for label in ['default','selected']:
        params=(dict(max_age=10,volume_multiple=2.,body_min=.05,hold_sessions=5)
                if label=='default' else result['selected'])
        for period in ['train','validation','holdout']:
            run=json.loads((ROOT/f'{pool_id}_{label}_{period}.json').read_text())
            nav=np.zeros(len(run['dates']))
            for w in pools[pool_id]:
                code=w['code'];d=raw[code];key=(code,params['max_age'],params['volume_multiple'],params['body_min'])
                if key not in feature_cache:
                    feature_cache[key]=compute(d,max_age=params['max_age'],volume_multiple=params['volume_multiple'],body_min=params['body_min']).set_index('date')
                features=feature_cache[key]
                trades=[t for t in run['trades'] if t['code']==code]
                incomplete=[t for t in run['open_positions'] if t['code']==code]
                previous_exit=''
                for t in trades:
                    assert features.loc[t['signal_date'],'candidate']
                    entry=calendar.index(t['entry_date']);exit=calendar.index(t['exit_date'])
                    assert calendar[entry-1]==t['signal_date']
                    assert exit-entry+1>=params['hold_sessions']>=2
                    assert t['entry_date']>previous_exit
                    previous_exit=t['exit_date']
                    assert abs(t['net']-(t['exit_price']*SELL/(t['entry_price']*BUY)-1))<1e-12
                    checked+=1
                entries={t['entry_date']:t for t in trades+incomplete}
                exits={t['exit_date']:t for t in trades}
                bydate=d.set_index('date');mark=bydate.close.reindex(calendar).ffill()
                cash=1.;qty=0.
                for i,date in enumerate(run['dates']):
                    if date in entries:
                        assert qty==0
                        cost=float(bydate.loc[date,'open'])*BUY
                        qty=.95*cash/cost;cash*=.05
                    if date in exits:
                        cash+=qty*float(bydate.loc[date,'close'])*SELL;qty=0
                    nav[i]+=cash+(qty*float(mark.loc[date]) if qty else 0)
            nav/=len(pools[pool_id])
            assert np.max(np.abs(nav-np.array(run['equity'])))<1e-10,(pool_id,label,period)
            assert abs(nav[-1]-1-result['models'][label][period]['portfolio']['return_total'])<1e-10
audit=dict(completed_trade_checks=checked,equity_curves_checked=12,
           checks=['registered_factor_signals','T+1_and_horizon','no_overlap','fee_arithmetic','independent_cash_and_mark_NAV'])
(ROOT/'validation.json').write_text(json.dumps(audit,indent=2))
print(audit)
