import copy
import unittest
from unittest.mock import patch

from signal_scope import (
    align_signal_scope,
    retained_inventory_codes,
    unclosed_lifecycle_codes,
    purge_closed_signals_at_next_session,
    purge_stale_unheld_signals,
)


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
                '600006':dict(strategy='strategy1',status='ARMED')}))
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

    def test_closure_principle_preserves_unclosed_buy_signals_on_pool_switch(self):
        # 闭环原则：策略换池时，已有持仓(603138)与已触发买入尚未完成卖出(002093)的股票，必须保留在监听队列中
        holdings = {
            "positions": {
                "603138": {"qty": 4000, "cost": 15.0},
                "002093": {"qty": 0},  # 虽未登记实仓，但已触发买入信号且尚未平仓
                "600001": {"qty": 0},  # 纯未触发的旧候选
            },
            "condition_buy_orders": {
                "orders": {
                    "603138": {"status": "FILLED", "strategy": "strategy1"},
                    "002093": {"status": "TRIGGERED", "strategy": "strategy1"},
                    "600001": {"status": "ARMED", "strategy": "strategy1"},
                }
            },
            "realized_today": {},
        }
        # 新目标池不包含 603138, 002093, 600001
        new_strategy_codes = {"603206", "000601"}
        session = "2026-11-06"

        retained = retained_inventory_codes(holdings, session)
        self.assertIn("603138", retained)
        self.assertIn("002093", retained)
        self.assertNotIn("600001", retained)

        align_signal_scope(holdings, strategy_id="strategy1", strategy_codes=new_strategy_codes, session=session)
        # 验证 603138 与 002093 均保留在 portfolio_pool 中继续拉行情
        self.assertIn("603138", holdings["portfolio_pool"])
        self.assertIn("002093", holdings["portfolio_pool"])
        # 纯未触发的 600001 挂单被取消
        self.assertEqual(holdings["condition_buy_orders"]["orders"]["600001"]["status"], "CANCELLED")

    def test_delayed_cleanup_and_next_session_reset(self):
        # 延迟清理与次日重置：
        # 当日触发卖出的股票，当日必须保留供用户核对；次日 9:00 重置时才执行销毁清理
        holdings = {
            "positions": {
                "603138": {"qty": 0, "cost": None, "note": "10点前跌破开盘-1%止损@14.8"},
            },
            "condition_buy_orders": {
                "session": "2026-11-06",
                "orders": {
                    "603138": {"status": "FILLED", "strategy": "strategy1"},
                }
            },
            "realized_today": {
                "603138": {"session": "2026-11-06", "reason": "止损卖出", "full_exit": True, "qty": 4000}
            },
            "alert_sticky": {"603138": {"sticky": True}},
            "portfolio_pool": ["603138", "603206"],
        }
        # 1. 在卖出当日 (2026-11-06)：retained 必须包含 603138，保证当日视觉留存
        retained_today = retained_inventory_codes(holdings, "2026-11-06")
        self.assertIn("603138", retained_today)

        # 2. 到了下一个交易日早盘 9:00 (2026-11-09)：触发次日重置清理
        new_active_codes = {"603206", "000601"}  # 新目标池不含 603138
        next_session = "2026-11-09"

        # 执行次日 9:00 重置清理
        changed = purge_closed_signals_at_next_session(holdings, active_strategy_codes=new_active_codes, session=next_session)
        self.assertTrue(changed)

        # 昨天已完成卖出闭环的 603138，在次日 9:00 正式被销毁清理
        orders = holdings["condition_buy_orders"]["orders"]
        self.assertNotIn("603138", orders)
        self.assertNotIn("603138", holdings["alert_sticky"])
        self.assertNotIn("603138", holdings["portfolio_pool"])
