import unittest

import numpy as np
import pandas as pd

from strategy.industry_residual_momentum import (
    composite_scores,
    improved_residual_momentum,
    monthly_topk_targets,
    ordinary_momentum,
    rolling_residual_returns,
    simulate_monthly_topk,
)


class IndustryResidualMomentumFactorTests(unittest.TestCase):
    def test_ordinary_and_loudest_month_reversal_formulas(self) -> None:
        periods = pd.period_range("2023-01", periods=12, freq="M")
        monthly = pd.DataFrame({"A": np.arange(1, 13) / 100.0}, index=periods)
        ordinary = ordinary_momentum(monthly, lookback=12)
        self.assertAlmostEqual(float(ordinary.iloc[-1, 0]), 0.78)

        residual = pd.DataFrame({"A": np.arange(1, 13, dtype=float)}, index=periods)
        volatility = pd.DataFrame({"A": np.ones(12)}, index=periods)
        volatility.iloc[4, 0] = 10.0
        improved = improved_residual_momentum(residual, volatility, lookback=12)
        self.assertAlmostEqual(float(improved.iloc[-1, 0]), 78.0 - 2.0 * 5.0)

    def test_composite_uses_cross_sectional_percentiles(self) -> None:
        index = pd.period_range("2024-01", periods=1, freq="M")
        ordinary = pd.DataFrame({"A": [3.0], "B": [2.0], "C": [1.0]}, index=index)
        residual = pd.DataFrame({"A": [1.0], "B": [2.0], "C": [3.0]}, index=index)
        score = composite_scores(ordinary, residual)
        self.assertAlmostEqual(float(score.loc[index[0], "A"]), 2.0 / 3.0)
        self.assertAlmostEqual(float(score.loc[index[0], "B"]), 2.0 / 3.0)
        self.assertAlmostEqual(float(score.loc[index[0], "C"]), 2.0 / 3.0)

    def test_rolling_residual_has_no_future_dependency(self) -> None:
        rng = np.random.default_rng(7)
        periods = pd.period_range("2015-01", periods=80, freq="M")
        common = pd.DataFrame(
            rng.normal(0.005, 0.03, size=(80, 5)),
            index=periods,
            columns=list("VWXYZ"),
        )
        industry = pd.DataFrame(
            {
                "A": 0.6 * common["V"] - 0.2 * common["W"] + rng.normal(0, 0.01, 80),
                "B": -0.1 * common["X"] + 0.5 * common["Y"] + rng.normal(0, 0.01, 80),
            },
            index=periods,
        )
        base = rolling_residual_returns(
            industry, common, pca_window=36, n_components=3
        )
        changed = common.copy()
        changed.iloc[-1] += 10.0
        perturbed = rolling_residual_returns(
            industry, changed, pca_window=36, n_components=3
        )
        pd.testing.assert_series_equal(
            base.iloc[-2], perturbed.iloc[-2], check_names=False
        )

    def test_monthly_targets_and_execution_do_not_trade_early(self) -> None:
        score = pd.DataFrame(
            {"A": [0.9], "B": [0.8], "C": [0.7], "D": [0.1]},
            index=pd.period_range("2024-01", periods=1, freq="M"),
        )
        targets = monthly_topk_targets(score, top_k=3)
        dates = pd.bdate_range("2024-01-02", "2024-02-05")
        opens = pd.DataFrame(10.0, index=dates, columns=list("ABCD"))
        closes = opens.copy()
        equity, trades, _ = simulate_monthly_topk(
            opens=opens,
            closes=closes,
            targets=targets,
            bt_start=pd.Timestamp("2024-01-15"),
            initial_cash=100_000,
        )
        self.assertFalse(equity.empty)
        self.assertTrue((trades["date"] >= pd.Timestamp("2024-02-01")).all())
        self.assertEqual(set(trades.loc[trades["side"] == "buy", "symbol"]), {"A", "B", "C"})


class Factor7RegistrationTests(unittest.TestCase):
    def test_factor7_is_registered(self) -> None:
        from strategy import get_factor, list_strategies

        factor = get_factor("factor7")
        self.assertEqual(factor.meta["kind"], "industry_etf_dual_momentum")
        self.assertNotIn("strategy8", {s.id for s in list_strategies()})


if __name__ == "__main__":
    unittest.main()

