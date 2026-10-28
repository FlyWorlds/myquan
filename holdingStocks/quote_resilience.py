"""Bounded source failover; source timestamps remain the authority for freshness."""
from __future__ import annotations

import math
import time
from datetime import datetime


def usable_quote(spot, *, now=None, continuous=False):
    try:
        stamp = datetime.strptime(spot['last_ts'], '%Y-%m-%d %H:%M:%S')
        values = [float(spot[k]) for k in ('last', 'open', 'high', 'low', 'prev_close')]
        last, opening, high, low, _ = values
        if not all(math.isfinite(v) and v > 0 for v in values):
            return False
        if low > min(last, opening) or high < max(last, opening):
            return False
        if spot.get('_trade_quality_ok') is False:
            return False
        age = ((now or datetime.now()) - stamp).total_seconds()
        return age >= -2 and (not continuous or age <= 40)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


class SourceRouter:
    """One instance per poll group, so a failing batch never blocks other groups."""
    def __init__(self, sources, *, clock=time.monotonic, log=lambda _: None):
        self.sources, self.clock, self.log = sources, clock, log
        self.states = {name: dict(failures=0, retryAt=0., trips=0, attempts=0,
                                 successes=0, latencyMs=None, lastSuccessAt=None,
                                 lastFailureAt=None, lastError=None) for name, _ in sources}

    def fetch(self, codes, *, now=None, continuous=False, source_names=None):
        result = {}
        for name, fetch in self.sources:
            if source_names is not None and name not in source_names:
                continue
            missing = [code for code in codes if code not in result]
            if not missing:
                break
            state = self.states[name]
            if self.clock() < state['retryAt']:
                continue
            started = self.clock()
            state['attempts'] += 1
            error = 'empty_or_stale'
            responded = False
            try:
                raw = fetch(missing, timeout=(2, 3))
                responded = any(code in missing and usable_quote(spot, now=now, continuous=False)
                                for code, spot in raw.items())
                valid = {code: dict(spot, _quote_source=name) for code, spot in raw.items()
                         if code in missing and usable_quote(spot, now=now, continuous=continuous)}
            except Exception as exc:
                valid, error = {}, type(exc).__name__
            state['latencyMs'] = round((self.clock()-started)*1000, 1)
            if valid:
                if state['failures']:
                    self.log(f'行情源 {name} 恢复')
                state.update(failures=0, retryAt=0., trips=0, lastError=None,
                             lastSuccessAt=(now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'))
                state['successes'] += 1
                result.update(valid)
            elif responded:
                # A successful response carrying the 09:25 auction quote at the bell
                # must not trip a 30s network circuit before the first 09:30 tick arrives.
                state.update(failures=0, retryAt=0., trips=0, lastError='stale_quote')
            else:
                state['failures'] += 1
                state.update(lastError=error, lastFailureAt=(now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'))
                if state['failures'] >= 3:
                    delay = min(300, 30 * 2**min(state['trips'], 4))
                    state['trips'] += 1
                    state['retryAt'] = self.clock() + delay
                    self.log(f'行情源 {name} 连续失败，暂停 {delay}s 后探测')
        return result

    def status(self):
        return {name: dict(state, retryInSec=round(max(0., state['retryAt']-self.clock()), 1),
                           circuit='open' if self.clock() < state['retryAt'] else 'closed')
                for name, state in self.states.items()}
