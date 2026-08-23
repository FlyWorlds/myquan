"""因子10 价格选股：无未来函数与周频名单时点。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.s1_price_select import (
    compute_price_select,
    panel_price_factors,
    weekly_topk_allowed,
)


def _synth(n: int = 80, drift: float = 0.01, symbol: str = "A") -> pd.DataFrame:
    rng = np.random.default_rng(3)
    close = 10 * np.exp(np.cumsum(np.full(n, drift) + rng.normal(0, 0.01, n)))
    dates = pd.bdate_range("2020-01-02", periods=n, tz="Asia/Shanghai") + pd.Timedelta(
        hours=15
    )
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "symbol": symbol,
        }
    )


class PriceSelectTests(unittest.TestCase):
    def test_exec_is_shifted_raw(self) -> None:
        df = compute_price_select(_synth())
        raw = df["px_near_high"].to_numpy()
        exec_ = df["px_near_high_exec"].to_numpy()
        self.assertTrue(np.isnan(exec_[0]))
        np.testing.assert_allclose(exec_[1:], raw[:-1], equal_nan=True)

    def test_weekly_uses_previous_week(self) -> None:
        a = _synth(symbol="A", drift=0.02)
        b = _synth(symbol="B", drift=-0.01)
        panel = panel_price_factors({"A": a, "B": b})
        allowed = weekly_topk_allowed(panel, value_col="px_composite", k=1)
        days = sorted(allowed["A"])
        self.assertTrue(days)
        first = days[0]
        first_week = [
            d
            for d in days
            if pd.Timestamp(d) - pd.to_timedelta(pd.Timestamp(d).dayofweek, unit="D")
            == pd.Timestamp(first) - pd.to_timedelta(pd.Timestamp(first).dayofweek, unit="D")
        ]
        self.assertTrue(first_week)
        self.assertFalse(any(allowed["A"][d] or allowed["B"][d] for d in first_week))


if __name__ == "__main__":
    unittest.main()
