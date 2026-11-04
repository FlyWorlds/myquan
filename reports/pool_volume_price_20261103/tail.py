"""14:55 observable signal; next 5m bar open fill proxy, with coverage audit."""
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parent
MINUTES=ROOT.parent/'pool_first5m_bear_20261103'
pool=json.loads((ROOT/'pool.json').read_text())
events=[];coverage=[];excluded=[]
for w in pool:
    raw=json.loads((ROOT/'raw'/f"{w['code']}.json").read_text())
    d=pd.DataFrame([r[:6] for r in raw],columns=['date','open','close','high','low','volume'])
    for c in ['open','close','high','low','volume']:d[c]=d[c].astype(float)
    d['low60']=d.volume<=d.volume.rolling(60).min()
    mraw=json.loads((MINUTES/'raw'/f"{w['code']}.json").read_text())
    m=pd.DataFrame(mraw['bars']);m['date']=m.day.str[:10];m['clock']=m.day.str[11:19]
    for c in ['open','close','volume']:m[c]=m[c].astype(float)
    actual_open={r[0]:float(r[1]) for r in mraw['daily']}
    used=set()
    for i,r in d.iterrows():
        if not '2026-10-03'<=r.date<='2026-11-02':continue
        bars=m[(m.date==r.date)&(m.clock>='09:35:00')&(m.clock<='15:00:00')].sort_values('day')
        before=bars[bars.clock<='14:55:00'];trigger=bars[bars.clock=='14:55:00'];after=bars[bars.clock=='15:00:00']
        if len(bars)!=48 or len(trigger)!=1 or len(after)!=1:
            excluded.append(dict(code=w['code'],date=r.date,reason='incomplete_48_bars'));continue
        # Tencent volumes are lots; Sina volumes are shares. Check using completed day, QA only.
        volume_error=abs(bars.volume.sum()/100/r.volume-1)
        if volume_error>.02:
            excluded.append(dict(code=w['code'],date=r.date,reason='volume_units_or_coverage',error=volume_error));continue
        opening=float(bars.iloc[0].open)
        if r.date not in actual_open or abs(opening-actual_open[r.date])>.010001:
            excluded.append(dict(code=w['code'],date=r.date,reason='open_mismatch'));continue
        coverage.append(dict(code=w['code'],date=r.date,volume_error=volume_error))
        anchors=d.iloc[max(0,i-10):i];anchors=anchors[anchors.low60]
        if anchors.empty:continue
        a=anchors.iloc[-1];anchor=a.date
        price=float(trigger.iloc[0].close);volume=before.volume.sum()/100
        if anchor in used or volume<a.volume*2 or price/opening-1<.05-1e-9:continue
        # Prior raw close derived from same-day adjustment scaling (no ex-date candidates accepted).
        scale=r.open/opening;prior_raw=d.iloc[i-1].close/scale
        fill_raw=float(after.iloc[0].open)
        if price/prior_raw-1>=.097 or fill_raw/prior_raw-1>=.097:
            excluded.append(dict(code=w['code'],date=r.date,reason='signal_near_limit_up'));continue
        used.add(anchor);entry=fill_raw*scale
        row=dict(code=w['code'],name=w['name'],date=r.date,anchor=anchor,
                 volume_ratio=float(volume/a.volume),body1455=(price/opening-1)*100,
                 entry_raw=fill_raw,entry_adjusted=entry)
        for h in [1,2,3,5,10,20]:
            row[f'net_{h}']=float((d.iloc[i+h].close*(1-.001)*(1-.000596)/(entry*(1+.001)*(1+.000096))-1)*100) if i+h<len(d) else None
        events.append(row)
summary={}
e=pd.DataFrame(events)
for h in [1,2,3,5,10,20]:
    v=e[f'net_{h}'].dropna() if len(e) else pd.Series(dtype=float)
    summary[str(h)]=dict(n=len(v),mean=float(v.mean()) if len(v) else None,median=float(v.median()) if len(v) else None,win=float((v>0).mean()*100) if len(v) else None)
result=dict(valid_stock_days=len(coverage),excluded=excluded,events=events,summary=summary)
(ROOT/'tail_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
print(json.dumps(result,ensure_ascii=False,indent=2))
