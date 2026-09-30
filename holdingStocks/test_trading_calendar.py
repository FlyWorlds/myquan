"""A-share trading calendar regression tests."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

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


class TestTradingCalendar(unittest.TestCase):
    def test_weekend_still_anchors_to_friday(self) -> None:
        fri = dt.date(2026, 9, 11)
        self.assertEqual(last_weekday(dt.date(2026, 9, 12)), fri)
        self.assertEqual(last_weekday(dt.date(2026, 9, 13)), fri)
        self.assertEqual(trading_session_date(dt.datetime(2026, 9, 12, 10)), fri)
        self.assertEqual(trading_session_date(dt.datetime(2026, 9, 14, 10)), dt.date(2026, 9, 14))
        self.assertEqual(prev_trading_day(dt.date(2026, 9, 14)), fri)

    def test_mid_autumn_2026_holiday(self) -> None:
        self.assertEqual(
            trading_session_date(dt.datetime(2026, 9, 25, 10)),
            dt.date(2026, 9, 24),
        )
        self.assertEqual(normalize_signal_session("2026-09-27"), "2026-09-24")
        self.assertEqual(prev_trading_day("2026-09-28"), dt.date(2026, 9, 24))

    def test_national_day_2026_holiday(self) -> None:
        for day in range(1, 8):
            self.assertEqual(
                trading_session_date(dt.datetime(2026, 10, day, 10)),
                dt.date(2026, 9, 30),
            )
        self.assertEqual(trading_session_date(dt.datetime(2026, 10, 8, 10)), dt.date(2026, 10, 8))
        self.assertEqual(prev_trading_day("2026-10-08"), dt.date(2026, 9, 30))
        self.assertEqual(normalize_signal_session("2026-10-03"), "2026-09-30")


if __name__ == "__main__":
    unittest.main()
