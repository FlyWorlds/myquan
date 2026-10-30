import unittest
from signal_priority import signal_priority
from wechat_notify import format_sell_fill_message, format_buy_fill_message, format_alert_message

class SignalPriorityTests(unittest.TestCase):
    def test_risk_wins_over_profit_and_peak(self):
        self.assertEqual(signal_priority('半仓止盈 峰值回撤 hard_from_cost'), 'P0 紧急')
        self.assertEqual(signal_priority('风险强制退出'), 'P0 紧急')
    def test_categories(self):
        for reason in ('t1_peak_trail', 'peak_pullback_clear', '趋势破位'):
            self.assertEqual(signal_priority(reason), 'P1 重要')
        for reason in ('ladder_half_10', '常规止盈', '调仓换股'):
            self.assertEqual(signal_priority(reason), 'P2 普通')
    def test_messages(self):
        base=dict(code='600000',name='测试',price=10,qty=100)
        self.assertIn('等级：P0 紧急',format_sell_fill_message(**base,reason_code='HALF',priority_reason='hard_from_cost'))
        self.assertIn('等级：P1 重要',format_sell_fill_message(**base,reason_code='t1_peak_trail'))
        self.assertIn('等级：P2 普通',format_buy_fill_message(**base))
        self.assertIn('等级：P0 紧急',format_alert_message({'代码':'600000','名称':'测试','reason':'hard_from_cost'}))
