"""Today's return starts at 09:15 Shanghai time, independently of signal timing."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
from trading_calendar import is_trading_day


def day_pnl_started(now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    return is_trading_day(now.date()) and now.time().replace(tzinfo=None) >= time(9, 15)


def apply_day_pnl_window(snapshot, now=None):
    ready = day_pnl_started(now)
    account = snapshot.setdefault('account', {})
    changed = account.get('dayPnlStarted') != ready
    account['dayPnlStarted'] = ready
    if ready:
        return changed
    for key in ('dayPnl', 'dayPnlPct', 'equityDayPnl', 'rowDayPnl', 'dayPnlVsRows',
                'dayPnlVsEquity', 'settledDayPnl'):
        changed = changed or account.get(key) is not None
        account[key] = None
    for section in ('holdings', 'strategy1', 'strategy16', 'strategy16b', 'strategy17'):
        for row in snapshot.get(section) or []:
            changed = changed or row.get('当日盈亏') is not None or row.get('当日盈亏%') is not None
            row['当日盈亏'] = None
            row['当日盈亏%'] = None
    return changed
