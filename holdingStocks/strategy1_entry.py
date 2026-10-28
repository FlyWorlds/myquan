"""Strategy 1 live entry schedule; all phases share the real portfolio slots."""
import math
from strategy.open_break import entry_trigger_price

LABELS = {'auction_open': '因子29·竞价末段强度', 'breakout': '因子26·开盘突破',
          'day_low_rebound': '因子33·日内低点反弹'}


def phase_at(now):
    clock = now.strftime('%H:%M:%S')
    if '09:25:00' <= clock < '09:30:00':
        return 'auction_open'
    if '09:30:00' <= clock < '10:00:00':
        return 'breakout'
    if '10:00:00' <= clock <= '11:30:00' or '13:00:00' <= clock < '15:00:00':
        return 'day_low_rebound'
    return None


def effective_order(order, quote):
    if order.get('strategy') != 'strategy1' or order.get('kind') != 'day_low_rebound':
        return order
    try:
        low = float(quote.get('low') or 0)
    except (TypeError, ValueError, OverflowError):
        return order
    if not math.isfinite(low) or low <= 0:
        return order
    return dict(order, price=entry_trigger_price(low, entry_pct=float(order['entry_pct']), tick=float(order['tick'])),
                reference_low=low)


def phase_allowed(order, now):
    if order.get('strategy') != 'strategy1':
        return True
    kind = order.get('kind')
    # Auction is prepared during 09:25–09:30 and settled using the first audited bell quote.
    if kind == 'auction_open':
        return '09:30:00' <= now.strftime('%H:%M:%S') <= '09:30:05'
    return kind == phase_at(now)


def quota_reason(order, trades, session):
    if order.get('strategy') != 'strategy1' or order.get('kind') == 'day_low_rebound':
        return None
    kind = order.get('kind')
    for trade in trades:
        if str(trade.get('side') or '').lower() != 'buy' or trade.get('reset_archived'):
            continue
        at = str(trade.get('session') or trade.get('time') or '')
        if at[:10] != session:
            continue
        factor = trade.get('signal_factor')
        clock = str(trade.get('time') or '')[11:19]
        phase = 'auction_open' if factor == 'factor29' else ('day_low_rebound' if factor == 'factor33' or clock >= '10:00:00' else 'breakout')
        if phase == kind:
            return 'ENTRY_PHASE_QUOTA'
    return None
