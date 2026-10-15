# -*- coding: utf-8 -*-
"""盯盘 / 因子26 / 时间完整性 / BT-1m Contract / Cross-resolution 默认回归。

改 trailing、HWM、成交时刻、paper exit、eval_multi_tp_bar 优先级后必须跑通。
不包含会动真实 holdings 的集成测试。
"""

from __future__ import annotations

import sys
import os
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
os.environ["HOLDINGS_STORAGE"] = "local_json"  # Isolate legacy fixtures from the production database.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Gate 1: Realtime temporal + HWM
# Gate 2–3: Factor26 priority / cross-resolution（strategy/）
REGRESSION_MODULES = (
    "test_temporal_integrity",
    "test_high_watermark_sell_side",
    "test_watch_boot_perf",
    "test_watch_process",
    "test_boot_holdings",
    "tests.test_project_launcher",
    "test_trading_calendar",
    "test_health_status",
    "test_signal_latency",
    "test_condition_buy",
    "test_condition_order_report",
    "test_quote_exit",
    "test_database_strategy_books",
    "test_database_quotes",
    "test_data_read_boundaries",
    "test_quote_feed_health",
    "test_minute_backup",
    "test_holdings_reset_http",
    "test_runtime_integrity",
    "test_comprehensive_trade_return",
    "test_watch_remote_ledger",
    "test_sectors_watch_fast",
    "tests.test_market_data_sources",
    "tests.test_sina_boards",
    "test_stale_sticky_crossday",
    "test_holdings_store",
    "test_database_holdings",
    "test_account_history",
    "test_account_reconciliation",
    "test_strategy_simulator_lifecycle",
    "test_gap_rebuy",
    "test_strategy_cumulative_regression",
    "strategy.test_factor26_exit_priority",
    "strategy.test_factor26_characterization",
    "strategy.test_factor29",
    "strategy.test_cross_resolution_harness",
    "strategy.test_full_exit_orchestration",
)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in REGRESSION_MODULES:
        suite.addTests(loader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
