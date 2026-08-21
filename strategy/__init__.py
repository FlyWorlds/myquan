"""多策略 + 多因子可插拔框架。

架构（开闭原则）：
  · factors/factor1..7              — 因子层：信号/价位规则
  · strategies/strategyN/
      bindings.py + decision.py     — 策略层(绑定) + 决策层(买卖)
  · core/                           — 协议 / MarketContext / Decision / 注册表
  · backtest.py / runner.py         — 执行层（下单与回测）

默认生效：援军战法（strategy1）= 因子1（开盘±2.5% 一次打满）+ 因子2（回撤预警）。
动量：因子3（策略五截面组合 / 单票时序）。因子4 = 牛市持股 regime。
策略六：因子6 组合动量 ETF 轮动。策略七：因子5事件开仓、单主题一只、固定持有五日的五槽位策略。
策略八：因子7 行业 ETF 普通动量 + 改进残差动量月频 Top3。
兼容旧 API：run_open_break（仅因子1交易）/ open_break3 / STRATEGY_RULES 等保持可用。
"""

from strategy.open_break import (
    DEFAULT_PCT,
    ENTRY_PCT,
    LOT_SIZE,
    NEAR_POINTS,
    NEAR_FACTOR_PCT,
    PREV_SMALL_YANG_PCT,
    REASON_STOP,
    STOP_PCT,
    STRATEGY_RULES,
    TICK_SIZE,
    bar_shape,
    ceil_to_tick,
    entry_trigger_price,
    floor_to_tick,
    has_double_yang_before,
    is_t1_buy_day,
    is_yang,
    is_yin,
    prev_day_allows_entry,
    stop_trigger_price,
    strategy_levels,
    strategy_signal,
)
from strategy.config import (
    KAICHENG,
    TIANTONG,
    HANGTIANDIANZI,
    XIEXINNENGKE,
    ZZ500_ETF,
    KCZZ_ETF,
    BacktestConfig,
)
from strategy.data import fetch_daily
from strategy.base import CommonBacktestParams, run_akquant_backtest, run_backtest_pipeline
from strategy.minute import (
    fetch_minute_1m,
    fetch_minute_5m,
    fetch_minute_30m,
    pull_akshare_1m,
    standardize_minute_1m,
)
from strategy.runner import (
    apply_strategy_config,
    build_open_break_strategy,
    run_momentum,
    run_open_break,
    run_open_break_backtest,
)
from strategy.backtest import OpenBreak3Strategy, metric, print_monthly, print_summary, print_yearly

# 加载插件注册表
import strategy.factors  # noqa: F401,E402
import strategy.strategies  # noqa: F401,E402

from strategy.registry import (  # noqa: E402
    REGISTRY,
    StrategyEntry,
    get_strategy,
    get_strategy_bindings,
    get_strategy_factors,
    list_strategies,
)
from strategy.registry import get_decision_engine  # noqa: E402
from strategy.core import (  # noqa: E402
    FACTOR_REGISTRY,
    STRATEGY_REGISTRY,
    Decision,
    MarketContext,
    FactorBinding,
    FactorSpec,
    StrategySpec,
    bind_factor,
    get_factor,
    list_factors,
    get_strategy_spec,
    list_strategy_specs,
)

# 语义别名：run_strategy1 = 因子1交易 + 因子2权益叠加；run_open_break = 仅因子1
Strategy1 = OpenBreak3Strategy
from strategy.strategies.strategy1 import run_strategy1  # noqa: E402
from strategy.strategies.strategy2 import run_strategy2  # noqa: E402
from strategy.strategies.strategy6 import run_strategy6  # noqa: E402
from strategy.strategies.strategy7 import run_strategy7  # noqa: E402
from strategy.strategies.strategy8 import run_strategy8  # noqa: E402

__all__ = [
    "DEFAULT_PCT",
    "ENTRY_PCT",
    "STOP_PCT",
    "TICK_SIZE",
    "PREV_SMALL_YANG_PCT",
    "LOT_SIZE",
    "NEAR_POINTS",
    "NEAR_FACTOR_PCT",
    "STRATEGY_RULES",
    "REASON_STOP",
    "BacktestConfig",
    "KAICHENG",
    "TIANTONG",
    "HANGTIANDIANZI",
    "XIEXINNENGKE",
    "ZZ500_ETF",
    "KCZZ_ETF",
    "ceil_to_tick",
    "floor_to_tick",
    "entry_trigger_price",
    "stop_trigger_price",
    "strategy_levels",
    "is_yin",
    "is_yang",
    "bar_shape",
    "prev_day_allows_entry",
    "has_double_yang_before",
    "is_t1_buy_day",
    "strategy_signal",
    "OpenBreak3Strategy",
    "Strategy1",
    "fetch_daily",
    "CommonBacktestParams",
    "run_akquant_backtest",
    "run_backtest_pipeline",
    "REGISTRY",
    "StrategyEntry",
    "get_strategy",
    "get_strategy_factors",
    "get_strategy_bindings",
    "get_decision_engine",
    "list_strategies",
    "FACTOR_REGISTRY",
    "STRATEGY_REGISTRY",
    "Decision",
    "MarketContext",
    "FactorBinding",
    "FactorSpec",
    "StrategySpec",
    "bind_factor",
    "get_factor",
    "list_factors",
    "get_strategy_spec",
    "list_strategy_specs",
    "fetch_minute_1m",
    "fetch_minute_5m",
    "fetch_minute_30m",
    "pull_akshare_1m",
    "standardize_minute_1m",
    "run_open_break",
    "run_open_break_backtest",
    "run_momentum",
    "run_strategy1",
    "run_strategy2",
    "run_strategy6",
    "run_strategy7",
    "run_strategy8",
    "apply_strategy_config",
    "build_open_break_strategy",
    "metric",
    "print_summary",
    "print_yearly",
    "print_monthly",
]
