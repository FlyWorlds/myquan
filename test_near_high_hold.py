"""因子11 / 策略五：两段近高与周频时点。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.core.context import MarketContext
from strategy.near_high_hold import (
    daily_from_snaps_fill,
    equal_weight_hold_nav,
    factor11_signal,
    limit_fill_masks,
    picks_on,
    run_near_high_hold,
    weekly_near_high_gate,
)
from strategy.strategies.strategy5.decision import create_decision_engine


def _panel(n: int = 40, n_names: int = 25) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = pd.bdate_range("2020-01-06", periods=n)
    close = pd.DataFrame(index=idx)
    high = pd.DataFrame(index=idx)
    t = np.arange(n, dtype=float)
    for i in range(n_names):
        name = f"s{i:02d}"
        base = 10.0 + 0.01 * i + 0.002 * t
        close[name] = base
        high[name] = base * 1.02
    # HOT_NEAR: 20日涨得多，且收盘=高点
    close["hot_near"] = 8.0 + 0.15 * t
    high["hot_near"] = close["hot_near"]
    # HOT_FAR: 20日涨得更多，但最近从高点回落
    close["hot_far"] = 8.0 + 0.22 * t
    high["hot_far"] = close["hot_far"] * 1.35
    close.loc[idx[-5:], "hot_far"] = close.loc[idx[-5:], "hot_far"] * 0.72
    return close, high


class NearHighHoldTests(unittest.TestCase):
    def test_default_is_mom3_high5_k5(self) -> None:
        from strategy.near_high_hold import DEFAULT_PARAMS, ORIGINAL_PARAMS

        self.assertEqual(DEFAULT_PARAMS["mom_n"], 3)
        self.assertEqual(DEFAULT_PARAMS["high_n"], 5)
        self.assertEqual(DEFAULT_PARAMS["stage2_k"], 5)
        self.assertEqual(ORIGINAL_PARAMS["mom_n"], 20)
        self.assertEqual(ORIGINAL_PARAMS["high_n"], 20)

    def test_registered(self) -> None:
        from strategy import get_factor, get_strategy

        f = get_factor("factor11")
        self.assertEqual(f.id, "factor11")
        s = get_strategy("strategy5")
        self.assertEqual(s.id, "strategy5")
        self.assertEqual(get_strategy("strategy10").id, "strategy5")
        self.assertEqual(s.factor_ids, ("factor11",))

    def test_first_week_not_selected(self) -> None:
        close, high = _panel()
        gate = weekly_near_high_gate(close, high)
        first_week = close.index[:5]
        for d in first_week:
            picks = picks_on(gate, str(d.date()))
            self.assertEqual(picks, [])

    def test_hot_near_beats_hot_far_in_stage2(self) -> None:
        close, high = _panel()
        gate = weekly_near_high_gate(close, high)
        later = str(close.index[-1].date())
        picks = picks_on(gate, later)
        self.assertIn("hot_near", picks)
        self.assertNotIn("hot_far", picks)
        self.assertLessEqual(len(picks), 5)

    def test_signal_date(self) -> None:
        close, high = _panel()
        later = str(close.index[-1].date())
        sig = factor11_signal(close, high, date=later)
        self.assertEqual(sig["factor_id"], "factor11")
        self.assertEqual(sig["picks"], sig["target"])
        self.assertTrue(sig["picks"])

    def test_equal_weight_nav(self) -> None:
        close, high = _panel()
        gate = weekly_near_high_gate(close, high)
        nav = equal_weight_hold_nav(close, gate)[0]
        self.assertGreater(len(nav), 10)
        self.assertTrue(np.isfinite(float(nav.iloc[-1])))
        res = run_near_high_hold(
            close=close, high=high, start="2020-01-06", end="2020-03-01", verbose=False
        )
        self.assertIn("ret_pct", res.stats)

    def test_one_word_limit_up_skips_new_buy(self) -> None:
        idx = pd.bdate_range("2020-01-06", periods=8)
        close = pd.DataFrame(
            {"keep": [10.0] * 8, "hot": [10.0, 10.0, 10.0, 10.0, 10.0, 11.0, 12.1, 12.2]},
            index=idx,
        )
        open_px = close.copy()
        open_px.loc[idx[6], "hot"] = 12.1
        high = close.copy()
        low = close.copy()
        gate = {
            "keep": {str(d.date()): i < 6 for i, d in enumerate(idx)},
            "hot": {str(d.date()): i >= 6 for i, d in enumerate(idx)},
        }
        nav, st = equal_weight_hold_nav(
            close,
            gate,
            open_px=open_px,
            high=high,
            low=low,
            block_limit_up_buy=True,
            block_limit_down_sell=False,
        )
        self.assertGreater(st["skipped_limit_up_buy"], 0)
        self.assertTrue(np.isfinite(float(nav.iloc[-1])))

    def test_decision_blocks_limit_up_open(self) -> None:
        eng = create_decision_engine()
        blocked = eng.decide(
            MarketContext(
                open=11.0,
                high=11.0,
                low=11.0,
                close=11.0,
                prev_close=10.0,
                meta={"symbol": "a", "target": ["a"]},
            )
        )
        self.assertEqual(blocked.action, "hold")
        self.assertIn("一字涨停", blocked.reason)

    def test_fill_masks_match_cannot_buy(self) -> None:
        from strategy.open_break import cannot_buy_limit_up, limit_down_state

        idx = pd.bdate_range("2020-01-06", periods=4)
        close = pd.DataFrame({"a": [10.0, 10.0, 11.0, 11.0]}, index=idx)
        open_px = pd.DataFrame({"a": [10.0, 10.0, 11.0, 11.0]}, index=idx)
        high = close.copy()
        low = close.copy()
        bb, bs, _ = limit_fill_masks(close, open_px, high, low)
        ts = idx[2]
        self.assertEqual(
            bool(bb.at[ts, "a"]),
            cannot_buy_limit_up(
                prev_close=10.0,
                open_px=11.0,
                high_px=11.0,
                low_px=11.0,
                close_px=11.0,
                limit_up_pct=0.10,
            ),
        )
        self.assertEqual(
            bool(bs.at[ts, "a"]),
            bool(
                limit_down_state(
                    prev_close=10.0,
                    open_px=11.0,
                    high_px=11.0,
                    low_px=11.0,
                    close_px=11.0,
                    limit_down_pct=0.10,
                )["locked"]
            ),
        )

    def test_snaps_fill_skips_limit_up(self) -> None:
        idx = pd.bdate_range("2020-01-06", periods=8)
        close = pd.DataFrame(
            {"keep": [10.0] * 8, "hot": [10.0, 10.0, 10.0, 10.0, 10.0, 11.0, 12.1, 12.2]},
            index=idx,
        )
        open_px = close.copy()
        open_px.loc[idx[6], "hot"] = 12.1
        high = close.copy()
        low = close.copy()
        w0 = idx[0] - pd.to_timedelta(int(idx[0].dayofweek), unit="D")
        snap = {w0: {"hot"}}
        bb, bs, _ = limit_fill_masks(close, open_px, high, low)
        _, st = daily_from_snaps_fill(close, snap, bb, bs)
        self.assertGreater(st["skipped_limit_up_buy"], 0)

    def test_decision_rotate(self) -> None:
        eng = create_decision_engine()
        buy = eng.decide(
            MarketContext(open=10, high=10, low=10, close=10, meta={"symbol": "a", "target": ["a"]})
        )
        self.assertEqual(buy.action, "buy")
        sell = eng.decide(
            MarketContext(
                open=10,
                high=10,
                low=10,
                close=10,
                position_qty=100,
                available_qty=100,
                meta={"symbol": "a", "target": ["b"], "t_plus_one": False},
            )
        )
        self.assertEqual(sell.action, "sell")


if __name__ == "__main__":
    unittest.main()
