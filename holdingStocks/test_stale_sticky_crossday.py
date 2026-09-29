"""跨日粘滞回归：昨日 buy_touched/buy_hit_ts 不得被今日写入继承（2026-09-29 金安国纪 002636）。

事故：9:15 清空前加载的扫描写卖出防抖时继承昨日已触买并把 session 改成今日 →
09:30 腾槽后按「第一梯队」现价买入，buy_time 记成昨日 09:46 → 绕过 T+1 当场止损。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import index as idx  # noqa: E402

TODAY = "2026-09-29"
YDAY = "2026-09-28"


def _stale_sticky() -> dict:
    return {
        "002636": {
            "session": YDAY,
            "buy_touched": True,
            "buy_hit_ts": f"{YDAY} 09:46:00",
            "stop_touched": True,
            "touch_stop": 80.0,
            "stop_hit_ts": f"{YDAY} 14:00:00",
        }
    }


class TestStickyCrossDay(unittest.TestCase):
    def test_sticky_put_does_not_inherit_yesterday(self) -> None:
        sticky = _stale_sticky()
        idx._sticky_put(sticky, "002636", TODAY, {"bg_class": "warn-sell", "alert": "已触止损"})
        st = sticky["002636"]
        self.assertEqual(st["session"], TODAY)
        self.assertNotIn("buy_touched", st)
        self.assertNotIn("buy_hit_ts", st)
        self.assertNotIn("stop_touched", st)
        self.assertNotIn("touch_stop", st)

    def test_stamp_stop_touched_fresh_session(self) -> None:
        sticky = _stale_sticky()
        idx._stamp_stop_touched(
            sticky, "002636", session=TODAY, ts=f"{TODAY} 09:30:15", touch_stop=77.31
        )
        st = sticky["002636"]
        self.assertEqual(st["session"], TODAY)
        self.assertTrue(st["stop_touched"])
        self.assertTrue(st["stop_hit_ts"].startswith(TODAY))
        self.assertNotIn("buy_touched", st)
        self.assertNotIn("buy_hit_ts", st)

    def test_stamp_buy_touched_uses_today_ts(self) -> None:
        sticky = _stale_sticky()
        idx._stamp_buy_touched(sticky, "002636", session=TODAY, ts=f"{TODAY} 10:01:00")
        st = sticky["002636"]
        self.assertTrue(st["buy_touched"])
        self.assertEqual(st["buy_hit_ts"], f"{TODAY} 10:01:00")

    def test_same_session_still_keeps_flags(self) -> None:
        sticky = {"600552": {"session": TODAY, "buy_touched": True, "buy_hit_ts": f"{TODAY} 09:41:07"}}
        idx._sticky_put(sticky, "600552", TODAY, {"bg_class": "warn-sell"})
        self.assertTrue(sticky["600552"]["buy_touched"])
        self.assertEqual(sticky["600552"]["buy_hit_ts"], f"{TODAY} 09:41:07")

    def test_restore_session_buy_hit_ignores_rewritten_stale(self) -> None:
        sticky = _stale_sticky()
        idx._stamp_stop_touched(sticky, "002636", session=TODAY, ts=f"{TODAY} 09:15:06")
        self.assertFalse(
            idx._restore_session_buy_hit(False, qty=0, sticky_row=sticky["002636"], session=TODAY)
        )


class TestSlotBuyStaleTrigger(unittest.TestCase):
    def setUp(self) -> None:
        self.book = {
            "account_cash": 300000.0,
            "account_total": 300000.0,
            "positions": {},
            "closed_today": {},
        }
        self._load, self._save, self._append = idx.load_holdings, idx.save_holdings, idx.append_trade
        idx.load_holdings = lambda: self.book
        idx.save_holdings = lambda d: None
        idx.append_trade = lambda *_a, **_k: None

    def tearDown(self) -> None:
        idx.load_holdings, idx.save_holdings, idx.append_trade = self._load, self._save, self._append

    def test_rejects_buy_time_from_other_session(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            idx.apply_paper_slot_buy(
                code="002636",
                meta={"name": "金安国纪", "market": "深证"},
                price=77.32,
                qty=700,
                buy_time=f"{YDAY} 09:46:00",
                session=TODAY,
            )
        self.assertIn("STALE_BUY_TRIGGER", str(ctx.exception))
        self.assertEqual(self.book["account_cash"], 300000.0)
        self.assertNotIn("002636", self.book["positions"])

    def test_accepts_same_session_buy_time(self) -> None:
        pos = idx.apply_paper_slot_buy(
            code="002636",
            meta={"name": "金安国纪", "market": "深证"},
            price=77.32,
            qty=700,
            buy_time=f"{TODAY} 09:46:00",
            session=TODAY,
        )
        self.assertEqual(int(pos["qty"]), 700)
        self.assertTrue(str(pos["buy_time"]).startswith(TODAY))


if __name__ == "__main__":
    unittest.main()
