from __future__ import annotations

import builtins
import importlib
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


@contextmanager
def import_backtest_without_scipy():
    sys.modules.pop("backtest", None)
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise ImportError("scipy blocked by offline test")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = blocked_import
    try:
        yield importlib.import_module("backtest")
    finally:
        builtins.__import__ = original_import
        sys.modules.pop("backtest", None)


class BacktestOfflineTests(unittest.TestCase):
    def sample_factor_and_returns(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        factor = pd.DataFrame(
            [
                ["2026-01-02", "A", 0.9, "buy"],
                ["2026-01-02", "B", 0.3, "hold"],
                ["2026-01-02", "C", -0.2, "hold"],
                ["2026-01-02", "D", -0.8, "sell"],
                ["2026-01-03", "A", 0.7, "buy"],
                ["2026-01-03", "B", 0.1, "hold"],
                ["2026-01-03", "C", -0.4, "hold"],
                ["2026-01-03", "D", -0.6, "sell"],
            ],
            columns=["trade_date", "symbol", "factor_value", "signal"],
        )
        returns = pd.DataFrame(
            [
                ["2026-01-02", "A", "A2601", 0.030],
                ["2026-01-02", "B", "B2601", 0.010],
                ["2026-01-02", "C", "C2601", -0.005],
                ["2026-01-02", "D", "D2601", -0.020],
                ["2026-01-03", "A", "A2601", 0.015],
                ["2026-01-03", "B", "B2601", -0.010],
                ["2026-01-03", "C", "C2601", 0.000],
                ["2026-01-03", "D", "D2601", -0.015],
            ],
            columns=["trade_date", "symbol", "contract_symbol", "forward_return"],
        )
        return factor, returns

    def sample_dominant_and_daily(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        dominant = pd.DataFrame(
            [
                ["20260102", "A", "A2601"],
                ["20260103", "A", "A2601"],
                ["20260104", "A", "A2602"],
                ["20260102", "B", "B2601"],
                ["20260103", "B", "B2601"],
                ["20260104", "B", "B2602"],
                ["20260102", "C", "C2601"],
                ["20260103", "C", "C2601"],
                ["20260104", "C", "C2602"],
                ["20260102", "D", "D2601"],
                ["20260103", "D", "D2601"],
                ["20260104", "D", "D2602"],
            ],
            columns=["date", "underlying_symbol", "symbol"],
        )
        daily = pd.DataFrame(
            [
                ["20260102", "A2601", 100.0],
                ["20260103", "A2601", 103.0],
                ["20260104", "A2602", 105.0],
                ["20260102", "B2601", 100.0],
                ["20260103", "B2601", 101.0],
                ["20260104", "B2602", 102.0],
                ["20260102", "C2601", 100.0],
                ["20260103", "C2601", 99.5],
                ["20260104", "C2602", 100.0],
                ["20260102", "D2601", 100.0],
                ["20260103", "D2601", 98.0],
                ["20260104", "D2602", 97.0],
            ],
            columns=["date", "symbol", "close"],
        )
        return dominant, daily

    def test_backtest_import_does_not_require_scipy(self) -> None:
        with import_backtest_without_scipy() as backtest:
            self.assertTrue(hasattr(backtest, "evaluate_factor"))

    def test_bootstrap_ic_confidence_interval_is_deterministic(self) -> None:
        with import_backtest_without_scipy() as backtest:
            factor, returns = self.sample_factor_and_returns()
            first = backtest.bootstrap_ic_confidence_interval(
                factor,
                returns,
                n_bootstrap=200,
                random_state=7,
            )
            second = backtest.bootstrap_ic_confidence_interval(
                factor,
                returns,
                n_bootstrap=200,
                random_state=7,
            )

        self.assertEqual(first, second)
        self.assertEqual(first["bootstrap_samples"], 200)
        self.assertLessEqual(first["IC_95_CI_low"], first["IC"])
        self.assertGreaterEqual(first["IC_95_CI_high"], first["IC"])

    def test_backtest_results_include_tradeable_metrics(self) -> None:
        with import_backtest_without_scipy() as backtest:
            factor, _returns = self.sample_factor_and_returns()
            dominant, daily = self.sample_dominant_and_daily()
            result = backtest.compute_backtest_results(
                factor,
                dominant,
                daily,
                data_lag=0,
                roll_cost_bps=5.0,
                bootstrap_samples=100,
                bootstrap_seed=11,
            )

        self.assertIn("research", result)
        self.assertIn("tradeable", result)
        self.assertIn("bootstrap_ic", result)
        self.assertIn("holding_period_ic", result)
        for section in ("research", "tradeable"):
            self.assertIn("ARR(%)", result[section])
            self.assertIn("IR", result[section])
            self.assertIn("IC", result[section])
        self.assertEqual(result["bootstrap_ic"]["bootstrap_samples"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
