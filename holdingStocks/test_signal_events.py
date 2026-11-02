from signal_events import buy_signal_rows
from types import SimpleNamespace


def model():
    buy = dict(id='rebuy', side='buy', code='600330', name='天通股份', qty=3400, price=17.75,
               session='2026-11-02', time='2026-11-02 11:26:07')
    source = dict(buy, signal_factor='factor33', signal_time='2026-11-02 11:26:06', order_price=17.69)
    return SimpleNamespace(entries=[dict(side='sell', code='600330', time='2026-11-02 09:30:01'), buy],
                           state={'trades': [source]})


def test_rebuy_retains_its_own_event_time_type_and_price_after_sell_and_simulator_overrides():
    rows = buy_signal_rows(model(), '2026-11-02', [{'代码': '600330', '现价': 17.81, '已实现': True,
        '槽位留痕': True, '信号时间': '2026-11-02 09:30:00', '首次触买时间': '2026-10-30 10:00:00'}])
    assert len(rows) == 1
    row = rows[0]
    assert row['预警类型'] == '探底回升' and row['信号因子'] == 'factor33'
    assert row['买信号时间'] == row['信号时间'] == '2026-11-02 11:26:06'
    assert row['买入侧价'] == 17.69 and row['现价'] == 17.81
    assert row['已触买'] == '是' and not row['已实现'] and not row['槽位留痕']
    assert row['持仓'] == 0 and row['信号已成交']
    assert buy_signal_rows(model(), '2026-11-03') == []


def test_same_symbol_can_keep_different_buy_events_and_archived_events_are_excluded():
    m = model()
    m.entries.append(dict(m.entries[-1], id='morning', time='2026-11-02 09:30:00'))
    m.state['trades'].append(dict(m.entries[-1], signal_factor='factor29'))
    rows = buy_signal_rows(m, '2026-11-02')
    assert len(rows) == 2 and {r['预警类型'] for r in rows} == {'探底回升', '竞价强度'}
    m.state['trades'][-1]['reset_archived'] = True
    assert len(buy_signal_rows(m, '2026-11-02')) == 1


def test_wechat_messages_include_actionable_alert_type_without_sending():
    from wechat_notify import format_alert_message, alert_type_label
    assert alert_type_label({'signal_factor': 'factor33'}) == '探底回升'
    assert alert_type_label({'卖出原因': '中赚波动回落'}, sell=True) == '阶段回落（峰值）'
    message = format_alert_message({'代码': '600330', '名称': '天通股份', '持仓': 0,
        '已触买': '是', '信号因子': 'factor33', '预警': '已触买', '现价': 17.75, '买点': 17.69})
    assert '预警类型：探底回升' in message


def test_retained_unfilled_signal_keeps_its_type_when_removed_from_active_rows():
    from alert_retention import AlertRetention
    from datetime import datetime
    retention = AlertRetention(strategy_id='strategy1')
    row = dict(代码='600330', 持仓=0, 交易日='2026-11-02', 已触买='是', 预警='已触买',
               信号因子='factor33', 信号来源='探底回升', 预警类型='探底回升', 买信号时间='2026-11-02 11:26:06')
    retention.merge([row], now=datetime(2026,11,2,11,27), strategy_codes={'600330'})
    restored = retention.merge([], now=datetime(2026,11,2,13), strategy_codes={'600330'})
    assert restored[0]['预警类型'] == '探底回升'
    assert restored[0]['买信号时间'] == '2026-11-02 11:26:06'
