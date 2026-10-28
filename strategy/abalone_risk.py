"""结构反弹入场价位：纯函数，A/B/C均取信号收盘快照，不使用买入日极值。"""
from __future__ import annotations
import math
from typing import Mapping, Any


def value(row, name, default=None):
    return row.get(name,default) if isinstance(row,Mapping) else getattr(row,name,default)


def entry_plan(row, entry_px:float, config:Mapping[str,Any])->dict:
    px=float(entry_px)
    mode=config.get('stop_mode','cost')
    def num(name):
        try:return float(value(row,name,float('nan')))
        except (ValueError,TypeError):return float('nan')
    a,b,c,atr=[num(name) for name in ('anchor','peak','trough','atr')]
    atr_buffer=float(config.get('stop_buffer_atr',.3))
    pct_buffer=float(config.get('stop_buffer_pct',0.))
    cost_stop=px*(1-float(config.get('stop',.08)))
    structural=(c*(1-pct_buffer)-atr_buffer*atr) if math.isfinite(c) and math.isfinite(atr) else float('nan')
    stop=structural if mode=='event_low' else max(structural,cost_stop) if mode=='hybrid' else cost_stop
    target_mode=config.get('take_mode','cost')
    second=None
    if target_mode=='structure':
        if not all(math.isfinite(x) for x in (a,b,c)) or not c<a<b:
            return dict(allowed=False,reason='缺少有效A/B/C结构')
        if px<a:
            target=a;second=b;location='前低之下'
        elif px<b:
            target=b;location='已收复前低'
        else:
            return dict(allowed=False,reason='开盘已越前高，反弹目标已兑现')
    else:
        target=a if target_mode=='anchor' else b if target_mode=='swing_top' else px*(1+float(config.get('take',.1)))
        location='前低之下' if math.isfinite(a) and px<a else '已收复前低'
    if not all(math.isfinite(x) for x in (px,stop,target)) or px<=0 or stop>=px or stop<=0:
        return dict(allowed=False,reason='失效位无效或开盘已跌穿失效位')
    risk=(px-stop)/px
    rr=(target-px)/(px-stop)
    allowed=risk<=float(config.get('max_entry_risk',1.))+1e-12 and rr+1e-12>=float(config.get('min_rr',0.))
    return dict(allowed=allowed,reason='' if allowed else '开盘风险距离或空间比未过门',
                entry_px=px,stop_px=stop,target_px=target,second_target_px=second,
                risk_pct=risk,reward_risk=rr,anchor=a,prior_high=b,event_low=c,atr=atr,
                location=location,
                breach_wave_ratio=(a-c)/(b-a) if b>a>c else None,
                rebound_to_a=(px-c)/(a-c) if a>c else None)
