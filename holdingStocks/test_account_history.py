from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from account_history import build_sample


class AccountHistoryTests(unittest.TestCase):
    def sample(self):
        return {"clock":"2026-10-14 15:36:00","account":{"accountTotal":1000,"availableCash":900,"totalPnl":0,"dayPnl":None},
                "holdings":[{"代码":"002841","持仓":10,"现价":10,"成本":10},
                            {"代码":"002580","持仓":0,"已实现":True,"浮盈":20}]}

    def test_records_actual_returns_and_preserves_missing_day_return(self):
        frame=self.sample()
        sample=build_sample(frame,session="2026-10-14",revision=1)
        self.assertEqual(sample["account"]["totalPnl"],0)
        self.assertIsNone(sample["account"]["dayPnl"])
        self.assertEqual(len(sample["holdings"]),1)
        self.assertEqual(len(sample["closed"]),1)
        frame["account"]["totalPnl"]=99
        self.assertEqual(sample["account"]["totalPnl"],0)

    def test_partial_valuation_never_becomes_zero_return(self):
        frame=self.sample()
        frame["account"]["totalPnl"]=None
        self.assertIsNone(build_sample(frame,session="2026-10-14",revision=1))
        frame=self.sample()
        frame["holdings"][0]["现价"]=0
        self.assertIsNone(build_sample(frame,session="2026-10-14",revision=1))

    def test_boot_and_nonfinite_values_are_not_recorded(self):
        frame=self.sample()
        frame["boot"]=True
        self.assertIsNone(build_sample(frame,session="2026-10-14",revision=1))

    def test_database_equity_never_replaces_real_cash_with_day_pnl(self):
        from watch_snapshot import apply_day_linked_account_equity
        account=apply_day_linked_account_equity({"equityBasis":"cash_plus_market_value",
                "availableCash":179535,"marketValue":112644,"accountOpen":286497,
                "paperEquityBase":300000,"dayPnl":-4395})
        self.assertEqual(account["availableCash"],179535)
        self.assertEqual(account["accountTotal"],292179)
        self.assertEqual(account["totalPnl"],-7821)
        self.assertEqual(account["dayPnl"],-4395)
        self.assertEqual(account["equityDayPnl"],5682)
        self.assertEqual(account["dayPnlVsEquity"],-10077)

    def test_quick_day_return_uses_all_fills_not_only_last_closed_row(self):
        from watch_snapshot import _database_day_pnl
        rows=[{"持仓":100,"当日盈亏":-20},{"持仓":0,"已实现":True,"当日盈亏":5}]
        self.assertEqual(_database_day_pnl({"settledDayPnl":15,"settledCount":2},rows),-5)
        rows[0]["当日盈亏"]=None
        self.assertIsNone(_database_day_pnl({"settledDayPnl":15,"settledCount":2},rows))
        frame=self.sample()
        frame["account"]["accountTotal"]=float("nan")
        self.assertIsNone(build_sample(frame,session="2026-10-14",revision=1))


if __name__=="__main__":unittest.main()
