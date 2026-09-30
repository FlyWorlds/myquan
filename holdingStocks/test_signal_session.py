"""信号交易日 / 前日锚定（休市日→上一交易日）。"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_config import (  # noqa: E402
    last_weekday,
    normalize_signal_session,
    prev_trading_day,
    trading_session_date,
)
from index import _prev_bars_from_daily  # noqa: E402


def test_weekend_and_monday_anchor() -> None:
    fri = dt.date(2026, 9, 11)  # 周五
    assert last_weekday(dt.date(2026, 9, 12)) == fri  # 周六
    assert last_weekday(dt.date(2026, 9, 13)) == fri  # 周日
    assert trading_session_date(dt.datetime(2026, 9, 12, 10, 0)) == fri
    assert trading_session_date(dt.datetime(2026, 9, 14, 10, 0)) == dt.date(2026, 9, 14)
    # 周一的前一交易日 = 上周五
    assert prev_trading_day(dt.date(2026, 9, 14)) == fri
    assert normalize_signal_session("2026-09-13") == "2026-09-11"
    assert normalize_signal_session("2026-09-14") == "2026-09-14"


def test_exchange_holiday_anchor() -> None:
    # 2026 National Day: SSE closes Oct 1-7 and resumes Oct 8.
    assert trading_session_date(dt.datetime(2026, 10, 1, 10, 0)) == dt.date(2026, 9, 30)
    assert trading_session_date(dt.datetime(2026, 10, 7, 10, 0)) == dt.date(2026, 9, 30)
    assert trading_session_date(dt.datetime(2026, 10, 8, 10, 0)) == dt.date(2026, 10, 8)
    assert prev_trading_day(dt.date(2026, 10, 8)) == dt.date(2026, 9, 30)
    assert normalize_signal_session("2026-10-03") == "2026-09-30"


def test_prev_bars_monday_uses_friday() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-09-09", "2026-09-10", "2026-09-11"]
            ),  # 周三/四/五
            "open": [10.0, 11.0, 12.0],
            "close": [10.5, 10.8, 12.5],
        }
    )
    # 周一 session：前日应为周五 9/11
    o, c, o2, c2 = _prev_bars_from_daily(daily, "2026-09-14")
    assert (o, c) == (12.0, 12.5)
    assert (o2, c2) == (11.0, 10.8)
    # 周末 session 规范化到周五后，前日落到周四 9/10
    o, c, _, _ = _prev_bars_from_daily(daily, "2026-09-13")
    assert (o, c) == (11.0, 10.8)


if __name__ == "__main__":
    test_weekend_and_monday_anchor()
    test_exchange_holiday_anchor()
    test_prev_bars_monday_uses_friday()
    print("ok")
