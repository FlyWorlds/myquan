"""Historical, unadjusted holding peaks; no network work on quote delivery."""
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def history_peak(buy_time, rows, *, session, buy_day_rows=()):
    bought = datetime.fromisoformat(buy_time)
    candidates = []
    for row in rows:
        day = str(row['date'])[:10]
        if bought.date().isoformat() < day < session:
            candidates.append((row.get('high'), day + ' 15:00:00'))
    # Daily bars cannot distinguish before/after an intraday purchase.
    for row in buy_day_rows:
        at = datetime.fromisoformat(str(row['ts']))
        if at.date() == bought.date() and at - timedelta(minutes=1) >= bought:
            candidates.append((row.get('high'), str(row['ts'])))
    valid = [(float(price), at) for price, at in candidates
             if price is not None and math.isfinite(float(price)) and float(price) > 0]
    return max(valid, default=None, key=lambda item: item[0])


def fetch_holding_history_peak(sina, buy_time, session):
    import akshare as ak
    from strategy.data import AKSHARE_CALL_LOCK
    start = buy_time[:10].replace('-', '')
    end = (datetime.fromisoformat(session) - timedelta(days=1)).strftime('%Y%m%d')
    if start > end:
        return None
    with AKSHARE_CALL_LOCK:
        daily = ak.stock_zh_a_daily(symbol=sina, start_date=start, end_date=end, adjust='')
    minute_rows = []
    path = Path(__file__).resolve().parents[1] / 'data_cache' / 'research_minutes.sqlite3'
    if path.exists():
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            minute_rows = [dict(row) for row in db.execute(
                'SELECT ts,high FROM research_minutes WHERE symbol=? AND ts>=? AND ts<?',
                (sina, buy_time, buy_time[:10] + ' 16:00:00'))]
    return history_peak(buy_time, daily.to_dict('records'), session=session, buy_day_rows=minute_rows)
