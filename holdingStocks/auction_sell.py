"""Factor29 sell preparation and audited bell-only settlement eligibility."""
from condition_buy import fresh_quote
from strategy.factors.factor29 import merge_auction_path, signal


def draft_auction_sell(pos, quote, *, session, now, entry_pct, tick=.01):
    if not '09:25:00' <= now.strftime('%H:%M:%S') < '09:30:00':
        return None
    bought = str(pos.get('buy_time') or '')
    if not bought or bought[:10] >= session or not int(pos.get('qty') or 0) or pos.get('hold_lock'):
        return None
    if not fresh_quote(quote, session, now) or str(quote['last_ts'])[11:19] < '09:25:00':
        return None
    path = merge_auction_path(quote=quote, session=session)
    hit = signal(baseline_px=path.get('baseline'), auction_high=path.get('high'),
                 auction_low=path.get('low'), threshold_pct=entry_pct, tick=tick)
    if not hit.get('hit_sell'):
        return None
    return dict(session=session, cycle=bought, open=quote['open'], status='ARMED',
                signal_factor='factor29', auction_path=path)


def auction_sell_ready(order, pos, quote, *, session, now):
    return bool(order and order.get('status') == 'ARMED' and order.get('session') == session
        and order.get('cycle') == pos.get('buy_time') and str(pos.get('buy_time') or '')[:10] < session
        and not pos.get('hold_lock') and int(pos.get('qty') or 0) > 0
        and '09:30:00' <= now.strftime('%H:%M:%S') <= '09:30:05'
        and fresh_quote(quote, session, now)
        and '09:30:00' <= str(quote.get('last_ts') or '')[11:19] <= '09:30:05'
        and abs(float(quote['open']) - float(order['open'])) < 1e-8)
