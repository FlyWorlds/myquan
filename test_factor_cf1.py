"""CF1 流动性门控反转：单测。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.cf1_liquidity_gated_reversal import compute_cf1


class FactorCF1Tests(unittest.TestCase):
    def test_registered(self) -> None:
        from strategy import get_factor

        f = get_factor("cf1")
        self.assertEqual(f.id, "cf1")
        self.assertIn("流动性", f.name)

    def _panel(self, n_days: int = 80, n_sym: int = 40) -> tuple[pd.DataFrame, pd.DataFrame]:
        idx = pd.bdate_range("2020-01-02", periods=n_days)
        rng = np.random.default_rng(7)
        close = pd.DataFrame(index=idx)
        volume = pd.DataFrame(index=idx)
        for i in range(n_sym):
            ret = rng.normal(0.0, 0.02, n_days)
            if i == 0:
                ret[-6:] = -0.08
            if i == 1:
                ret[-6:] = 0.08
            px = 10.0 * np.exp(np.cumsum(ret))
            close[f"s{i}"] = px
            volume[f"s{i}"] = 1_000_000.0
        volume["s0"] = 50_000.0
        volume["s1"] = 50_000.0
        volume["s2"] = 20_000_000.0
        return close, volume

    def test_loser_ranks_above_winner(self) -> None:
        close, volume = self._panel()
        fac = compute_cf1(close, volume, params={"min_names": 10, "adv_floor": 0.0, "limit_gate": False})
        row = fac.iloc[-1]
        self.assertGreater(float(row["s0"]), float(row["s1"]))

    def test_illiquid_gate_lifts_same_reversal(self) -> None:
        idx = pd.bdate_range("2020-01-02", periods=60)
        n = 36
        close = pd.DataFrame(index=idx)
        volume = pd.DataFrame(index=idx)
        for i in range(n):
            close[f"s{i}"] = 10.0
            volume[f"s{i}"] = 1_000_000.0
        path = np.linspace(10.0, 8.0, len(idx))
        close["illiq"] = path
        close["liq"] = path
        volume["illiq"] = 20_000.0
        volume["liq"] = 8_000_000.0
        ungated = compute_cf1(
            close,
            volume,
            params={
                "gate_mode": "none",
                "adv_floor": 0.0,
                "min_names": 10,
                "vol_scale": False,
            },
        )
        gated = compute_cf1(
            close,
            volume,
            params={
                "gate_mode": "soft_illiquid",
                "gate_lo": 0.3,
                "adv_floor": 0.0,
                "min_names": 10,
                "vol_scale": False,
            },
        )
        self.assertAlmostEqual(float(ungated.iloc[-1]["illiq"]), float(ungated.iloc[-1]["liq"]), places=4)
        self.assertGreater(float(gated.iloc[-1]["illiq"]), float(gated.iloc[-1]["liq"]))

    def test_adv_floor_drops_tiny_volume(self) -> None:
        close, volume = self._panel()
        volume["s0"] = 1.0
        fac = compute_cf1(close, volume, params={"adv_floor": 0.2, "min_names": 10, "limit_gate": False})
        self.assertTrue(np.isnan(fac.iloc[-1]["s0"]))

    def test_limit_gate_drops_limit_down(self) -> None:
        idx = pd.bdate_range("2020-01-02", periods=50)
        close = pd.DataFrame({f"s{i}": 10.0 for i in range(12)}, index=idx)
        volume = close * 0 + 1_000_000.0
        close.iloc[-1, close.columns.get_loc("s0")] = 8.95  # ~−10.5%
        high = close * 1.001
        low = close * 0.999
        low.iloc[-1, low.columns.get_loc("s0")] = 8.95
        high.iloc[-1, high.columns.get_loc("s0")] = 8.95
        off = compute_cf1(
            close, volume, high=high, low=low,
            params={
                "limit_gate": False,
                "adv_floor": 0.0,
                "min_names": 8,
                "gate_mode": "none",
                "vol_scale": False,
            },
        )
        on = compute_cf1(
            close, volume, high=high, low=low,
            params={
                "limit_gate": True,
                "adv_floor": 0.0,
                "min_names": 8,
                "gate_mode": "none",
                "vol_scale": False,
            },
        )
        self.assertTrue(np.isfinite(off.iloc[-1]["s0"]))
        self.assertTrue(np.isnan(on.iloc[-1]["s0"]))

    def test_trend_below_ma_drops_above(self) -> None:
        idx = pd.bdate_range("2020-01-02", periods=80)
        t = np.arange(len(idx), dtype=float)
        close = pd.DataFrame(index=idx)
        volume = pd.DataFrame(index=idx)
        for i in range(16):
            close[f"s{i}"] = 12.0 - 0.02 * t
            volume[f"s{i}"] = 1_000_000.0
        close["up"] = 8.0 + 0.05 * t
        close["down"] = 16.0 - 0.05 * t
        volume["up"] = 1_000_000.0
        volume["down"] = 1_000_000.0
        fac = compute_cf1(
            close,
            volume,
            params={
                "limit_gate": False,
                "trend_gate": "below_ma",
                "trend_n": 20,
                "adv_floor": 0.0,
                "min_names": 8,
                "gate_mode": "none",
                "vol_scale": False,
            },
        )
        self.assertTrue(np.isnan(fac.iloc[-1]["up"]))
        self.assertTrue(np.isfinite(fac.iloc[-1]["down"]))

    def test_no_lookahead(self) -> None:
        close, volume = self._panel()
        full = compute_cf1(close, volume, params={"min_names": 10, "limit_gate": False})
        trunc = compute_cf1(
            close.iloc[:-5], volume.iloc[:-5], params={"min_names": 10, "limit_gate": False}
        )
        a = full.iloc[-6].dropna()
        b = trunc.iloc[-1].reindex(a.index)
        diff = (a - b).abs().max()
        self.assertLess(float(diff), 1e-9)


if __name__ == "__main__":
    unittest.main()
