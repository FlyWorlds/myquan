"""鲍鱼捞饭：结构前低破位→放量止跌→冻结失效位与A/B目标退出。"""
from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from .bindings import FACTOR_BINDINGS,STRATEGY_ID,STRATEGY_NAME
from .decision import create_decision_engine


def run_strategy3(*,research='bound',**kwargs):
    if research=='scan':
        from .manual_scan import start
        if kwargs:raise TypeError('手动监控扫描使用固定中证1000范围；历史扫描请显式调用研究模块')
        return start()
    if research=='bound':
        from .bound_backtest import run_bound
        return run_bound(**kwargs)
    if kwargs:raise TypeError('挖掘研究使用固定训练/验证区间；日期参数仅用于已绑定组合重放')
    if research=='stops':
        from .stop_study import run
    elif research=='mining':
        from .factor_mining import run
    else:raise ValueError('research只支持scan/bound/stops/mining')
    return run()


register_strategy(StrategySpec(id=STRATEGY_ID,name=STRATEGY_NAME,
    description='因子30结构前低破位+因子31放量止跌+因子32冻结止损/A前低B前高分批退出；日线研究绑定',
    factor_bindings=FACTOR_BINDINGS,run=run_strategy3,default_config={},
    print_rules=lambda:compose_rules(STRATEGY_NAME,bindings=FACTOR_BINDINGS),decision_factory=create_decision_engine,
    aliases=('s3','鲍鱼捞饭','策略三'),implemented=True,
    meta={'execution':'daily_bound_research','universe':'csi1000_mainboard_manual','research_only':True,
          'mode':'portfolio','auto_trade':False,'factors':('factor30','factor31','factor32')}))
