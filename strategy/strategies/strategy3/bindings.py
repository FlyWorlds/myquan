"""策略三·鲍鱼捞饭：组合因子30（结构）+31（止跌）+32（失效/退出）。"""
from strategy.core.protocols import bind_factor
from .combo_config import load_config
STRATEGY_ID='strategy3'
STRATEGY_NAME='策略三·鲍鱼捞饭'
_cfg=load_config()
_rule=_cfg['rule']
FACTOR_BINDINGS=(
    bind_factor('factor30',role='filter',label='结构前低破位',
                params={k:v for k,v in _rule.items() if k in ('support','window')},
                filter_desc='A底分型→上笔→B顶分型→相邻下笔破A；按当日可知状态识别'),
    bind_factor('factor31',role='entry',label='放量释放后止跌',
                params={k:v for k,v in _rule.items() if k in ('trigger','volume')},
                filter_desc='须同时通过因子30；下影/收复信号收盘形成，次开复核'),
    bind_factor('factor32',role='exit',label='冻结失效位与前低前高退出',params=_cfg['policy'],
                filter_desc='A/B/C在入场时冻结，C不下移；风险仓位、再破低止损及分批反弹退出'),
)
