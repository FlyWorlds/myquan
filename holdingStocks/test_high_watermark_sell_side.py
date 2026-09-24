# -*- coding: utf-8 -*-
"""持仓 highWaterMark / trailing sell — 通用回归（无个股 hardcode）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.pullback_wave_stop import (  # noqa: E402
    cost_hard_stop_px,
    raise_position_peak_high,
    stop_note_invalidated_by_recovery,
    t1_trail_stop_px,
    working_stop_price,
)


class TestRaisePositionPeakHigh(unittest.TestCase):
    """TEST 1–8 的 HWM 原子语义。"""

    def test_1_intraday_new_highs(self) -> None:
        h = raise_position_peak_high(persisted_peak=18.0, entry_price=18.0, quote_last=18.2)
        self.assertAlmostEqual(h, 18.2)
        h = raise_position_peak_high(persisted_peak=h, quote_last=18.5)
        self.assertAlmostEqual(h, 18.5)
        h = raise_position_peak_high(persisted_peak=h, quote_last=18.88)
        self.assertAlmostEqual(h, 18.88)
        _, s1 = working_stop_price(
            cost_px=18.0, peak_high=18.5, session_peak=18.5, overnight_armed=True
        )
        _, s2 = working_stop_price(
            cost_px=18.0, peak_high=18.88, session_peak=18.88, overnight_armed=True
        )
        self.assertGreater(s2, s1)

    def test_2_pullback_does_not_lower_hwm(self) -> None:
        cost = 18.34
        hwm = 18.88
        h = raise_position_peak_high(
            persisted_peak=hwm, quote_last=18.60, quote_day_high=18.60
        )
        self.assertAlmostEqual(h, 18.88)
        kind, px = working_stop_price(
            cost_px=cost, peak_high=h, session_peak=h, overnight_armed=True
        )
        self.assertEqual(kind, "t1_peak_trail")
        self.assertAlmostEqual(px, t1_trail_stop_px(18.88, cost_px=cost), places=2)

    def test_3_cross_day_open_cannot_reset(self) -> None:
        cost = 18.34
        h = raise_position_peak_high(
            persisted_peak=18.88,
            quote_last=18.40,
            quote_day_high=18.50,
            allow_quote_day_high=True,
        )
        self.assertAlmostEqual(h, 18.88)
        kind, px = working_stop_price(
            cost_px=cost,
            peak_high=h,
            session_peak=h,
            day_open=18.20,
            overnight_armed=True,
        )
        self.assertEqual(kind, "t1_peak_trail")
        self.assertAlmostEqual(px, t1_trail_stop_px(18.88, cost_px=cost), places=2)
        self.assertGreater(px, t1_trail_stop_px(18.20, cost_px=cost))

    def test_4_today_new_high_via_day_high(self) -> None:
        cost = 18.34
        old_sell = t1_trail_stop_px(18.88, cost_px=cost)
        h = raise_position_peak_high(
            persisted_peak=18.88,
            quote_last=19.05,
            quote_day_high=19.20,
            allow_quote_day_high=True,
        )
        self.assertAlmostEqual(h, 19.20)
        kind, px = working_stop_price(
            cost_px=cost, peak_high=h, session_peak=h, overnight_armed=True
        )
        # 峰值浮盈已过 3% → 中段；卖价仍须相对旧 trail 抬升或以 HWM 为锚
        self.assertGreater(px, old_sell - 1e-9)
        self.assertGreater(h, 18.88)

    def test_5_missed_tick_recovered_by_day_high(self) -> None:
        """漏掉最高 tick：current=18.60 但 dayHigh=18.88 → HWM 仍应到 18.88。"""
        h = raise_position_peak_high(
            persisted_peak=18.50,
            quote_last=18.60,
            quote_day_high=18.88,
            allow_quote_day_high=True,
        )
        self.assertAlmostEqual(h, 18.88)

    def test_5b_same_day_buy_must_not_use_pre_entry_day_high(self) -> None:
        """买入当日：即使 API dayHigh=20，也不得在 allow=False 时并入。"""
        h = raise_position_peak_high(
            persisted_peak=18.0,
            entry_price=18.0,
            quote_last=18.50,
            quote_day_high=20.0,
            allow_quote_day_high=False,
        )
        self.assertAlmostEqual(h, 18.50)

    def test_6_intraday_entry_ignores_pre_buy_day_high(self) -> None:
        h = raise_position_peak_high(
            persisted_peak=18.0,
            entry_price=18.0,
            quote_last=18.50,
            quote_day_high=20.0,
            path_running_high=18.50,
            allow_quote_day_high=False,
        )
        self.assertAlmostEqual(h, 18.50)
        self.assertNotAlmostEqual(h, 20.0)

    def test_7_new_position_does_not_inherit(self) -> None:
        old = 20.0
        fresh = raise_position_peak_high(
            persisted_peak=18.0,  # 新仓以成本重置
            entry_price=18.0,
            quote_last=18.0,
            quote_day_high=old,
            allow_quote_day_high=False,
        )
        self.assertAlmostEqual(fresh, 18.0)

    def test_8_restart_preserves_persisted(self) -> None:
        h = raise_position_peak_high(
            persisted_peak=18.88,
            quote_last=18.40,
            quote_day_high=18.40,
            allow_quote_day_high=True,
        )
        self.assertAlmostEqual(h, 18.88)


class TestTrailingArmedGeneric(unittest.TestCase):
    def test_t1_sentinel_not_voided_by_small_profit(self) -> None:
        cost = 10.0
        self.assertFalse(
            stop_note_invalidated_by_recovery(
                last_px=10.2,
                noted_px=cost,
                prev_close=10.1,
                cost_px=cost,
                reason="t1_trail",
            )
        )
        hard = cost_hard_stop_px(cost)
        self.assertTrue(
            stop_note_invalidated_by_recovery(
                last_px=10.2,
                noted_px=hard,
                prev_close=10.1,
                cost_px=cost,
                reason="hard_from_cost",
            )
        )

    def test_unarmed_below_3pct_hard(self) -> None:
        cost = 18.34
        peak = 18.88  # ~2.94%
        kind, px = working_stop_price(
            cost_px=cost, peak_high=peak, overnight_armed=False
        )
        self.assertEqual(kind, "hard_from_cost")
        self.assertAlmostEqual(px, cost_hard_stop_px(cost), places=2)

    def test_armed_tracks_peak(self) -> None:
        cost = 18.34
        kind, px = working_stop_price(
            cost_px=cost, peak_high=18.88, session_peak=18.88, overnight_armed=True
        )
        self.assertEqual(kind, "t1_peak_trail")
        self.assertAlmostEqual(px, 18.40, places=2)


class TestHealGeneric(unittest.TestCase):
    def test_heal_arms_any_overnight_symbol(self) -> None:
        from index import heal_missing_overnight_t1_trail_notes

        data = {
            "positions": {
                "688001": {
                    "qty": 100,
                    "cost": 50.0,
                    "buy_time": "2026-09-23 09:31:00",
                    "peak_high": 51.0,
                    "stop_noted": False,
                }
            }
        }
        n = heal_missing_overnight_t1_trail_notes(data, session="2026-09-24")
        self.assertEqual(n, 1)
        self.assertTrue(data["positions"]["688001"]["stop_noted"])
        self.assertAlmostEqual(float(data["positions"]["688001"]["stop_noted_px"]), 50.0)

    def test_heal_skips_buy_day(self) -> None:
        from index import heal_missing_overnight_t1_trail_notes

        data = {
            "positions": {
                "688001": {
                    "qty": 100,
                    "cost": 10.0,
                    "buy_time": "2026-09-24 09:31:00",
                    "peak_high": 10.1,
                }
            }
        }
        self.assertEqual(
            heal_missing_overnight_t1_trail_notes(data, session="2026-09-24"), 0
        )

    def test_t1_trail_persist_allowed_small_profit(self) -> None:
        from index import t1_stop_note_allowed

        self.assertTrue(
            t1_stop_note_allowed(
                reason="t1_trail",
                stop_px=18.34,
                cost_px=18.34,
                last_px=18.45,
                prev_close=18.56,
            )
        )

    def test_no_symbol_hardcode_in_peak_helpers(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "strategy" / "pullback_wave_stop.py"
        text = src.read_text(encoding="utf-8")
        # 函数定义附近不得绑死凯盛代码
        idx = text.find("def raise_position_peak_high")
        chunk = text[idx : idx + 800]
        self.assertNotIn("600552", chunk)
        self.assertNotIn("凯盛", chunk)


class TestHwmUiFieldsSoT(unittest.TestCase):
    """UI 持仓最高必须来自 peak_high，不得用 dayHigh 冒充。"""

    def test_attach_prefers_position_peak_not_day_high(self) -> None:
        from index import _attach_hwm_row_fields, _stamp_position_peak_high

        pos = {"peak_high": 19.2, "peak_high_at": "2026-09-24 10:32:15"}
        row = {"最高": 18.88, "今日最高": 18.88}
        _attach_hwm_row_fields(row, pos, px_digits=2)
        self.assertAlmostEqual(float(row["持仓最高"]), 19.2)
        self.assertAlmostEqual(float(row["峰值"]), 19.2)
        self.assertAlmostEqual(float(row["今日最高"]), 18.88)
        self.assertEqual(row["持仓最高时间"], "10:32:15")
        # 抬升只升不降
        self.assertFalse(_stamp_position_peak_high(pos, 19.0))
        self.assertTrue(_stamp_position_peak_high(pos, 19.5, at="2026-09-24 11:00:00"))
        self.assertAlmostEqual(float(pos["peak_high"]), 19.5)
        self.assertEqual(pos["peak_high_at"], "2026-09-24 11:00:00")

    def test_day_high_alias_independent(self) -> None:
        from index import _attach_hwm_row_fields

        row = {"最高": 18.5}
        _attach_hwm_row_fields(row, {"peak_high": 19.0}, px_digits=2)
        self.assertAlmostEqual(float(row["今日最高"]), 18.5)
        self.assertAlmostEqual(float(row["持仓最高"]), 19.0)
        self.assertNotEqual(row["今日最高"], row["持仓最高"])


if __name__ == "__main__":
    unittest.main()
