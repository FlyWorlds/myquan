"""Today's return starts at 09:15 on trading days, after 09:00 morning reset.

Non-trading days (weekends, holidays) and pre-09:00 preserve previous session's return.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo
from trading_calendar import is_trading_day


def day_pnl_started(now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    # 非交易日（周六、周日、休市日）保留上一交易日结算盈亏展示，不抹为 None
    if not is_trading_day(now.date()):
        return True
    t = now.time().replace(tzinfo=None)
    # 交易日 09:00 之前：尚未执行 09:00 早盘重置，展示上一交易日盈亏
    if t < time(9, 0):
        return True
    # 交易日 09:00–09:15：09:00 已执行早盘重置，集合竞价尚未开始，处于盘前待竞价
    if t < time(9, 15):
        return False
    # 交易日 09:15 之后：集合竞价与连续竞价，正常展示当日盈亏
    return True


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
