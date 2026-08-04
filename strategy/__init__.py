"""多策略模块化框架（当前内置 OpenBreak3）。

共用: data, minute, base, registry
OpenBreak3: open_break, backtest, config, runner
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
from strategy.config import KAICHENG, HANGTIANDIANZI, XIEXINNENGKE, ZZ500_ETF, BacktestConfig
from strategy.data import fetch_daily
from strategy.base import CommonBacktestParams, run_akquant_backtest, run_backtest_pipeline
from strategy.registry import REGISTRY, StrategyEntry, get_strategy, list_strategies
from strategy.minute import (
    fetch_minute_1m,
    fetch_minute_5m,
    fetch_minute_30m,
    pull_akshare_1m,
    standardize_minute_1m,
)
from strategy.runner import run_open_break, run_open_break_backtest
from strategy.backtest import OpenBreak3Strategy, metric, print_monthly, print_summary, print_yearly

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
    "HANGTIANDIANZI",
    "XIEXINNENGKE",
    "ZZ500_ETF",
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
    "fetch_daily",
    "CommonBacktestParams",
    "run_akquant_backtest",
    "run_backtest_pipeline",
    "REGISTRY",
    "StrategyEntry",
    "get_strategy",
    "list_strategies",
    "fetch_minute_1m",
    "fetch_minute_5m",
    "fetch_minute_30m",
    "pull_akshare_1m",
    "standardize_minute_1m",
    "run_open_break",
    "run_open_break_backtest",
    "metric",
    "print_summary",
    "print_yearly",
    "print_monthly",
]
