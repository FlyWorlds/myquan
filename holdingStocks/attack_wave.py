"""Observed attack waves, shared by alerts and both execution books.

No daily low/high reconstruction. Restart starts a new observation window.
Any downward tick after a rise starts a new trough; flat ticks keep direction.
"""
import threading
from condition_buy import fresh_quote


class AttackWaves:
    def __init__(self):
        self.lock = threading.RLock()
        self.states = {}

    def observe(self, code, quote, now):
        day = str(quote.get('session') or '')
        at = str(quote.get('last_ts') or '')
        clock = at[11:19]
        if not fresh_quote(quote, day, now) or not (
                '10:00:00' <= clock <= '11:30:00' or '13:00:00' <= clock < '15:00:00'):
            return
        price = float(quote['last'])
        with self.lock:
            old = self.states.get(code, {})
            if old.get('session') != day:
                old = {}
            if at <= old.get('at', ''):
                if at == old.get('at') and price == old.get('last'):
                    quote['_attack_wave'] = dict(old)
                return
            state = dict(old) if old else dict(session=day, low=price, ready=False,
                falling=False, start_at=at, low_at=at, anchor_at=at)
            if old and price < old['last']:
                if not old['falling']:
                    state.update(low=price, start_at=at, anchor_at=old['at'])
                else:
                    state['low'] = min(state['low'], price)
                state.update(ready=True, falling=True, low_at=at)
            elif old and price > old['last']:
                state['falling'] = False

            # 探底回升形态衔接：低开且日内最低价 < 开盘价-3%，反弹超过开盘价确认为探底就绪
            try:
                open_px = float(quote.get('open') or 0)
                prev_close = float(quote.get('prev_close') or quote.get('preclose') or 0)
                day_low = float(quote.get('low') or 0)
                # 1. 必须低开；2. 最低价小于开盘价-3%
                if open_px > 0 and (prev_close <= 0 or open_px < prev_close) and 0 < day_low <= open_px * 0.97:
                    if price >= day_low * 1.015:
                        ref_low = min(state.get('low', price), day_low)
                        state.update(low=ref_low, ready=True)
            except (TypeError, ValueError):
                pass

            state.update(at=at, last=price, code=code)
            self.states[code] = state
            quote['_attack_wave'] = dict(state)

    def snapshot(self, code, quote):
        with self.lock:
            state = quote.get('_attack_wave') or self.states.get(code, {})
            if not state or state.get('code') != code or state.get('session') != quote.get('session'):
                return {}
            return dict(state)


WAVES = AttackWaves()
