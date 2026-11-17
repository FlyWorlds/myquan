"""Strategy 1 live entry schedule; all phases share the real portfolio slots."""
import math
from strategy.open_break import entry_trigger_price

LABELS = {'auction_open': '因子29·竞价末段强度', 'breakout': '因子26·开盘突破',
          'day_low_rebound': '因子33·探底反包开盘价'}


def phase_at(now):
    clock = now.strftime('%H:%M:%S')
    if '09:25:00' <= clock < '09:30:00':
        return 'auction_open'
    if '09:30:00' <= clock < '10:00:00':
        return 'breakout'
    if '10:00:00' <= clock <= '11:30:00':
        return 'day_low_rebound'
    return None


def effective_order(order, quote):
    if order.get('strategy') != 'strategy1' or order.get('kind') != 'day_low_rebound':
        return order
    from attack_wave import WAVES
    wave = WAVES.snapshot(order['code'], quote)
    since = str(order.get('reentry_after') or '')
    ready = bool(wave.get('ready') and (not since or wave.get('anchor_at', '') > since))
    low = wave.get('low')
    open_px = float(order.get('open') or quote.get('open') or 0)
    prev_close = float(order.get('prev_close') or quote.get('prev_close') or quote.get('preclose') or 0)
    tick = float(order.get('tick') or 0.01)
    entry_pct = float(order.get('entry_pct') or 0.015)

    # 铁律 1: 必须低开 (open < prev_close)
    if prev_close > 0 and open_px >= prev_close:
        return dict(order, wave_ready=False)

    try:
        quote_low = float(quote.get('low') or 0)
        # 铁律 2: 最低价必须小于开盘价 -3% (low <= open * 0.97)
        if open_px > 0 and 0 < quote_low <= open_px * 0.97:
            if not low or quote_low < low:
                low = quote_low
                ready = True
    except (TypeError, ValueError):
        pass

    # 若未发生有效探底（跌幅未达开盘价-3%），不能触发买入
    if not low or (open_px > 0 and low > open_px * 0.97):
        return dict(order, wave_ready=False)

    # 铁律 3: 回升超过开盘价
    rebound_px = entry_trigger_price(low, entry_pct=entry_pct, tick=tick)
    break_open_px = round(open_px + tick, 4) if open_px > 0 else rebound_px
    target_price = max(break_open_px, rebound_px)

    return dict(order, price=target_price, reference_low=low, wave_ready=ready,
                wave_start=wave.get('start_at'), wave_low_at=wave.get('low_at'))


def phase_allowed(order, now):
    if order.get('strategy') != 'strategy1':
        return True
    kind = order.get('kind')
    # Audited official-open quotes may settle auction orders from 09:25.
    if kind == 'auction_open':
        return '09:25:00' <= now.strftime('%H:%M:%S') <= '09:30:05'
    return kind == phase_at(now)


def quota_reason(order, trades, session):
    if order.get('strategy') != 'strategy1':
        return None
    kind = order.get('kind')

    # 统计当日各类型买入数
    auction_buys = 0
    breakout_buys = 0
    rebound_buys = 0
    for trade in trades:
        if str(trade.get('side') or '').lower() != 'buy' or trade.get('reset_archived'):
            continue
        at = str(trade.get('session') or trade.get('time') or '')
        if at[:10] != session:
            continue
        factor = trade.get('signal_factor')
        clock = str(trade.get('time') or '')[11:19]
        phase = 'auction_open' if factor == 'factor29' else ('day_low_rebound' if factor == 'factor33' or clock >= '10:00:00' else 'breakout')
        if phase == 'auction_open':
            auction_buys += 1
        elif phase == 'breakout':
            breakout_buys += 1
        elif phase == 'day_low_rebound':
            rebound_buys += 1

    total_buys = auction_buys + breakout_buys + rebound_buys

    # 单日新增总槽位限制：仓位建议未到60%时单日新增不超过2槽
    try:
        from watch_config import dynamic_max_new_symbols_per_session
        max_daily_new = dynamic_max_new_symbols_per_session()
    except Exception:
        max_daily_new = 2

    if total_buys >= max_daily_new:
        return 'ENTRY_PHASE_QUOTA'

    # 1. 竞价段（09:25~09:30）：限额 1 只
    if kind == 'auction_open':
        if auction_buys >= 1:
            return 'ENTRY_PHASE_QUOTA'

    # 2. 开盘突破段（09:30~10:00）：
    # 竞价落空机制：若竞价买入 0 只，则 09:30~10:00 允许买入 2 只；若竞价已买 1 只，则 09:30~10:00 允许买入 1 只
    elif kind == 'breakout':
        max_breakout = 2 if auction_buys == 0 else 1
        if breakout_buys >= max_breakout:
            return 'ENTRY_PHASE_QUOTA'

    # 3. 探底回升段（10:00~11:30）：
    # 探底回升可以买一槽；如果竞价买了且突破买了，探底回升就不买；竞价没买的，探底回升可以买
    elif kind == 'day_low_rebound':
        if rebound_buys >= 1:
            return 'ENTRY_PHASE_QUOTA'
        if auction_buys >= 1 and breakout_buys >= 1:
            return 'ENTRY_PHASE_QUOTA'

    return None
