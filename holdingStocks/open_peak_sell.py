"""Prepare low-open peak exits after auction finalization; fill only at the bell."""
from condition_buy import fresh_quote
from trading_calendar import is_trading_day
from strategy.pullback_wave_stop import working_stop_price


def draft_open_peak_sell(pos, quote, *, session, now, vol20_daily=None, tick=.01):
    clock = now.strftime('%H:%M:%S')
    bought = str(pos.get('buy_time') or '')
    if not is_trading_day(now.date()) or now.date().isoformat() != session:
        return None
    if not '09:25:00' <= clock < '09:30:00' or not bought or bought[:10] >= session:
        return None
    if int(pos.get('qty') or 0) <= 0 or pos.get('hold_lock') or not fresh_quote(quote, session, now):
        return None
    if str(quote.get('last_ts') or '')[11:19] < '09:25:00':
        return None
    opening, previous = float(quote.get('open') or 0), float(quote.get('prev_close') or 0)
    if not 0 < opening < previous:
        return None
    reason, stop = working_stop_price(cost_px=float(pos.get('cost') or 0),
        peak_high=float(pos.get('peak_high') or 0), day_open=opening,
        overnight_armed=bool(pos.get('stop_noted')), vol20_daily=vol20_daily, tick=tick)
    if stop <= 0 or opening > stop + 1e-12:
        return None
    return dict(session=session, cycle=bought, open=opening, peak=pos.get('peak_high'),
                stop=stop, reason=reason, status='ARMED')


def open_peak_sell_ready(order, pos, quote, *, session, now):
    return bool(order and order.get('status') == 'ARMED' and order.get('session') == session
        and order.get('cycle') == pos.get('buy_time') and not pos.get('hold_lock')
        and int(pos.get('qty') or 0) > 0
        and '09:30:00' <= now.strftime('%H:%M:%S') <= '09:30:05'
        and fresh_quote(quote, session, now)
        and '09:30:00' <= str(quote.get('last_ts') or '')[11:19] <= '09:30:05'
        and abs(float(quote.get('open') or 0) - float(order['open'])) < 1e-8
        and 0 < float(quote.get('open') or 0) < float(quote.get('prev_close') or 0)
        and float(quote['open']) <= float(order['stop']) + 1e-12)
