"""交割单仍持仓 BUY：单笔盈亏按现价 mark-to-market（读模型，不写 ledger）。"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import trade_ledger as tl  # noqa: E402


def _holdings(positions: dict) -> dict:
    return {
        "account_cash": 100000.0,
        "positions": positions,
    }


class TestTradeOpenMark(unittest.TestCase):
    def test_open_buy_pnl_formula(self) -> None:
        pnl, pct = tl.open_buy_unrealized_pnl(
            mark=3.66, buy_cost=3.81, remaining_qty=19300
        )
        self.assertEqual(pnl, -2895.0)
        self.assertAlmostEqual(pct, -3.94, places=2)

    def test_open_buy_mark_on_enrich(self) -> None:
        entries = [
            {
                "id": "b1",
                "time": "2026-09-18 10:00:00",
                "side": "buy",
                "code": "000055",
                "name": "方大集团",
                "price": 3.81,
                "qty": 19300,
                "after_qty": 19300,
                "amount": 3.81 * 19300,
                "cost": None,
                "pnl": None,
                "pnl_pct": None,
            }
        ]
        holdings = _holdings(
            {
                "000055": {
                    "code": "000055",
                    "qty": 19300,
                    "cost": 3.81,
                }
            }
        )
        out = tl.enrich_open_buy_marks(
            entries, holdings=holdings, marks={"000055": 3.66}
        )
        self.assertEqual(out[0]["pnl"], -2895.0)
        self.assertAlmostEqual(out[0]["pnl_pct"], -3.94, places=2)
        self.assertEqual(out[0]["pnl_kind"], "unrealized")
        self.assertEqual(out[0]["remaining_qty"], 19300)
        self.assertEqual(out[0]["mark_price"], 3.66)

    def test_current_price_update_changes_open_buy(self) -> None:
        entries = [
            {
                "id": "b1",
                "time": "2026-09-18 10:00:00",
                "side": "buy",
                "code": "000055",
                "price": 3.81,
                "qty": 19300,
                "after_qty": 19300,
            }
        ]
        holdings = _holdings({"000055": {"qty": 19300, "cost": 3.81}})
        a = tl.enrich_open_buy_marks(
            copy.deepcopy(entries), holdings=holdings, marks={"000055": 3.66}
        )
        b = tl.enrich_open_buy_marks(
            copy.deepcopy(entries), holdings=holdings, marks={"000055": 3.70}
        )
        self.assertEqual(a[0]["pnl"], -2895.0)
        self.assertEqual(b[0]["pnl"], round((3.70 - 3.81) * 19300, 2))
        self.assertNotEqual(a[0]["pnl"], b[0]["pnl"])

    def test_closed_sell_frozen_when_mark_changes(self) -> None:
        entries = [
            {
                "id": "s1",
                "time": "2026-09-18 14:00:00",
                "side": "sell",
                "code": "603115",
                "price": 95.0,
                "qty": 800,
                "after_qty": 0,
                "cost": 91.8,
                "pnl": 2560.0,
                "pnl_pct": 3.49,
            }
        ]
        holdings = _holdings({})
        a = tl.enrich_open_buy_marks(
            copy.deepcopy(entries), holdings=holdings, marks={"603115": 90.0}
        )
        b = tl.enrich_open_buy_marks(
            copy.deepcopy(entries), holdings=holdings, marks={"603115": 100.0}
        )
        self.assertEqual(a[0]["pnl"], 2560.0)
        self.assertEqual(b[0]["pnl"], 2560.0)
        self.assertEqual(a[0]["pnl_pct"], 3.49)
        self.assertNotIn("pnl_kind", a[0])  # SELL 不改写

    def test_partial_sell_open_uses_remaining_qty(self) -> None:
        entries = [
            {
                "id": "b1",
                "time": "2026-09-18 09:40:00",
                "side": "buy",
                "code": "000001",
                "price": 10.0,
                "qty": 1000,
                "after_qty": 1000,
            },
            {
                "id": "s1",
                "time": "2026-09-18 11:00:00",
                "side": "sell",
                "code": "000001",
                "price": 12.0,
                "qty": 400,
                "after_qty": 600,
                "cost": 10.0,
                "pnl": 800.0,
                "pnl_pct": 20.0,
            },
        ]
        holdings = _holdings({"000001": {"qty": 600, "cost": 10.0}})
        out = tl.enrich_open_buy_marks(
            entries, holdings=holdings, marks={"000001": 11.0}
        )
        sell = next(e for e in out if e["side"] == "sell")
        buy = next(e for e in out if e["side"] == "buy")
        self.assertEqual(sell["pnl"], 800.0)
        self.assertEqual(buy["remaining_qty"], 600)
        self.assertEqual(buy["pnl"], 600.0)  # (11-10)*600
        self.assertNotEqual(buy["pnl"], 1000.0)  # 不得按原 1000 股

    def test_full_close_no_dynamic_mark_on_buy(self) -> None:
        entries = [
            {
                "id": "b1",
                "time": "2026-09-18 09:40:00",
                "side": "buy",
                "code": "000002",
                "price": 10.0,
                "qty": 1000,
                "after_qty": 1000,
            },
            {
                "id": "s1",
                "time": "2026-09-18 14:00:00",
                "side": "sell",
                "code": "000002",
                "price": 12.0,
                "qty": 1000,
                "after_qty": 0,
                "cost": 10.0,
                "pnl": 2000.0,
                "pnl_pct": 20.0,
            },
        ]
        holdings = _holdings({})  # 已平仓
        out = tl.enrich_open_buy_marks(
            entries, holdings=holdings, marks={"000002": 15.0}
        )
        buy = next(e for e in out if e["side"] == "buy")
        sell = next(e for e in out if e["side"] == "sell")
        self.assertIsNone(buy.get("pnl"))
        self.assertNotEqual(buy.get("pnl_kind"), "unrealized")
        self.assertEqual(sell["pnl"], 2000.0)

    def test_cross_day_cumulative_vs_today_baseline(self) -> None:
        """单笔累计用 buy_cost；今日盈亏用昨收 —— 二者不得混用。"""
        cost = 10.0
        prev_close = 11.0
        current = 12.0
        qty = 100
        cum_pnl, _ = tl.open_buy_unrealized_pnl(
            mark=current, buy_cost=cost, remaining_qty=qty
        )
        today_pnl = round((current - prev_close) * qty, 2)
        self.assertEqual(cum_pnl, 200.0)  # (12-10)*100
        self.assertEqual(today_pnl, 100.0)  # (12-11)*100
        self.assertNotEqual(cum_pnl, today_pnl)

    def test_enrich_does_not_write_ledger_or_holdings(self) -> None:
        entries = [
            {
                "id": "b1",
                "time": "2026-09-18 10:00:00",
                "side": "buy",
                "code": "000055",
                "price": 3.81,
                "qty": 19300,
                "after_qty": 19300,
            }
        ]
        holdings = _holdings({"000055": {"qty": 19300, "cost": 3.81}})
        with (
            patch.object(tl, "save_ledger") as save_l,
            patch.object(tl, "record_trade_ledger") as rec,
        ):
            tl.enrich_open_buy_marks(
                entries, holdings=holdings, marks={"000055": 3.66}
            )
            save_l.assert_not_called()
            rec.assert_not_called()

    def test_lot_matching_flag(self) -> None:
        self.assertIs(tl.TRADE_LOT_MATCHING_AVAILABLE, False)

    def test_list_ledger_entries_injects_marks(self) -> None:
        fake = {
            "updated_at": "2026-09-18 10:00:00",
            "entries": [
                {
                    "id": "b1",
                    "time": "2026-09-18 10:00:00",
                    "side": "buy",
                    "code": "000021",
                    "name": "深科技",
                    "price": 36.98,
                    "qty": 1900,
                    "after_qty": 1900,
                    "amount": 36.98 * 1900,
                }
            ],
        }
        holdings = _holdings({"000021": {"qty": 1900, "cost": 36.98}})
        with patch.object(tl, "load_ledger", return_value=fake):
            payload = tl.list_ledger_entries(
                holdings=holdings, marks={"000021": 37.50}, limit=50
            )
        row = payload["entries"][0]
        self.assertEqual(row["pnl_kind"], "unrealized")
        self.assertEqual(
            row["pnl"], round((37.50 - 36.98) * 1900, 2)
        )
        self.assertIs(payload["lot_matching"], False)


if __name__ == "__main__":
    unittest.main()
