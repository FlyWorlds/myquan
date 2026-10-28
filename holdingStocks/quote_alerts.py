"""Read-only quote alerts, independent of auto-fill quotas and minute downloads."""
from __future__ import annotations

import threading
from datetime import datetime

from condition_buy import fresh_quote, timestamp


class QuoteAlerts:
    def __init__(self):
        self._lock = threading.RLock()
        self._session = None
        self._targets = {}
        self._hits = {}

    def observe(self, code, quote, now):
        session = str(quote.get('session') or '')
        at = timestamp(quote.get('last_ts'))
        if not at or not fresh_quote(quote, session, now):
            return
        clock = at.strftime('%H:%M:%S')
        if not ('09:30:00' <= clock <= '11:30:00' or '13:00:00' <= clock < '15:00:00'):
            return
        with self._lock:
            target = self._targets.get(code)
            if not target or target['session'] != session:
                return
            if abs(float(quote['open']) - target['open']) > target['tick'] / 10:
                return
            if float(quote['last']) >= target['price']:
                self._hits.setdefault((session, code, target['price'], target.get('factor')), quote['last_ts'])

    def enrich(self, row, quote, *, now, signal, entry_pct, tick, official_open=None,
               blocked=False):
        session = str(row.get('交易日') or '')
        code = str(row.get('代码') or '')
        opening = float(official_open or 0)
        if opening <= 0:
            return
        from watch_config import official_buy_trigger, is_signal_window, is_threshold_ready
        if not is_threshold_ready(now):
            return
        buy = float(row.get('买点') or official_buy_trigger(opening, entry_pct=entry_pct, tick=tick))
        qty = int(row.get('持仓') or 0)
        allowed = bool(row.get('过门OK')) and not blocked and not row.get('已实现')
        with self._lock:
            if self._session != session:
                self._targets.clear(); self._hits.clear(); self._session = session
            if allowed and qty == 0:
                self._targets[code] = dict(session=session, open=opening, price=buy, tick=tick, factor=row.get('信号因子'))
            else:
                self._targets.pop(code, None)
        self.observe(code, quote, now)
        row.update({'开盘': opening, '买点': buy, '买入侧价': buy, '阈值就绪': True})
        if row.get('已实现'):
            return
        if not fresh_quote(quote, session, now):
            row['预警状态'] = '等待当日新鲜报价'
            return
        # A changed official open is an audit conflict, not permission to shift the trigger.
        if abs(float(quote['open']) - opening) > tick / 10:
            row['预警状态'] = '开盘价不一致，等待复核'
            return
        with self._lock:
            first_hit = self._hits.get((session, code, buy, row.get('信号因子'))) if allowed else None
        last = float(quote['last'])
        stop = row.get('卖出侧价')
        sig = signal(open_px=opening, high_px=float(quote['high']), low_px=float(quote['low']),
            last_px=last, session=session, buy_trigger=buy, stop_px=stop, qty=qty,
            buy_time=row.get('买入时间'), vs_open_pts=(last/opening-1)*100,
            entry_pct=entry_pct, tick=tick, allow_entry=allowed,
            hit_buy=bool(first_hit) and qty == 0,
            hit_stop=bool(qty > 0 and stop and last <= float(stop) and is_signal_window(now)),
            cost_px=row.get('成本'), peak_high=row.get('持仓最高'))
        for key in ('因子侧','因子价','因子触发','建议挂单','距买点%','距买点价差','距止损%','距止损价差'):
            if key in sig:
                row[key] = sig[key]
        row.update({'预警': sig['alert'], '近买点': bool(sig['pending_buy']),
            '近止损': bool(sig['pending_sell']), 'bg_class': sig['bg_class'],
            '当日预警': bool(sig['pending_buy'] or sig['pending_sell']),
            '已触买': '是' if first_hit and qty == 0 else row.get('已触买','否'),
            '已触止损': '是' if sig['hit_stop'] else row.get('已触止损','否'),
            '预警状态': '报价监控中'})
        if first_hit and qty == 0:
            row['信号时间'] = first_hit
            row['已触发因子侧'] = '买入'
            row['已触发因子价'] = buy
        if sig.get('pending_buy') and qty == 0:
            row['持仓状态'] = '待买入'
        if sig.get('pending_sell') and qty > 0 and str(row.get('买入时间') or '')[:10] < session:
            row['持仓状态'] = '待卖出'
        note = str(row.get('挂单说明') or '')
        extra = str(sig.get('挂单说明') or '').strip()
        if extra and extra not in note:
            row['挂单说明'] = '；'.join(x for x in (note, extra) if x)
