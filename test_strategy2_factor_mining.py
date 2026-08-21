"""策略二因子契约、相关性门禁与挖掘回滚。"""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.chan.config import ChanStrategyConfig
from strategy.chan.mining import cs_winsorize_zscore, mine_factors, primary_score


def _mining_panel(n_symbols: int = 36, n_dates: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2018-01-02 10:00", periods=n_dates, freq="B")
    rows = []
    for i in range(n_symbols):
        symbol = f"S{i:03d}"
        price = 10.0 + i * 0.1
        alpha = rng.normal(0, 1, size=n_dates)
        noise = rng.normal(0, 1, size=n_dates)
        for j, dt in enumerate(dates):
            ret = 0.002 * alpha[j] + 0.001 * noise[j]
            open_px = price
            close = price * (1.0 + ret)
            rows.append(
                {
                    "dt": dt,
                    "symbol": symbol,
                    "open": open_px,
                    "high": max(open_px, close),
                    "low": min(open_px, close),
                    "close": close,
                    "amount": 1_000_000 + i,
                    "buy1": j % 17 == i % 17,
                    "buy2": j % 17 == (i % 17) + 1,
                    "buy3": False,
                    "sell2": j % 29 == 0,
                    "sell3": False,
                    "good_factor": float(alpha[j]),
                    "clone_factor": float(alpha[j] * 1.01),
                    "noise_factor": float(noise[j]),
                }
            )
            price = close
    return pd.DataFrame(rows)


class FactorContractTests(unittest.TestCase):
    def test_primary_score_penalizes_drawdown(self) -> None:
        strong = primary_score(2.0, 1.5, 0.20, -0.10, 0.8, 8.0)
        fragile = primary_score(4.0, -1.0, -0.05, -0.60, 0.2, 40.0)
        self.assertGreater(strong, fragile)
        self.assertGreater(strong, 0.5)
        self.assertLess(fragile, 0.0)

    def test_cross_section_zscore_is_centered(self) -> None:
        panel = _mining_panel(n_symbols=36, n_dates=8)
        z = cs_winsorize_zscore(panel, "good_factor", min_cross_section=30)
        by_date = pd.DataFrame({"dt": panel["dt"], "z": z}).groupby("dt")["z"].mean()
        self.assertTrue((by_date.abs() < 1e-8).all())

    def test_mine_factors_rejects_clone_and_keeps_journal(self) -> None:
        panel = _mining_panel()
        config = replace(
            ChanStrategyConfig(),
            discovery_start="20180101",
            discovery_end="20180301",
            validation_start="20180301",
            validation_end="20180501",
            test_start="20180501",
            test_end="20180601",
            purge_days=0,
            min_cross_section=30,
            top_k=5,
        )
        result = mine_factors(
            panel,
            candidates=("good_factor", "clone_factor", "noise_factor", "missing"),
            config=config,
            max_factors=2,
        )
        self.assertIn("missing", set(result.journal["factor"]))
        self.assertTrue((result.journal["status"] == "CRASH").any())
        clone = result.journal[result.journal["factor"] == "clone_factor"]
        if not clone.empty and "good_factor" in result.accepted:
            self.assertIn(clone.iloc[0]["status"], {"REJECTED", "ACCEPTED"})
            if clone.iloc[0]["status"] == "REJECTED":
                self.assertEqual(clone.iloc[0]["reason"], "correlation_gate")
        self.assertGreaterEqual(len(result.journal), 4)
        self.assertFalse(bool(result.metadata["final_test_touched"]))


class FeatureAndBlendTests(unittest.TestCase):
    def test_xiaozhuan_confirm_uses_turn_environment(self) -> None:
        from strategy.chan.features import add_derived_features

        frame = pd.DataFrame(
            {
                "dt": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "symbol": ["AAA", "AAA"],
                "open": [10.0, 10.1],
                "high": [10.2, 10.3],
                "low": [9.8, 9.9],
                "close": [10.1, 10.2],
                "amount": [1e6, 1e6],
                "m30_buy2": [True, True],
                "daily_turn_env": [False, True],
                "daily_macd_bottom": [False, True],
                "buy1": [False, False],
                "buy2": [False, True],
                "buy3": [False, False],
                "sell2": [False, False],
                "sell3": [False, False],
            }
        )
        out = add_derived_features(frame)
        self.assertGreater(float(out.loc[1, "xiaozhuan_confirm"]), float(out.loc[0, "xiaozhuan_confirm"]))

    def test_blend_equal_weights_sum_to_one(self) -> None:
        from strategy.chan.blend import _scheme_weights

        journal = pd.DataFrame(
            [
                {
                    "factor": "a",
                    "status": "ACCEPTED",
                    "discovery_rank_ic_ir": 2.0,
                    "discovery_score": 1.0,
                },
                {
                    "factor": "b",
                    "status": "ACCEPTED",
                    "discovery_rank_ic_ir": 1.0,
                    "discovery_score": 0.5,
                },
            ]
        )
        equal = _scheme_weights(["a", "b"], journal, "equal")
        self.assertAlmostEqual(sum(equal.values()), 1.0)
        icir = _scheme_weights(["a", "b"], journal, "icir")
        self.assertGreater(icir["a"], icir["b"])


class ResearchReportTests(unittest.TestCase):
    def test_synthetic_report_states_pipeline_only(self) -> None:
        from tempfile import TemporaryDirectory

        from strategy.chan.reporting import write_research_report

        journal = pd.DataFrame(
            [
                {
                    "factor": "baseline_equal_weight",
                    "status": "BASELINE",
                    "reason": "reference",
                    "validation_sharpe": 0.1,
                    "validation_score": 0.0,
                    "max_abs_correlation": 0.0,
                }
            ]
        )
        with TemporaryDirectory() as tmp:
            path = write_research_report(
                Path(tmp),
                journal=journal,
                accepted=[],
                diagnostics={
                    "search_trials": 1,
                    "test_stats": {
                        "annual_return": -0.1,
                        "sharpe": -0.5,
                        "max_drawdown": -0.2,
                        "annual_turnover": 10,
                    },
                    "bootstrap": {"sharpe_p05": -1.0, "sharpe_p95": 0.1},
                    "deflated_sharpe_probability": 0.0,
                    "pbo_estimate": 0.5,
                    "decision": "reject",
                    "limitations": ["历史回测不代表未来表现"],
                },
                data_label="CZSC可复现合成数据（测试）",
                point_in_time_universe=False,
            )
            text = path.read_text(encoding="utf-8")
        self.assertIn("只验证流水线", text)
        self.assertIn("不能当成 A 股缠论选股绩效", text)
        self.assertIn("历史回测不代表未来表现", text)


if __name__ == "__main__":
    unittest.main()
