"""多策略 + 多因子可插拔框架。

架构（开闭原则）：
  · factors/factor1..7              — 因子层：信号/价位规则
  · strategies/strategyN/
      bindings.py + decision.py     — 策略层(绑定) + 决策层(买卖)
  · core/                           — 协议 / MarketContext / Decision / 注册表
  · backtest.py / runner.py         — 执行层（下单与回测）

默认生效：援军战法（strategy1）= 因子1（开盘±2.5% 一次打满）+ 因子2（回撤预警）。
因子 1–12 均保留。现行策略：1 / 2 / 3 / 4 / 5 / 6。旧号 strategy7/9/10 仍是别名。
策略三：因子5事件开仓、单主题一只、固定持有五日。
策略五：因子11 两段近高（3日动量→5日近高 Top5）等权持有（研究，非默认）。
策略六：因子12 反转池近高（研究候选，2024–2025 未确认）。
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
    apply_s1_recommended,
)
from strategy.costs import (
    COMMISSION_RATE,
    COST_ROUND_TRIP,
    ENGINE_COMMISSION_RATE,
    MISC_FEE_RATE,
    SLIPPAGE_VALUE,
    STAMP_TAX_RATE,
    fee_rules_text,
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
from strategy.strategies.strategy3 import run_strategy3, run_strategy7  # noqa: E402
from strategy.strategies.strategy4 import run_strategy4, run_strategy9  # noqa: E402
from strategy.strategies.strategy5 import run_strategy5, run_strategy10  # noqa: E402
from strategy.strategies.strategy6 import run_strategy6  # noqa: E402
from strategy.f3_f1_combo import (  # noqa: E402
    combo_rules_text,
    run_f3_f1_combo,
)

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
    "apply_s1_recommended",
    "COMMISSION_RATE",
    "MISC_FEE_RATE",
    "STAMP_TAX_RATE",
    "SLIPPAGE_VALUE",
    "ENGINE_COMMISSION_RATE",
    "COST_ROUND_TRIP",
    "fee_rules_text",
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
    "run_strategy3",
    "run_strategy4",
    "run_strategy5",
    "run_strategy6",
    "run_strategy7",
    "run_strategy9",
    "run_strategy10",
    "run_f3_f1_combo",
    "combo_rules_text",
    "apply_strategy_config",
    "build_open_break_strategy",
    "metric",
    "print_summary",
    "print_yearly",
    "print_monthly",
]
