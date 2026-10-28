"""Opening-session latency budgets; execution rules are deliberately unchanged."""
from datetime import datetime


def opening_fast(now=None):
    now = now or datetime.now()
    return now.weekday() < 5 and '09:25:00' <= now.strftime('%H:%M:%S') < '09:40:00'


def quote_poll_interval(normal=1., now=None):
    return .25 if opening_fast(now) else max(1., float(normal))


def view_interval(now=None):
    return .1 if opening_fast(now) else .4
