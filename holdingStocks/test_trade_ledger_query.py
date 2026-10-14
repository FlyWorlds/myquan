"""交割单按月筛选与总盈亏汇总。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import trade_ledger as tl  # noqa: E402


def _entries() -> list[dict]:
    return [
        {
            "id": "b1",
            "time": "2026-09-18 10:00:00",
            "session": "2026-09-18",
            "side": "buy",
            "code": "603115",
            "price": 70.0,
            "qty": 100,
            "amount": 7000,
            "pnl": None,
        },
        {
            "id": "s1",
            "time": "2026-09-20 14:00:00",
            "session": "2026-09-20",
            "side": "sell",
            "code": "603115",
            "price": 73.0,
            "qty": 100,
            "amount": 7300,
            "pnl": 300.0,
        },
        {
            "id": "b2",
            "time": "2026-10-08 09:35:00",
            "session": "2026-10-08",
            "side": "buy",
            "code": "600403",
            "price": 7.0,
            "qty": 1000,
            "amount": 7000,
            "pnl": None,
        },
        {
            "id": "s2",
            "time": "2026-10-08 13:10:00",
            "session": "2026-10-08",
            "side": "sell",
            "code": "600403",
            "price": 7.2,
            "qty": 500,
            "amount": 3600,
            "pnl": 100.0,
        },
    ]


class TestTradeLedgerQuery(unittest.TestCase):
    def test_adjust_record_is_not_persisted_as_trade(self) -> None:
        ledger = {"updated_at": "t", "entries": []}
        with (
            patch.object(tl, "load_ledger", return_value=ledger),
            patch.object(tl, "save_ledger") as save_ledger,
        ):
            entry = tl.record_trade_ledger(
                {
                    "time": "2026-10-14 11:26:04",
                    "side": "adjust",
                    "code": "002580",
                    "name": "圣阳股份",
                    "price": 19.06,
                    "qty": 3000,
                    "after_qty": 0,
                    "cost": 19.0,
                    "pnl": 180.0,
                    "note": "开盘保护纠价 19.12->19.06（原按抬高止损记账）",
                },
                holdings={"account_cash": 179841.0},
            )
        self.assertEqual(entry["side"], "adjust")
        self.assertEqual(ledger["entries"], [])
        save_ledger.assert_not_called()

    def test_backfill_ignores_adjust_records(self) -> None:
        lines = [
            {
                "time": "2026-10-14 09:32:00",
                "side": "sell",
                "code": "002580",
                "name": "圣阳股份",
                "price": 19.06,
                "qty": 3000,
                "after_qty": 0,
                "cost": 19.0,
                "pnl": 180.0,
            },
            {
                "time": "2026-10-14 11:26:04",
                "side": "adjust",
                "code": "002580",
                "name": "圣阳股份",
                "price": 19.06,
                "qty": 3000,
                "after_qty": 0,
                "cost": 19.0,
                "pnl": 180.0,
                "note": "开盘保护纠价 19.12->19.06（原按抬高止损记账）",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trades.jsonl"
            path.write_text(
                "\n".join(json.dumps(x, ensure_ascii=False) for x in lines),
                encoding="utf-8",
            )
            data = {"updated_at": None, "entries": []}
            with (
                patch.object(tl, "load_ledger", return_value=data),
                patch.object(tl, "save_ledger") as save_ledger,
            ):
                count = tl.backfill_from_trades_jsonl(path, force=True)
        self.assertEqual(count, 1)
        saved = save_ledger.call_args.args[0]
        self.assertEqual(len(saved["entries"]), 1)
        self.assertEqual(saved["entries"][0]["side"], "sell")
        self.assertEqual(saved["entries"][0]["price"], 19.06)

    def test_entry_month(self) -> None:
        self.assertEqual(tl.entry_month({"session": "2026-10-08"}), "2026-10")
        self.assertEqual(tl.entry_month({"time": "2026-09-18 10:00:00"}), "2026-09")
        self.assertEqual(tl.entry_month({}), "")

    def test_month_filter_and_total_pnl(self) -> None:
        ledger = {"updated_at": "t", "entries": _entries()}
        holdings = {
            "positions": {
                "600403": {"code": "600403", "qty": 500, "cost": 7.0},
            }
        }
        with patch.object(tl, "load_ledger", return_value=ledger):
            all_rows = tl.list_ledger_entries(
                holdings=holdings, marks={"600403": 7.4}, limit=50
            )
            oct_rows = tl.list_ledger_entries(
                month="2026-10",
                holdings=holdings,
                marks={"600403": 7.4},
                limit=50,
            )
        self.assertEqual(all_rows["months"], ["2026-10", "2026-09"])
        self.assertEqual(all_rows["summary"]["realized_pnl"], 400.0)
        self.assertEqual(all_rows["summary"]["unrealized_pnl"], 200.0)
        self.assertEqual(all_rows["summary"]["total_pnl"], 600.0)
        self.assertEqual(oct_rows["summary"]["count"], 2)
        self.assertEqual(oct_rows["summary"]["realized_pnl"], 100.0)
        self.assertEqual(oct_rows["summary"]["unrealized_pnl"], 200.0)
        self.assertEqual(oct_rows["summary"]["total_pnl"], 300.0)
        self.assertEqual(oct_rows["month"], "2026-10")

    def test_rows_sort_by_trade_time_not_append_order(self) -> None:
        ledger = {
            "updated_at": "t",
            "entries": [
                {"time": "2026-10-14 09:32:00", "side": "sell", "code": "002580"},
                {"time": "2026-10-14 09:31:00", "side": "sell", "code": "002636"},
                {"time": "2026-10-14 10:01:00", "side": "sell", "code": "002636"},
            ],
        }
        with patch.object(tl, "load_ledger", return_value=ledger):
            out = tl.list_ledger_entries(holdings={"positions": {}}, marks={}, limit=10)
        self.assertEqual(
            [f"{r['time']} {r['code']}" for r in out["entries"]],
            [
                "2026-10-14 10:01:00 002636",
                "2026-10-14 09:32:00 002580",
                "2026-10-14 09:31:00 002636",
            ],
        )


if __name__ == "__main__":
    unittest.main()
