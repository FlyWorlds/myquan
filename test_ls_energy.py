"""因子9 日线多空动能：无未来函数与方向性冒烟测试。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.ls_energy import compute_ls_energy, ls_energy_rules_text


def _synth(n: int = 120, drift: float = 0.01) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 10 * np.exp(np.cumsum(np.full(n, drift) + rng.normal(0, 0.01, n)))
    high = close * 1.01
    low = close * 0.99
    open_ = close
    dates = pd.bdate_range("2020-01-02", periods=n, tz="Asia/Shanghai") + pd.Timedelta(hours=15)
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "symbol": "TEST",
        }
    )


class LsEnergyTests(unittest.TestCase):
    def test_exec_is_shifted_raw(self) -> None:
        df = compute_ls_energy(_synth())
        raw = df["ls_net"].to_numpy()
        exec_ = df["ls_net_exec"].to_numpy()
        self.assertTrue(np.isnan(exec_[0]))
        np.testing.assert_allclose(exec_[1:], raw[:-1], equal_nan=True)

    def test_uptrend_net_energy_positive_late(self) -> None:
        up = compute_ls_energy(_synth(drift=0.02))
        down = compute_ls_energy(_synth(drift=-0.02))
        self.assertGreater(float(up["ls_net"].iloc[-20:].mean()), float(down["ls_net"].iloc[-20:].mean()))

    def test_rules_mention_timing(self) -> None:
        text = ls_energy_rules_text()
        self.assertIn("T+1", text)
        self.assertIn("追涨杀跌", text)


if __name__ == "__main__":
    unittest.main()
