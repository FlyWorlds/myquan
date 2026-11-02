"""Display-only buy events from committed deliveries; independent of current inventory."""
from __future__ import annotations


def buy_signal_rows(model, session, market_rows=()):
    quotes = {str(r.get('代码')): r for r in market_rows}
    originals = {t.get('id'): t for t in model.state.get('trades', []) if t.get('id')}
    rows = []
    for entry in model.entries:
        if entry.get('side') != 'buy' or str(entry.get('session') or entry.get('time') or '')[:10] != session:
            continue
        source = {**originals.get(entry.get('id'), {}), **entry}
        if source.get('reset_archived') or int(source.get('qty') or 0) <= 0:
            continue
        code = str(source.get('code') or '')
        detail = str(source.get('note') or source.get('reason_detail') or '')
        factor = source.get('signal_factor') or ('factor33' if '反弹' in detail or '探底' in detail else
            'factor29' if '竞价' in detail else 'factor26')
        label = {'factor33': '探底回升', 'factor29': '竞价强度', 'factor26': '开盘突破'}.get(factor, '买入信号')
        at = source.get('signal_time') or source.get('time')
        price = source.get('order_price') or source.get('price')
        row = dict(quotes.get(code) or {})
        row.update({'记录ID': source.get('id') or f'{code}-{at}', '代码': code,
            '名称': source.get('name') or row.get('名称') or code, '市场': source.get('market') or row.get('市场'),
            '交易日': session, '持仓': 0, '置顶': False, '槽位留痕': False, '三槽平仓': False,
            '已实现': False, '持仓状态': '待买入', '已触买': '是', '已触止损': '否',
            '预警': '已触买', '近止损': False, '信号因子': factor, '信号来源': label, '预警类型': label,
            '买点': price, '买入侧价': price, '阈值就绪': True,
            '买信号时间': at, '信号时间': at, '首次触买时间': at,
            '信号已成交': True, '信号成交价': source.get('price'), '信号成交数量': source.get('qty'),
            '挂单说明': f'{label}；已模拟买入 {source.get("qty")}股@{source.get("price")}'})
        rows.append(row)
    return sorted(rows, key=lambda r: (str(r['买信号时间']), str(r['记录ID'])))
