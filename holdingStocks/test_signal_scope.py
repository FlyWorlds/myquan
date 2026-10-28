import copy
import unittest
from unittest.mock import patch

from signal_scope import align_signal_scope, retained_inventory_codes


class SignalScopeTests(unittest.TestCase):
    def test_pool_switch_preserves_inventory_and_cash_but_cancels_foreign_entries(self):
        data = dict(account_cash=120000, positions={
            '600001':dict(qty=800,cost=10,buy_time='2026-10-27 10:00:00',peak_high=12),
            '600002':dict(qty=0,cost=11,buy_time='2026-10-26 10:00:00')},
            realized_today={'600003':dict(session='2026-10-28',price=12,qty=100)},
            portfolio_pool=['600001','600002','600004'], alert_sticky={'600004':{'f29_path':{}}},
            condition_buy_orders=dict(orders={
                '600004':dict(strategy='strategy16',status='ARMED'),
                '600005':dict(strategy='strategy1',status='ARMED'),
                '600006':dict(strategy='strategy1',status='TRIGGERED')}))
        original = copy.deepcopy(data)
        self.assertTrue(align_signal_scope(data,strategy_id='strategy1',strategy_codes={'600005'},session='2026-10-28'))
        self.assertEqual(data['positions'],original['positions'])
        self.assertEqual(data['account_cash'],original['account_cash'])
        self.assertEqual(data['realized_today'],original['realized_today'])
        self.assertEqual(data['portfolio_pool'],['600001','600003','600005'])
        orders=data['condition_buy_orders']['orders']
        self.assertEqual(orders['600004']['status'],'CANCELLED')
        self.assertEqual(orders['600006']['status'],'CANCELLED')
        self.assertEqual(orders['600005']['status'],'ARMED')
        self.assertEqual(data['alert_sticky'],{})
        self.assertFalse(align_signal_scope(data,strategy_id='strategy1',strategy_codes={'600005'},session='2026-10-28'))

    def test_primary_pool_never_appends_strategy16_candidates(self):
        import watch_config as cfg
        holdings=dict(portfolio_pool=['600002'], positions={
            '600001':dict(qty=100), '600002':dict(qty=0,cost=10)},realized_today={})
        base=[dict(code='600005',sina='sh600005',name='strategy1')]
        with patch.object(cfg,'STRATEGY_ID','strategy1'), \
             patch.object(cfg,'strategy_watchlist',return_value=base), \
             patch.object(cfg,'core_leader_codes',side_effect=AssertionError('strategy16 pool read')), \
             patch.object(cfg,'trading_session_date',return_value='2026-10-28'), \
             patch.object(cfg,'meta_for_code',side_effect=lambda code,_:dict(code=code,sina='sh'+code)), \
             patch.object(cfg,'merge_self_watchlist',side_effect=lambda rows,_:rows):
            rows=cfg.primary_watchlist(holdings)
        self.assertEqual({row['code'] for row in rows},{'600005','600001'})

    def test_full_scan_does_not_pull_strategy16b_into_strategy1(self):
        import index
        with patch.object(index,'STRATEGY_ID','strategy1'), \
             patch.object(index,'primary_watchlist',return_value=[{'code':'600005'}]), \
             patch.object(index,'_strategy16b_watchlist',side_effect=AssertionError('foreign scan')):
            self.assertEqual(index._scan_watchlist({},full=True),[{'code':'600005'}])

    def test_retention_flag_cannot_bypass_strategy1_holdings_boundary(self):
        from watch_snapshot import filter_portfolio_holdings
        rows=[dict(代码='600001',持仓=100,预警='持有',信号策略ID='strategy1'),
              dict(代码='600002',持仓=0,预警='将买入',近买点=True,当日预警=True,预警保留=True),
              dict(代码='600005',持仓=0,预警='将买入',近买点=True,当日预警=True,预警保留=True,信号策略ID='strategy16'),
              dict(代码='600006',持仓=0,预警='将买入',近买点=True,当日预警=True,信号策略ID='strategy1')]
        with patch('stock_names.resolve_stock_name',return_value='test'):
            selected=filter_portfolio_holdings(rows,phase='continuous',strategy_codes={'600005','600006'})
        self.assertEqual({row['代码'] for row in selected},{'600001','600006'})

    def test_snapshot_cannot_overlay_a_strategy16_order_on_strategy1_holdings(self):
        import index
        old=dict(strategy='strategy16',session='2026-10-28',price=99,status='CANCELLED')
        new=dict(strategy='strategy1',session='2026-10-28',price=10,status='ARMED')
        data=dict(condition_buy_orders=dict(session='2026-10-28',orders={'600001':old,'600005':new}))
        snap=dict(holdings=[dict(代码='600001',持仓=100)])
        with patch.object(index,'STRATEGY_ID','strategy1'), \
             patch.dict(index._HOLDINGS_CACHE,{'data':data},clear=True), \
             patch.object(index,'_current_feed_health',return_value={}), \
             patch.object(index,'market_phase',return_value='continuous'), \
             patch.object(index,'trading_session_date',return_value='2026-10-28'):
            index._stamp_snapshot_liveness(snap,clock='2026-10-28 10:00:00')
        self.assertEqual(snap['conditionBuy']['orders'],[new])
        self.assertNotIn('条件买入价',snap['holdings'][0])
