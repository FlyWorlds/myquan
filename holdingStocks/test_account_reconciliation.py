from __future__ import annotations

import copy
import unittest

from account_reconciliation import account_summary, effective_deliveries, cycle_return, enrich_snapshot_trade_metadata


class ReconciliationTests(unittest.TestCase):
    def test_snapshot_daily_quota_counts_buys_even_after_sales_and_uses_current_sell_signal(self):
        state = self.state()
        state['trades'] = [dict(code='001282', side='buy', session='2026-10-22'),
            dict(code='002866', side='buy', session='2026-10-22'),
            dict(code='001282', side='sell', session='2026-10-22'),
            dict(code='000070', side='buy', session='2026-10-21')]
        state['holdings']['realized_today'] = {'600330': dict(session='2026-10-22', signal_time='2026-10-22 09:30:10')}
        snap = dict(paperRevision=7, clock='2026-10-22 09:40:00', slotMeta=dict(maxNewSymbolsPerSession=2),
            holdings=[{'代码':'600330', '持仓':0, '已实现':True, '信号时间':'2026-10-21 10:18:27'}])
        original = copy.deepcopy(state)
        enrich_snapshot_trade_metadata(snap, state)
        self.assertEqual(snap['slotMeta']['buysToday'], 2)
        self.assertEqual(snap['slotMeta']['buysLeft'], 0)
        self.assertEqual(snap['holdings'][0]['信号时间'], '2026-10-22 09:30:10')
        self.assertEqual(state, original)
        snap['paperRevision'] = 6
        snap['slotMeta']['buysToday'] = 99
        enrich_snapshot_trade_metadata(snap, state)
        self.assertEqual(snap['slotMeta']['buysToday'], 99)

    def state(self):
        return dict(revision=7, holdings=dict(account_cash=800, paper_equity_base=1000,
                    account_total_open=1000, account_total_open_session="2026-10-14",
                    positions={"002636":dict(qty=20, cost=10, buy_time="2026-10-13 09:32:00")}),
                    ledger=dict(entries=[dict(id="a", side="sell", code="002636", price=12, cost=10,
                    qty=10, after_qty=20, pnl=20, day_pnl=10, session="2026-10-14", time="2026-10-14 10:00:00")]),
                    trades=[])

    def rows(self):
        return [{"代码":"002636", "持仓":20, "成本":10, "现价":12, "昨收":11,
                 "当日盈亏":999}]

    def test_open_partial_sale_is_counted_once_and_not_filtered_by_closed_rows(self):
        summary=account_summary(self.state(), self.rows(), "2026-10-14")
        self.assertEqual(summary["dayPnl"], 30)
        self.assertEqual(summary["accountTotal"], 1040)
        self.assertEqual(summary["settledCount"], 1)

    def test_legacy_adjustment_changes_read_model_not_cash_or_fill_timestamp(self):
        state=self.state()
        state["trades"]=[dict(side="adjust", code="002636", qty=10, price=11,
                pnl=10, time="2026-10-14 15:11:33", adjustment_kind="open_protect_reprice",
                note="开盘保护纠价 12->11")]
        original=copy.deepcopy(state)
        entries, issues=effective_deliveries(state)
        self.assertFalse(issues)
        self.assertEqual(entries[0]["pnl"],10)
        self.assertEqual(entries[0]["day_pnl"],0)
        self.assertEqual(entries[0]["time"],"2026-10-14 10:00:00")
        self.assertEqual(account_summary(state,self.rows(),"2026-10-14")["dayPnl"],20)
        self.assertEqual(state,original)
        self.assertEqual(effective_deliveries(state)[0],entries)

    def test_ambiguous_correction_never_selects_arbitrary_sale(self):
        state=self.state()
        state["ledger"]["entries"].append(dict(state["ledger"]["entries"][0],id="b"))
        state["trades"]=[dict(side="adjust",code="002636",qty=10,price=11,
                time="2026-10-14 15:11:33",adjustment_kind="open_protect_reprice",note="纠价 12->11")]
        entries,issues=effective_deliveries(state)
        self.assertEqual(entries[0]["price"],12)
        self.assertEqual(issues[0]["kind"],"ambiguous_adjustment")
        self.assertIsNone(account_summary(state,self.rows(),"2026-10-14")["dayPnl"])

    def test_missing_quote_or_cost_conflict_cannot_publish_partial_equity(self):
        self.assertIsNone(account_summary(self.state(),[],"2026-10-14")["accountTotal"])
        rows=self.rows()
        rows[0]["成本"]=9
        self.assertIsNone(account_summary(self.state(),rows,"2026-10-14")["accountTotal"])

    def test_missing_sell_daily_pnl_remains_unknown(self):
        state=self.state()
        state["ledger"]["entries"][0]["day_pnl"]=None
        self.assertIsNone(account_summary(state,self.rows(),"2026-10-14")["dayPnl"])

    def test_stale_opening_session_uses_complete_committed_valuation(self):
        state = self.state()
        state["holdings"]["account_total_open_session"] = "2026-10-13"
        summary = account_summary(state, self.rows(), "2026-10-14")
        self.assertEqual(summary["accountOpen"], 1010)
        self.assertEqual(summary["dayPnlPct"], 2.97)
        state["ledger"]["entries"][0]["day_pnl"] = None
        summary = account_summary(state, self.rows(), "2026-10-14")
        self.assertIsNone(summary["accountOpen"])
        self.assertIsNone(summary["dayPnlPct"])

    def test_flat_without_trades_is_real_zero(self):
        state=self.state()
        state["holdings"]["positions"]={}
        state["ledger"]["entries"]=[]
        summary=account_summary(state,[],"2026-10-14")
        self.assertEqual(summary["dayPnl"],0)
        self.assertEqual(summary["positionPct"],0)

    def test_cycle_return_uses_buy_capital_and_all_sells(self):
        state=self.state()
        state["ledger"]["entries"].insert(0,dict(id="buy",side="buy",code="002636",qty=30,
                    after_qty=30,price=10,amount=300,time="2026-10-13 09:32:00"))
        result=cycle_return(state,self.rows()[0])
        self.assertEqual(result["pnl"],60)
        self.assertEqual(result["pnl_pct"],20)
        self.assertEqual(result["base"],300)
        state["ledger"]["entries"].append(dict(state["ledger"]["entries"][-1],id="duplicate"))
        self.assertIsNone(cycle_return(state,self.rows()[0]))

    def test_delivery_query_uses_committed_revision_and_does_not_write(self):
        from unittest.mock import patch, Mock
        import index
        from trade_ledger import list_ledger_entries
        state=self.state()
        original=copy.deepcopy(state)
        store=Mock()
        store.snapshot.return_value=state
        with patch.object(index,"_HOLDINGS_STORE",store), patch("database_holdings.database_enabled",return_value=True):
            result=list_ledger_entries(session="2026-10-14")
        self.assertEqual(result["paperRevision"],7)
        self.assertEqual(result["summary"]["sell_pnl"],20)
        store.save.assert_not_called()
        self.assertEqual(state,original)


if __name__=="__main__":
    unittest.main()
