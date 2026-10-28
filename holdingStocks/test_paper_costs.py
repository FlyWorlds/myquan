import copy
import unittest
from unittest.mock import patch

from paper_costs import trade_costs, settle_trade, buy_cash_price
from account_reconciliation import AccountReadModel, account_summary
from trade_ledger import build_ledger_entry


class PaperCostsTests(unittest.TestCase):
    def test_stock_etf_cash_matches_backtest_formula_to_cents(self):
        from strategy.costs import ENGINE_COMMISSION_RATE, SLIPPAGE_VALUE, stamp_tax_for_code
        for code in ['600330', '001282', '510300']:
            for side in ['buy', 'sell']:
                for price, qty in [(10, 1000), (23.08, 2500), (14.82, 3900)]:
                    f = trade_costs(code, side, price, qty)
                    want = price*qty*(1+SLIPPAGE_VALUE)*(1+ENGINE_COMMISSION_RATE) if side == 'buy' else price*qty*(1-SLIPPAGE_VALUE)*(1-ENGINE_COMMISSION_RATE-stamp_tax_for_code(code))
                    self.assertAlmostEqual(f['net_amount'], want, delta=.005001)
                    if side == 'buy' or code == '510300':
                        self.assertEqual(f['stamp_tax'], 0)
        self.assertEqual(trade_costs('600330', 'buy', 10, 100)['commission'], .09)

    def test_partial_sales_allocate_entry_fees_once_and_cash_equals_net_pnl(self):
        # The existing fill functions apply gross cash/quantity before committing.
        h = dict(account_cash=90000., positions={'600330': dict(qty=1000, cost=10, buy_time='2026-10-21 10:00:00')}, realized_today={})
        buy = dict(id='b', time='2026-10-21 10:00:00', session='2026-10-21', side='buy', code='600330', price=10, qty=1000, after_qty=1000, amount=10000)
        settle_trade(buy, h)
        self.assertEqual(h['account_cash'], 89989.04)
        self.assertEqual(h['positions']['600330']['cost'], 10)
        before = copy.deepcopy(h)
        settle_trade(buy, h)
        self.assertEqual(h, before)
        records = [build_ledger_entry(buy)]
        for qty, remaining in [(400, 600), (600, 0)]:
            h['account_cash'] += 11*qty
            h['positions']['600330']['qty'] = remaining
            sell = dict(id='s'+str(qty), time='2026-10-22 10:00:00', session='2026-10-22', buy_time=buy['time'], side='sell', code='600330', price=11, qty=qty, after_qty=remaining, amount=11*qty, cost=10, pnl=qty, day_pnl=qty)
            h['realized_today']['600330'] = dict(sell, day_base=10*qty)
            settle_trade(sell, h)
            records.append(build_ledger_entry(sell))
            self.assertEqual(h['realized_today']['600330']['pnl'], sell['pnl'])
        self.assertEqual(sum(r.get('allocated_buy_fees', 0) for r in records), buy['total_fees'])
        self.assertEqual(h['positions']['600330']['buy_fees_remaining'], 0)
        self.assertAlmostEqual(sum(r.get('pnl') or 0 for r in records), h['account_cash']-100000, places=2)
        self.assertIn('total_fees', records[0])

    def test_account_day_and_cycle_returns_include_buy_fee_without_double_count(self):
        h = dict(account_cash=90000., paper_equity_base=100000., positions={'600330': dict(qty=1000, cost=10, buy_time='2026-10-22 10:00:00')})
        buy = dict(id='b', time='2026-10-22 10:00:00', session='2026-10-22', side='buy', code='600330', price=10, qty=1000, after_qty=1000, amount=10000)
        settle_trade(buy, h)
        state = dict(revision=1, holdings=h, trades=[buy], ledger=dict(entries=[build_ledger_entry(buy)]))
        row = {'代码':'600330', '持仓':1000, '成本':10, '现价':10, '昨收':10}
        model = AccountReadModel(state)
        summary = account_summary(state, [row], '2026-10-22', read_model=model)
        self.assertEqual(summary['dayPnl'], -10.96)
        self.assertEqual(summary['totalPnl'], -10.96)
        self.assertEqual(model.cycle_return(row)['pnl'], -10.96)
        self.assertEqual(model.cycle_return(row)['base'], 10010.96)
        row['交易日'] = '2026-10-23'
        self.assertEqual(account_summary(state, [row], '2026-10-23', read_model=model)['dayPnl'], 0)

    def test_real_commit_hook_applies_costs_before_database_save(self):
        import index
        h = dict(account_cash=9000, positions={'600330': dict(qty=100, cost=10)})
        record = dict(side='buy', code='600330', price=10, qty=100, after_qty=100, amount=1000)
        with patch.object(index, 'database_enabled', return_value=True), patch.object(index, 'append_trades') as save:
            index._commit_trade(record, holdings=h)
        self.assertEqual(save.call_args.kwargs['holdings']['account_cash'], 8998.90)
        self.assertEqual(record['net_amount'], 1001.10)

    def test_budget_reserves_costs_and_legacy_sale_does_not_invent_buy_fees(self):
        from watch_config import capital_buy_qty
        qty, reason = capital_buy_qty(price=buy_cash_price(10), equity=5000, cash=1000, weight=.2)
        self.assertEqual(qty, 0)
        h = dict(account_cash=1100, positions={'600330': dict(qty=0)})
        record = dict(side='sell', code='600330', price=11, qty=100, after_qty=0, cost=10, pnl=100)
        settle_trade(record, h)
        self.assertEqual(record['allocated_buy_fees'], 0)
        self.assertEqual(record['pnl'], 98.25)


if __name__ == '__main__':
    unittest.main()
