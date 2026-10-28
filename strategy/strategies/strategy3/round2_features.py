"""第二轮：已知破位结构进入反弹确认阶段；所有特征仅依赖当前与过去。"""
from __future__ import annotations
import numpy as np
import pandas as pd

PATTERNS=('shadow_confirm','reclaim2','retest','spring','low_confirm2','dry_reversal','bull_engulf','momentum_turn')


def enrich_features(frame:pd.DataFrame,*,allow_rebound=False)->pd.DataFrame:
    f=frame.copy().reset_index(drop=True)
    if f.empty:return f
    c=f.close;ma5=c.rolling(5,min_periods=5).mean();ma20=c.rolling(20,min_periods=20).mean()
    delta=c.diff();gain=delta.clip(lower=0).rolling(14,min_periods=10).mean()
    loss=(-delta.clip(upper=0)).rolling(14,min_periods=10).mean()
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    old_setup=None;pending_rows=[];finished=set()
    for i,row in enumerate(f.to_dict('records')):
        r=row.copy();valid=False
        if old_setup is not None:
            if i-old_setup['break_i']>10 or r['close']>=old_setup['peak']:
                finished.add(old_setup['event_id'])
                old_setup=None
        if allow_rebound:
            if old_setup is None and r['broken'] and r['event_id'] not in finished and r['close']<r['peak'] and 0<=r['break_age']<=10:
                old_setup=dict(event_id=r['event_id'],anchor=r['anchor'],peak=r['peak'],trough=r['trough'],
                    break_i=i-int(r['break_age']),break_volume=r['break_volume'],anchor_date=r['anchor_date'],
                    top_date=r['top_date'],known_date=r['known_date'],accelerated=r['accelerated'],
                    stage20=r['stage20'],stage60=r['stage60'],stage120=r['stage120'])
            if old_setup is not None:
                a=old_setup
                a['trough']=min(a['trough'],r['low'])
                a['break_volume']=max(a['break_volume'],r['vol_ratio'])
                for k in ('event_id','anchor','peak','trough','anchor_date','top_date','known_date','accelerated','stage20','stage60','stage120','break_volume'):
                    r[k]=a[k]
                r['break_age']=i-a['break_i'];r['depth']=max(0.,1-a['trough']/a['anchor'])
                r['broken']=True;valid=True
        r['setup_valid']=bool(valid)
        pending_rows.append(r)
    f=pd.DataFrame(pending_rows)
    # 所有确认信号要求同一轮结构；前一轮下影线不能用于本轮入场。
    recent_shadow=None;above=[];flags=[];prior_event=None
    for i,r in enumerate(f.itertuples()):
        same=i>0 and r.event_id and r.event_id==prior_event
        if not same:recent_shadow=None;above=[]
        prev=f.iloc[i-1] if i else None
        same2=bool(same and i>=2 and f.event_id.iloc[i-2]==r.event_id)
        shadow_confirm=bool(recent_shadow and 0<i-recent_shadow['i']<=3 and r.close>recent_shadow['high'] and r.low>=recent_shadow['low'])
        reclaim2=bool(same and prev.broken and prev.break_age>=0 and r.close>=r.anchor and prev.close>=r.anchor and r.low>=prev.low)
        retest=bool(any(1<=i-j<=5 for j in above) and r.anchor-.5*r.atr<=r.low<=r.anchor+.3*r.atr and r.close>=r.anchor and r.close>r.open)
        spring=bool(r.low<r.anchor<=r.close and r.close>r.open)
        low_confirm2=bool(same2 and r.low>=prev.low>=f.low.iloc[i-2] and r.close>prev.high)
        dry_reversal=bool(same2 and r.vol_ratio<=.8 and r.low>=prev.low>=f.low.iloc[i-2] and r.close>prev.close)
        bull_engulf=bool(same and prev.close<prev.open and r.open<=prev.close and r.close>prev.open and r.close>r.open)
        momentum_turn=bool(same and np.isfinite(ma5.iloc[i]) and r.close>ma5.iloc[i] and prev.close<=ma5.iloc[i-1]
                           and r.close>prev.high and rsi.iloc[i]>rsi.iloc[i-1])
        wave=(r.anchor-r.trough)/(r.peak-r.anchor) if r.peak>r.anchor and np.isfinite(r.trough) else np.inf
        flags.append(dict(shadow_confirm=shadow_confirm,reclaim2=reclaim2,retest=retest,spring=spring,
                          low_confirm2=low_confirm2,dry_reversal=dry_reversal,bull_engulf=bull_engulf,
                          momentum_turn=momentum_turn,
                          avoid_weak=bool(i>=25 and r.close>=.95*ma20.iloc[i] and ma20.iloc[i]>=.98*ma20.iloc[i-5]),
                          wave_ok=bool(0<=wave<=.5),depth_ok=bool(.02<=r.depth<=.08),breach_wave_ratio=wave))
        if r.shadow and r.broken and r.break_age>=0:recent_shadow=dict(i=i,high=r.high,low=r.low)
        if r.broken and r.break_age>=0 and r.close>=r.anchor:above.append(i)
        above=[j for j in above if i-j<=5]
        prior_event=r.event_id
    return pd.concat([f,pd.DataFrame(flags)],axis=1)


def entry_mask(f,rule):
    structure=(f.broken & f.down_leg) if not rule.get('allow_rebound') else (f.broken & f.setup_valid)
    mask=structure & f.break_age.between(0,rule.get('window',10)) & f.break_volume.ge(rule.get('volume',1.5))
    trigger=rule['trigger']
    mask &= f[trigger] if trigger not in ('recover','either') else f.recovered if trigger=='recover' else (f.shadow|f.recovered)
    quality=rule.get('quality_filter','none')
    if quality!='none':mask &= f[{'avoid_weak':'avoid_weak','wave':'wave_ok','depth':'depth_ok'}[quality]]
    return mask.fillna(False)


def as_frames(frames,rule):
    output={}
    for s,raw in frames.items():
        f=enrich_features(raw,allow_rebound=rule.get('allow_rebound',False))
        f['stabilize']=entry_mask(f,rule);f['anchor_date']=f.event_id
        output[s]=f
    return output
