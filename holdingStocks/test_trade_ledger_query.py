"""交割单按月筛选与总盈亏汇总。"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
