"""策略三组合因子唯一配置来源；默认是研究绑定，不发送交易指令。"""
from __future__ import annotations
import json
from .reversal import ROOT, Policy
ACTIVE_PATH=ROOT/'backtest/strategy3_abalone/stop_study/binding_config.json'


def load_config():
    if ACTIVE_PATH.exists():return json.loads(ACTIVE_PATH.read_text())
    p=Policy(stop_mode='event_low',stop_buffer_atr=.3,take_mode='structure',risk_budget=.005,
             initial=1.,reduce=.5,max_entry_risk=.08,stop_trigger='close')
    return dict(rule={'support':'chan','window':10,'trigger':'shadow','volume':1.5},policy=p.dict(),
                status='research_only',selection_note='尚未完成本轮止损比较')


def config_from_bindings(bindings):
    bs={b.factor_id:b for b in bindings if b.enabled}
    if set(bs)!={'factor30','factor31','factor32'}:raise ValueError('策略3须同时绑定结构、止跌、退出三个因子')
    return dict(rule={**bs['factor30'].params,**bs['factor31'].params},policy=dict(bs['factor32'].params),status='research_only')


def compose_entry(frames,rule):
    from strategy.factors.factor30 import signal as structure
    from strategy.factors.factor31 import signal as exhaustion
    out={}
    for s,f in frames.items():
        g=f.copy()
        g['stabilize']=[structure(r,**rule)['passed'] and exhaustion(r,**rule)['passed'] for r in f.itertuples()]
        g['anchor_date']=g.event_id
        out[s]=g
    return out
