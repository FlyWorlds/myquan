"""OpenBreak3 核心规则的离线回归测试，不拉取行情、不运行完整回测。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import strategy.data as data
from strategy.open_break import (
    limit_down_state,
    strategy_levels,
    strategy_signal,
)


class StrategyRuleTests(unittest.TestCase):
    def test_trigger_prices_are_rounded_to_tick(self) -> None:
        levels = strategy_levels(15.05)
        self.assertEqual(levels["buy_trigger"], 15.43)
        self.assertEqual(levels["stop"], 14.67)

    def test_t1_buy_day_never_emits_sell_signal(self) -> None:
        signal = strategy_signal(
            open_px=15.05,
            high_px=15.50,
            low_px=14.60,
            last_px=14.70,
            session="2026-08-04",
            buy_trigger=15.43,
            stop_px=14.67,
            qty=100,
            buy_time="2026-08-04 10:00:00",
            vs_open_pts=-0.35,
        )
        self.assertTrue(signal["t1_lock"])
        self.assertFalse(signal["pending_sell"])
        self.assertFalse(signal["actionable"])
        self.assertEqual(signal["alert"], "持有·T+1")

    def test_limit_down_locked_and_opened_states(self) -> None:
        locked = limit_down_state(
            prev_close=10.0,
            open_px=9.0,
            high_px=9.0,
            low_px=9.0,
            close_px=9.0,
        )
        self.assertTrue(locked["locked"])
        self.assertFalse(locked["opened"])

        opened = limit_down_state(
            prev_close=10.0,
            open_px=9.0,
            high_px=9.30,
            low_px=9.0,
            close_px=9.20,
        )
        self.assertFalse(opened["locked"])
        self.assertTrue(opened["opened"])
        self.assertEqual(opened["limit_px"], 9.0)


class DailyCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._remote = data._fetch_daily_remote
        self.calls: list[tuple[str, str, str]] = []

        def fake_remote(symbol: str, start: str, end: str) -> pd.DataFrame:
            self.calls.append((symbol, start, end))
            days = pd.date_range(start, end, freq="D")
            return pd.DataFrame(
                {
                    "date": (days + pd.Timedelta(hours=15)).tz_localize(
                        "Asia/Shanghai"
                    ),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.0,
                    "volume": 100.0,
                    "symbol": symbol,
                }
            )

        data._fetch_daily_remote = fake_remote

    def tearDown(self) -> None:
        data._fetch_daily_remote = self._remote

    def test_cache_writes_hits_and_only_fetches_new_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "sh600552_daily_qfq.parquet"
            first = data.fetch_daily(
                "sh600552", "20240101", "20240103", cache_path=cache
            )
            second = data.fetch_daily(
                "sh600552", "20240102", "20240103", cache_path=cache
            )
            third = data.fetch_daily(
                "sh600552", "20240102", "20240104", cache_path=cache
            )
            self.assertTrue(cache.exists())

        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 2)
        self.assertEqual(len(third), 3)
        self.assertEqual(
            self.calls,
            [
                ("sh600552", "20240101", "20240103"),
                ("sh600552", "20240104", "20240104"),
            ],
        )

    def test_wrong_symbol_in_cache_forces_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "bad.parquet"
            bad = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize(
                        "Asia/Shanghai"
                    )
                    + pd.Timedelta(hours=15),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 1.0,
                    "symbol": "sh999999",
                }
            )
            bad.to_parquet(cache, index=False)
            data.fetch_daily(
                "sh600552", "20240101", "20240102", cache_path=cache
            )
        self.assertEqual(self.calls[0][0], "sh600552")
        self.assertEqual(self.calls[0][1:], ("20240101", "20240102"))

    def test_suspicious_gap_forces_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "gap.parquet"
            gapped = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2024-01-01", "2024-03-01"]).tz_localize(
                        "Asia/Shanghai"
                    )
                    + pd.Timedelta(hours=15),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 1.0,
                    "symbol": "sh600552",
                }
            )
            gapped.to_parquet(cache, index=False)
            out = data.fetch_daily(
                "sh600552", "20240101", "20240105", cache_path=cache
            )
        self.assertGreaterEqual(len(out), 1)
        self.assertTrue(any(c[1] == "20240101" for c in self.calls))

    def test_stock_daily_failure_is_explicit(self) -> None:
        with mock.patch.object(
            data.ak,
            "stock_zh_a_daily",
            side_effect=ConnectionError("source unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "AkShare 个股日线拉取失败"):
                self._remote("sh600552", "20240101", "20240103")

    def test_etf_uses_fund_api(self) -> None:
        self.assertTrue(data._is_etf_symbol("sh510580"))
        self.assertFalse(data._is_etf_symbol("sh600552"))
        data._fetch_daily_remote = self._remote
        with mock.patch.object(
            data.ak,
            "fund_etf_hist_em",
            side_effect=ConnectionError("etf down"),
        ):
            with self.assertRaisesRegex(RuntimeError, "AkShare ETF 日线拉取失败"):
                data._fetch_daily_remote("sh510580", "20240101", "20240103")


class StrategyInstanceTests(unittest.TestCase):
    def test_apply_config_writes_instance_not_class(self) -> None:
        from strategy.config import BacktestConfig, KAICHENG
        from strategy.backtest import OpenBreak3Strategy
        from strategy.runner import apply_strategy_config, build_open_break_strategy

        class_default = OpenBreak3Strategy.symbol
        a = build_open_break_strategy(KAICHENG)
        other = OpenBreak3Strategy()
        apply_strategy_config(
            other,
            BacktestConfig(
                symbol="sh600879",
                symbol_name="航天电子",
                em_symbol="600879",
            ),
        )
        self.assertEqual(a.symbol, "sh600552")
        self.assertEqual(other.symbol, "sh600879")
        self.assertEqual(OpenBreak3Strategy.symbol, class_default)


if __name__ == "__main__":
    unittest.main()
