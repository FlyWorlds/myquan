"""盯盘 10% 半仓：只减半、落 tp_stage、当日可再卖剩余。"""

from __future__ import annotations

import unittest


class TestWatchHalfTp(unittest.TestCase):
    def setUp(self) -> None:
        import index as idx

        self.idx = idx
        self.data: dict = {
            "updated_at": None,
            "account_total": 300000.0,
            "account_cash": 200000.0,
            "positions": {
                "600000": {
                    "name": "测试",
                    "market": "上证",
                    "qty": 400,
                    "available": 400,
                    "cost": 10.0,
                    "buy_time": "2026-09-11 09:35:00",
                    "today_cost": None,
                    "tp_stage": 0,
                    "last_tp_ts": None,
                    "note": "",
                    "peak_high": 10.0,
                }
            },
            "realized_today": {},
            "closed_today": {},
        }
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        self._remember = idx.remember_factor_trigger
        idx.load_holdings = lambda: self.data
        idx.save_holdings = self._save_holdings
        idx.append_trade = lambda *_a, **_k: None
        idx.remember_factor_trigger = lambda *_a, **_k: None

    def _save_holdings(self, data: dict) -> None:
        self.data = data

    def tearDown(self) -> None:
        self.idx.load_holdings = self._load
        self.idx.save_holdings = self._save
        self.idx.append_trade = self._append
        self.idx.remember_factor_trigger = self._remember

    def test_ten_pct_stop_fills_half_not_full(self) -> None:
        rec = self.idx.apply_stop_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            stop_px=11.0,
            qty=400,
            cost=10.0,
            session="2026-09-12",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            action_kind="half",
            stop_kind="ladder_half_10",
            first_hit_ts="2026-09-12 10:15:00",
        )
        pos = self.data["positions"]["600000"]
        self.assertEqual(int(rec.get("qty") or 0), 200)
        self.assertEqual(int(rec.get("after_qty") or 0), 200)
        self.assertFalse(bool(rec.get("full_exit")))
        self.assertEqual(rec.get("reason"), self.idx.REASON_HALF)
        self.assertEqual(int(pos.get("qty") or 0), 200)
        self.assertEqual(int(pos.get("tp_stage") or 0), 1)
        self.assertEqual(str(pos.get("last_tp_ts") or ""), "2026-09-12 10:15:00")
        self.assertIsNotNone(pos.get("cost"))

    def test_second_sell_after_half_not_short_circuited(self) -> None:
        self.idx.apply_stop_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            stop_px=11.0,
            qty=400,
            cost=10.0,
            session="2026-09-12",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            action_kind="half",
            stop_kind="ladder_half_10",
            first_hit_ts="2026-09-12 10:15:00",
        )
        rec2 = self.idx.apply_stop_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            stop_px=11.5,
            qty=200,
            cost=10.0,
            session="2026-09-12",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            action_kind="full",
            stop_kind="peak_pullback_clear",
            first_hit_ts="2026-09-12 13:20:00",
        )
        pos = self.data["positions"]["600000"]
        self.assertEqual(int(rec2.get("qty") or 0), 200)
        self.assertEqual(int(pos.get("qty") or 0), 0)
        self.assertTrue(bool(rec2.get("full_exit")))
        self.assertEqual(int(pos.get("tp_stage") or 0), 0)

    def test_legacy_full_exit_still_idempotent(self) -> None:
        self.data["realized_today"]["600000"] = {
            "session": "2026-09-12",
            "reason": self.idx.REASON_STOP,
            "qty": 400,
            "price": 9.7,
        }
        rec = self.idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=9.7,
            qty=400,
            cost=10.0,
            session="2026-09-12",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            reason=self.idx.REASON_STOP,
            trade_note="dup",
        )
        self.assertEqual(int(rec.get("qty") or 0), 400)
        self.assertEqual(int(self.data["positions"]["600000"].get("qty") or 0), 400)


if __name__ == "__main__":
    unittest.main()
