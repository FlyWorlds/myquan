# -*- coding: utf-8 -*-
"""时间完整性验收：禁止未卜先知 / 价格反推时间 / 事后改写。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from temporal_integrity import (  # noqa: E402
    FUTURE_DATA_VIOLATION,
    LEGACY_HWM_AT,
    STALE_QUOTE_REJECTED,
    TemporalIntegrityError,
    assert_event_time_chain,
    assert_hwm_causal,
    assert_quote_usable,
    bar_usable_as_of,
    migrate_legacy_peak_high_at,
    stamp_peak_high_atomic,
)


class TestPeakHighAtGuard(unittest.TestCase):
    def test_hwm_at_must_not_exceed_decision(self) -> None:
        with self.assertRaises(TemporalIntegrityError) as ctx:
            assert_hwm_causal(
                peak_high_at="2026-09-24 10:00:00",
                decision_at="2026-09-24 09:30:00",
            )
        self.assertEqual(ctx.exception.code, FUTURE_DATA_VIOLATION)

    def test_atomic_stamp_requires_at(self) -> None:
        pos: dict = {"peak_high": 18.0}
        with self.assertRaises(TemporalIntegrityError):
            stamp_peak_high_atomic(pos, 18.5, at="")
        ok = stamp_peak_high_atomic(
            pos, 18.5, at="2026-09-24 10:32:15", decision_at="2026-09-24 10:32:15"
        )
        self.assertTrue(ok)
        self.assertAlmostEqual(float(pos["peak_high"]), 18.5)
        self.assertEqual(pos["peak_high_at"], "2026-09-24 10:32:15")

    def test_legacy_migrate_degraded(self) -> None:
        pos = {"peak_high": 18.88, "buy_time": "2026-09-23 14:00:00"}
        self.assertTrue(migrate_legacy_peak_high_at(pos))
        self.assertEqual(pos["peak_high_at"], "2026-09-23 14:00:00")
        self.assertTrue(pos.get("peak_high_at_degraded"))
        pos2 = {"peak_high": 18.88}
        self.assertTrue(migrate_legacy_peak_high_at(pos2))
        self.assertEqual(pos2["peak_high_at"], LEGACY_HWM_AT)


class TestFutureQuoteReject(unittest.TestCase):
    def test_future_quote_rejected(self) -> None:
        with self.assertRaises(TemporalIntegrityError) as ctx:
            assert_quote_usable(
                quote_at="2026-09-24 10:00:00",
                decision_at="2026-09-24 09:30:00",
            )
        self.assertEqual(ctx.exception.code, FUTURE_DATA_VIOLATION)

    def test_stale_ooo_quote_rejected(self) -> None:
        with self.assertRaises(TemporalIntegrityError) as ctx:
            assert_quote_usable(
                quote_at="2026-09-24 10:00:00",
                decision_at="2026-09-24 10:05:00",
                last_accepted_quote_at="2026-09-24 10:01:00",
            )
        self.assertEqual(ctx.exception.code, STALE_QUOTE_REJECTED)

    def test_future_quote_must_not_raise_hwm(self) -> None:
        pos = {"peak_high": 18.0, "peak_high_at": "2026-09-24 09:30:00"}
        with self.assertRaises(TemporalIntegrityError):
            stamp_peak_high_atomic(
                pos,
                18.88,
                at="2026-09-24 10:00:00",
                decision_at="2026-09-24 09:30:00",
            )
        self.assertAlmostEqual(float(pos["peak_high"]), 18.0)


class TestNoPriceInferredOpenBell(unittest.TestCase):
    def test_path_fill_equals_open_keeps_0958(self) -> None:
        from index import _open_protect_hit_ts

        ts = _open_protect_hit_ts(
            session="2026-09-24",
            fill_px=18.33,
            open_px=18.33,
            existing="2026-09-24 09:58:00",
            open_bell=False,
            exit_kind="path",
        )
        self.assertEqual(ts, "2026-09-24 09:58:00")

    def test_empty_existing_fill_eq_open_does_not_invent_0930(self) -> None:
        from index import _open_protect_hit_ts

        ts = _open_protect_hit_ts(
            session="2026-09-24",
            fill_px=18.33,
            open_px=18.33,
            existing=None,
            open_bell=False,
            exit_kind="path",
        )
        self.assertIsNone(ts)

    def test_true_open_protect_stamps_0930(self) -> None:
        from index import _open_protect_hit_ts

        ts = _open_protect_hit_ts(
            session="2026-09-24",
            fill_px=18.33,
            open_px=18.33,
            existing="2026-09-24 09:32:00",
            open_bell=True,
            exit_kind="open_protect",
        )
        self.assertEqual(ts, "2026-09-24 09:30:00")

    def test_keep_first_cannot_overwrite_0958_with_0930(self) -> None:
        from index import _keep_first_signal_ts

        st = {"stop_hit_ts": "2026-09-24 09:30:00"}
        _keep_first_signal_ts({"stop_hit_ts": "2026-09-24 09:58:00"}, st)
        self.assertEqual(st["stop_hit_ts"], "2026-09-24 09:58:00")

    def test_keep_first_allows_0932_to_0930(self) -> None:
        from index import _keep_first_signal_ts

        st = {"stop_hit_ts": "2026-09-24 09:30:00"}
        _keep_first_signal_ts({"stop_hit_ts": "2026-09-24 09:32:00"}, st)
        self.assertEqual(st["stop_hit_ts"], "2026-09-24 09:30:00")

    def test_heal_skips_path_even_if_fill_eq_open(self) -> None:
        from index import _open_protect_hit_ts

        # heal 入口：非 open_protect 不得把 PATH 纠成 09:30
        kept = _open_protect_hit_ts(
            session="2026-09-24",
            fill_px=18.33,
            open_px=18.33,
            existing="2026-09-24 09:58:00",
            open_bell=False,
            exit_kind="path",
        )
        self.assertEqual(kept, "2026-09-24 09:58:00")
        # heal 仅在 open_bell 时返回 bell
        bell = _open_protect_hit_ts(
            session="2026-09-24",
            fill_px=18.33,
            open_px=18.33,
            existing="2026-09-24 09:32:00",
            open_bell=True,
            exit_kind="open_protect",
        )
        self.assertEqual(bell, "2026-09-24 09:30:00")


class TestForming1mAndDaily(unittest.TestCase):
    def test_incomplete_bar_not_usable(self) -> None:
        self.assertFalse(
            bar_usable_as_of(
                bar_ts="2026-09-24 10:00:00",
                decision_at="2026-09-24 10:00:20",
                bar_complete=False,
            )
        )

    def test_forming_guard_in_resolver(self) -> None:
        from index import _bars_cover_current_minute
        import pandas as pd

        now = pd.Timestamp("2026-09-24 10:00:20")
        bars = pd.DataFrame(
            {"ts": [pd.Timestamp("2026-09-24 10:00:00")], "high": [18.88], "low": [18.5]}
        )
        self.assertTrue(_bars_cover_current_minute(bars, now=now))

    def test_open_auction_touch_ts_no_rewrite_late_bar(self) -> None:
        from strategy.pullback_wave_stop import open_auction_touch_ts

        later = "2026-09-24 09:58:00"
        out = open_auction_touch_ts(
            later, fill_px=18.33, day_open=18.33, first_bar=False
        )
        self.assertEqual(str(out), later)

    def test_vol20_excludes_session_day(self) -> None:
        """_vol20_daily_for 截止 session 前一日，不当日收盘泄漏。"""
        import inspect
        import index as idx

        src = inspect.getsource(idx._vol20_daily_for)
        self.assertIn("days=1", src)
        self.assertIn("end_excl", src)


class TestImmutableExit(unittest.TestCase):
    def test_event_chain_order(self) -> None:
        assert_event_time_chain(
            quote_at="2026-09-24 09:58:00",
            decision_at="2026-09-24 09:58:00",
            triggered_at="2026-09-24 09:58:00",
            filled_at="2026-09-24 09:58:00",
        )
        with self.assertRaises(TemporalIntegrityError):
            assert_event_time_chain(
                quote_at="2026-09-24 10:00:00",
                decision_at="2026-09-24 09:58:00",
            )


class TestTimeSteppingHWM(unittest.TestCase):
    """按事件时间逐步推进：HWM 只在创新高后抬升，回落不降。"""

    def test_causal_hwm_trail_sequence(self) -> None:
        from strategy.pullback_wave_stop import (
            raise_position_peak_high,
            working_stop_price,
        )

        pos: dict = {
            "peak_high": 18.30,
            "peak_high_at": "2026-09-24 09:30:00",
            "cost": 18.30,
        }
        ticks = [
            ("2026-09-24 09:30:00", 18.30, 18.30),
            ("2026-09-24 09:31:00", 18.40, 18.40),
            ("2026-09-24 09:35:00", 18.55, 18.55),
            ("2026-09-24 09:40:00", 18.70, 18.70),
            ("2026-09-24 10:00:00", 18.88, 18.88),
            ("2026-09-24 10:05:00", 18.80, 18.88),  # day high 保持，last 回落
            ("2026-09-24 10:10:00", 18.65, 18.88),
        ]
        rows = []
        for t, last, day_high in ticks:
            decision_at = t
            # 未来 day_high 不得提前进入：只用截至本 tick 的 day_high
            new_peak = raise_position_peak_high(
                persisted_peak=float(pos["peak_high"]),
                entry_price=18.30,
                quote_last=last,
                quote_day_high=day_high,
                allow_quote_day_high=True,
            )
            stamp_peak_high_atomic(
                pos, new_peak, at=t, decision_at=decision_at
            )
            assert_hwm_causal(
                peak_high_at=pos["peak_high_at"], decision_at=decision_at
            )
            kind, sell = working_stop_price(
                cost_px=18.30,
                peak_high=float(pos["peak_high"]),
                session_peak=float(pos["peak_high"]),
                overnight_armed=True,
            )
            should_sell = last <= float(sell) + 1e-9 and float(pos["peak_high"]) > last + 1e-6
            rows.append(
                {
                    "time": t,
                    "last": last,
                    "todayHigh": day_high,
                    "positionHWM": float(pos["peak_high"]),
                    "HWMAt": pos["peak_high_at"],
                    "sellTrigger": float(sell),
                    "decisionAt": decision_at,
                    "shouldSell": should_sell,
                }
            )
        # 创新高后 HWM 升
        self.assertAlmostEqual(rows[4]["positionHWM"], 18.88)
        self.assertEqual(rows[4]["HWMAt"], "2026-09-24 10:00:00")
        # 回落 HWM 不降
        self.assertAlmostEqual(rows[5]["positionHWM"], 18.88)
        self.assertAlmostEqual(rows[6]["positionHWM"], 18.88)
        self.assertEqual(rows[6]["HWMAt"], "2026-09-24 10:00:00")
        # 卖价随 HWM 升后保持
        self.assertGreaterEqual(rows[4]["sellTrigger"], rows[3]["sellTrigger"] - 1e-9)
        # 10:00 前不得出现 18.88 HWM
        for r in rows[:4]:
            self.assertLess(r["positionHWM"], 18.88 - 1e-9)


class TestSystemScanHints(unittest.TestCase):
    def test_no_fill_approx_open_in_open_protect_hit_ts(self) -> None:
        import inspect
        from index import _open_protect_hit_ts

        src = inspect.getsource(_open_protect_hit_ts)
        self.assertIn("禁止", src)
        self.assertNotIn("5e-3", src)

    def test_daily_pad_is_prev_close_not_today(self) -> None:
        import inspect
        import index as idx

        src = inspect.getsource(idx._vol20_daily_for)
        self.assertIn("end_excl", src)


if __name__ == "__main__":
    unittest.main()
