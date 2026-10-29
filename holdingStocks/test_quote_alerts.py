"""Read-only alerts must survive the quote-runtime switch without minute IO or fills."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from quote_alerts import QuoteAlerts
from strategy.pullback_wave_stop import strategy_signal

NOW = datetime(2026, 10, 16, 10, 0, 1)
class QuoteAlertTests(unittest.TestCase):
    def test_failed_gate_clears_stale_signal_even_without_fresh_quote(self):
        monitor=QuoteAlerts()
        row=self.row(**{'过门OK':False,'已触买':'是','预警':'已触买·未入槽',
            '持仓状态':'待买入','因子侧':'买入','因子价':10.25,
            '信号时间':'2026-10-16 09:59:00','近买点':True})
        self.enrich(monitor,row,self.quote(last_ts='2026-10-15 15:00:00'))
        self.assertEqual(row['已触买'],'否')
        self.assertFalse(row['预警'])
        self.assertEqual(row['持仓状态'],'空仓')
        self.assertNotIn('信号时间',row)

    def row(self, **extra):
        return dict({'代码':'000070','交易日':'2026-10-16','持仓':0,'过门OK':True,
                     '已触买':'否','已触止损':'否','持仓状态':'空仓'}, **extra)
    def quote(self, **extra):
        return dict(dict(open=10.,last=10.24,high=10.5,low=9.9,prev_close=10.,
             session='2026-10-16',last_ts=str(NOW),_quote_source='sina_batch',
             _source_time_verified=True,_open_finalized=True),**extra)
    def enrich(self, monitor, row, quote, **extra):
        monitor.enrich(row,quote,now=NOW,signal=strategy_signal,entry_pct=.025,tick=.01,official_open=10.,**extra)
    def test_near_buy_populates_ui_and_notification_fields(self):
        row=self.row();self.enrich(QuoteAlerts(),row,self.quote())
        self.assertEqual(row['买点'],10.25)
        self.assertTrue(row['近买点']);self.assertTrue(row['当日预警'])
        from watch_buy_signal import is_buy_side_alert
        self.assertTrue(is_buy_side_alert(row))
        from wechat_notify import classify_stock_alert
        self.assertIsNotNone(classify_stock_alert(row))
    def test_only_observed_current_price_triggers_and_hit_remains_after_retrace(self):
        monitor=QuoteAlerts();row=self.row();self.enrich(monitor,row,self.quote(last=10.,high=11.))
        self.assertEqual(row['已触买'],'否')
        monitor.observe('000070',self.quote(last=10.26),NOW)
        row=self.row();self.enrich(monitor,row,self.quote(last=10.01))
        self.assertEqual(row['已触买'],'是')
        self.assertEqual(row['信号时间'],str(NOW))
    def test_unpassed_gate_and_blocked_order_never_alert_buy(self):
        for gate,blocked in [(False,False),(True,True)]:
            row=self.row(过门OK=gate);self.enrich(QuoteAlerts(),row,self.quote(last=10.26),blocked=blocked)
            self.assertFalse(row['近买点']);self.assertEqual(row['已触买'],'否')
    def test_stale_or_reference_quotes_never_generate_new_alert(self):
        for changes in [dict(last_ts=str(NOW-timedelta(seconds=10))),dict(_reference_only=True),dict(_source_time_verified=False)]:
            q=self.quote();q.update(changes);row=self.row();self.enrich(QuoteAlerts(),row,q)
            self.assertFalse(row.get('当日预警',False))
    def test_saved_open_is_not_shifted_by_a_conflicting_quote(self):
        row=self.row();q=self.quote();q['open']=10.01
        self.enrich(QuoteAlerts(),row,q)
        self.assertEqual(row['开盘'],10.)
        self.assertEqual(row['预警状态'],'开盘价不一致，等待复核')
        self.assertFalse(row.get('当日预警',False))
    def test_held_position_receives_near_stop_without_buy_alert(self):
        row=self.row(持仓=100,成本=10.,持仓最高=10.5,买入时间='2026-10-15 10:00:00',卖出侧价=10.25)
        self.enrich(QuoteAlerts(),row,self.quote(last=10.26))
        self.assertTrue(row['近止损']);self.assertTrue(row['当日预警'])
        self.assertFalse(row['近买点'])
        self.assertEqual(row['持仓状态'],'待卖出')
    def test_old_day_hit_does_not_leak_into_next_session(self):
        monitor=QuoteAlerts();row=self.row();self.enrich(monitor,row,self.quote(last=10.26))
        later=NOW+timedelta(days=3);row=self.row(交易日=str(later.date()));q=self.quote(last=10.);q.update(session=str(later.date()),last_ts=str(later))
        monitor.enrich(row,q,now=later,signal=strategy_signal,entry_pct=.025,tick=.01,official_open=10.)
        self.assertEqual(row['已触买'],'否')

    def test_real_collect_path_restores_alert_fields_without_market_io_or_trade_writes(self):
        import index
        from unittest.mock import Mock
        item=dict(code='000070',sina='sz000070',name='测试',market='SZ',pct=.025)
        book=dict(positions={},condition_buy_orders=dict(session='2026-10-16',orders={
            '000070':dict(id='audited',strategy='strategy1',open=10.,price=10.25,status='ARMED',open_audit_at='2026-10-16 09:25:00')}))
        model=Mock();model.state=dict(holdings=book,trades=[])
        store=Mock();store.read_model.return_value=model
        with patch.object(index,'_HOLDINGS_STORE',store), \
             patch.object(index,'_scan_watchlist',return_value=[item]), \
             patch('boot_holdings.build_boot_holdings',return_value=([],{})), \
             patch.object(index,'_STRATEGY_BOOKS_CLIENT',None), \
             patch.object(index,'_QUOTE_ALERTS',QuoteAlerts()), \
             patch.object(index,'_DAILY_CACHE',{'sz000070':('2026-10-16',None)}), \
             patch.object(index,'_prev_bars_from_daily',return_value=(10,10,10,10)), \
             patch.object(index,'_entry_gate_detail',return_value=(True,'前日阴线·过门','阴')), \
             patch.object(index,'_calendar_signal_session',return_value='2026-10-16'), \
             patch.object(index,'is_threshold_ready',return_value=True), \
             patch.object(index,'_enrich_comprehensive_trade_return'), \
             patch.object(index,'_today_1m_bars',side_effect=AssertionError('minute IO')), \
             patch.object(index,'_watch_daily',side_effect=AssertionError('daily IO')), \
             patch.object(index,'_apply_portfolio_slots',side_effect=AssertionError('trade write')), \
             patch.object(index,'datetime',wraps=datetime) as clock:
            clock.now.return_value=NOW
            rows=index._collect_quote_runtime_rows(get_quote=lambda _:self.quote())
        self.assertTrue(rows[0]['当日预警'])
        self.assertTrue(rows[0]['近买点'])
        self.assertEqual(rows[0]['开盘'],10.)
        self.assertEqual(rows[0]['开盘记录时间'],'2026-10-16 09:25:00')
        store.save.assert_not_called()

    def test_actual_holdings_outside_primary_pool_keep_risk_alert_scope(self):
        from wechat_notify import filter_default_strategy_alert_rows
        holding={'代码':'000070','持仓':100,'近止损':True}
        overlay={'代码':'000001','持仓':0,'近买点':True}
        with patch('wechat_notify.in_default_strategy_alert_scope',return_value=False):
            self.assertEqual(filter_default_strategy_alert_rows([holding,overlay]),[holding])
