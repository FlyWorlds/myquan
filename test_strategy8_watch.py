"""策略八盯盘：题材日与实时涨停（不联网）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_HS = Path(__file__).resolve().parent / "holdingStocks"
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from strategy8_watch import _quote_is_limit_up, resolve_theme_date  # noqa: E402


class TestStrategy8ThemeLive(unittest.TestCase):
    def test_theme_date_follows_intraday_quotes(self) -> None:
        now = pd.Timestamp("2026-09-01 10:30:00")
        ds = resolve_theme_date("2026-08-28", live_quotes=True, now=now)
        self.assertEqual(ds, "2026-09-01")

    def test_theme_date_pre_auction_keeps_last_session(self) -> None:
        now = pd.Timestamp("2026-09-01 08:00:00")
        ds = resolve_theme_date("2026-08-28", live_quotes=True, now=now)
        self.assertNotEqual(ds, "2026-09-01")
        self.assertLessEqual(str(ds), "2026-08-28")

    def test_theme_date_weekend_not_today(self) -> None:
        now = pd.Timestamp("2026-09-05 10:30:00")
        ds = resolve_theme_date("2026-08-28", live_quotes=True, now=now)
        self.assertNotEqual(ds, "2026-09-05")
        self.assertIsNotNone(ds)

    def test_quote_limit_up_10pct(self) -> None:
        q = {"prev_close": 10.0, "last": 11.0, "high": 11.0}
        self.assertTrue(_quote_is_limit_up("600000", q))
        q2 = {"prev_close": 10.0, "last": 10.5, "high": 10.6}
        self.assertFalse(_quote_is_limit_up("600000", q2))


if __name__ == "__main__":
    unittest.main()
