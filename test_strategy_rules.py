"""OpenBreak3 核心规则的离线回归测试，不拉取行情、不运行完整回测。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import strategy.data as data
from strategy.open_break import (
    entry_filters_ok,
    has_double_yang_before,
    limit_down_state,
    should_block_entry_by_yang,
    strategy_levels,
    strategy_signal,
)


class StrategyRuleTests(unittest.TestCase):
    def test_trigger_prices_are_rounded_to_tick(self) -> None:
        levels = strategy_levels(15.05)
        self.assertEqual(levels["buy_trigger"], 15.43)
        self.assertEqual(levels["stop"], 14.67)

    def test_limit_up_open_cannot_buy(self) -> None:
        from strategy.open_break import cannot_buy_limit_up, limit_up_state

        locked = limit_up_state(
            prev_close=10.0, open_px=11.0, high_px=11.0, low_px=11.0, close_px=11.0
        )
        self.assertTrue(locked["locked"])
        self.assertTrue(locked["open_at_limit"])
        self.assertTrue(
            cannot_buy_limit_up(
                prev_close=10.0, open_px=11.0, high_px=11.0, low_px=11.0, close_px=11.0
            )
        )
        opened = limit_up_state(
            prev_close=10.0, open_px=10.2, high_px=11.0, low_px=10.1, close_px=10.8
        )
        self.assertFalse(opened["open_at_limit"])
        self.assertFalse(
            cannot_buy_limit_up(
                prev_close=10.0, open_px=10.2, high_px=11.0, low_px=10.1, close_px=10.8
            )
        )

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

    def test_double_yang_span_threshold_is_core_default(self) -> None:
        # 弱双阳：跨日 10→10.3 / 10.0 = 3% < 5% → 不禁
        self.assertFalse(
            has_double_yang_before(
                10.0, 10.2, 10.1, 10.3, combined_min_pct=0.05, combined_mode="span"
            )
        )
        self.assertFalse(
            should_block_entry_by_yang(10.0, 10.2, 10.1, 10.3)
        )
        # 前日小阳 + 弱双阳 → 默认可买
        self.assertTrue(
            entry_filters_ok(10.1, 10.3, 10.0, 10.2, entry_pct=0.025)
        )

        # 强双阳：跨日 10→10.6 = 6% ≥ 5% → 禁
        self.assertTrue(
            has_double_yang_before(
                10.0, 10.3, 10.2, 10.6, combined_min_pct=0.05, combined_mode="span"
            )
        )
        self.assertTrue(
            should_block_entry_by_yang(10.0, 10.3, 10.2, 10.6)
        )
        self.assertFalse(
            entry_filters_ok(10.2, 10.6, 10.0, 10.3, entry_pct=0.025)
        )

        # 显式关闭跨日门槛 → 任意双阳都禁（旧行为）
        self.assertTrue(
            should_block_entry_by_yang(
                10.0, 10.2, 10.1, 10.3, double_yang_combined_min_pct=None
            )
        )

    def test_factor2_dd_alert(self) -> None:
        from strategy import get_factor, get_strategy, get_strategy_bindings
        from strategy.dd_alert import derive_thresholds, evaluate_alert

        f2 = get_factor("factor2")
        self.assertTrue(f2.implemented)
        self.assertEqual(f2.meta.get("kind"), "dd_alert")
        self.assertFalse(f2.meta.get("overlay"))

        # 历史最大 26% → 加仓线 20%；年均值 19% → 减仓线 10%
        th = derive_thresholds(hist_max_dd=0.26, avg_yearly_max_dd=0.19)
        self.assertAlmostEqual(th.add_alert_dd, 0.20, places=4)
        self.assertAlmostEqual(th.reduce_alert_dd, 0.10, places=4)

        peak = 100_000.0
        # 浅回撤观望
        sig = evaluate_alert(equity=95_000, peak=peak, thresholds=th)
        self.assertEqual(sig["action"], "hold")
        # 触及加仓线
        sig = evaluate_alert(equity=80_000, peak=peak, thresholds=th)
        self.assertEqual(sig["action"], "add_alert")
        # 曾在加仓区，收窄到减仓线 → 减仓预警
        sig = evaluate_alert(
            equity=92_000, peak=peak, thresholds=th, in_add_zone=True
        )
        self.assertEqual(sig["action"], "reduce_alert")
        # 接近历史最大
        sig = evaluate_alert(equity=74_000, peak=peak, thresholds=th)
        self.assertEqual(sig["action"], "near_max")

        ids = {b.factor_id for b in get_strategy_bindings("strategy1")}
        self.assertEqual(ids, {"factor1", "factor2"})
        b2 = next(b for b in get_strategy_bindings("strategy1") if b.factor_id == "factor2")
        self.assertFalse(b2.params.get("overlay"))
        self.assertEqual(get_strategy("strategy1").name, "援军战法")
        self.assertEqual(get_strategy("援军战法").id, "strategy1")

    def test_strategy3_binds_factor5_as_event_universe(self) -> None:
        from strategy import get_strategy, get_strategy_bindings

        self.assertEqual(get_strategy("strategy3").id, "strategy3")
        bindings = {binding.factor_id: binding for binding in get_strategy_bindings("strategy3")}
        self.assertEqual(set(bindings), {"factor5"})
        factor5 = bindings["factor5"]
        self.assertEqual(factor5.role, "universe")
        self.assertEqual(factor5.params["lookback_days"], 0)
        self.assertEqual(factor5.params["max_candidates"], 5)
        self.assertEqual(factor5.params["max_per_theme"], 1)
        self.assertEqual(factor5.params["hold_days"], 5)


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


class Factor6HybridTests(unittest.TestCase):
    """因子6 组合动量 ETF；旧混合组合模拟仍可独立调用。现行策略六是因子12，与此无关。"""

    def test_factor6_decision_and_score(self) -> None:
        from strategy import (
            MarketContext,
            get_factor,
        )

        factor = get_factor("factor6")
        self.assertTrue(factor.implemented)
        self.assertEqual(factor.id, "factor6")
        self.assertEqual(factor.meta.get("kind"), "etf_combo_momentum")

        from strategy.strategies._unreg_s6.decision import create_decision_engine

        eng = create_decision_engine()
        hold = eng.decide(
            MarketContext(
                open=10.0,
                high=10.1,
                low=9.70,
                close=9.75,
                last=9.75,
                position_qty=100,
                available_qty=100,
                buy_time="2026-08-01 10:00:00",
                session="2026-08-04",
            )
        )
        self.assertEqual(hold.action, "hold")
        self.assertIn("因子6", hold.reason)

        buy = eng.decide(
            MarketContext(
                open=1.0,
                high=1.01,
                low=0.99,
                close=1.0,
                last=1.0,
                meta={"symbol": "sh510300", "target": ["sh510300"]},
            )
        )
        self.assertEqual(buy.action, "buy")
        self.assertEqual(buy.factor_id, "factor6")

        sell = eng.decide(
            MarketContext(
                open=1.0,
                high=1.01,
                low=0.99,
                close=1.0,
                last=1.0,
                position_qty=100,
                available_qty=100,
                buy_time="2026-08-01 10:00:00",
                session="2026-08-04",
                meta={"symbol": "sh510300", "target": []},
            )
        )
        self.assertEqual(sell.action, "sell")

    def test_combo_score_ranks_winner_and_cash_when_negative(self) -> None:
        from strategy.etf_combo_momentum import combo_momentum_score, daily_targets

        dates = pd.bdate_range("2024-01-02", periods=8)
        closes = pd.DataFrame(
            {
                "A": [100, 101, 103, 106, 110, 115, 121, 128],
                "B": [100, 99, 97, 94, 90, 85, 79, 72],
            },
            index=dates,
        )
        score = combo_momentum_score(closes, n=2, n2=3, w=1.0)
        last = score.iloc[-1]
        self.assertGreater(float(last["A"]), float(last["B"]))
        picks = daily_targets(score, top_k=1, min_score=0.0)
        self.assertEqual(picks[dates[-1]], ["A"])

        down = pd.DataFrame(
            {
                "A": [100, 99, 97, 94, 90, 85, 79, 72],
                "B": [100, 98, 95, 91, 86, 80, 73, 65],
            },
            index=dates,
        )
        empty = daily_targets(
            combo_momentum_score(down, n=2, n2=3, w=1.0),
            top_k=1,
            min_score=0.0,
        )
        self.assertEqual(empty[dates[-1]], [])

    def test_simulate_rotates_into_winner(self) -> None:
        from strategy.etf_combo_momentum import run_etf_combo_momentum

        dates = pd.bdate_range("2024-01-02", periods=12)
        a = 100 + pd.Series(range(12), index=dates).astype(float)
        b = 100 - pd.Series(range(12), index=dates).astype(float)
        dailies = {
            "A": pd.DataFrame(
                {
                    "date": dates,
                    "open": a.to_numpy(),
                    "high": a.to_numpy(),
                    "low": a.to_numpy(),
                    "close": a.to_numpy(),
                    "volume": 1.0,
                    "symbol": "A",
                }
            ),
            "B": pd.DataFrame(
                {
                    "date": dates,
                    "open": b.to_numpy(),
                    "high": b.to_numpy(),
                    "low": b.to_numpy(),
                    "close": b.to_numpy(),
                    "volume": 1.0,
                    "symbol": "B",
                }
            ),
        }
        result = run_etf_combo_momentum(
            n=2,
            n2=3,
            w=1.0,
            top_k=1,
            hold_days=3,
            min_score=0.0,
            start="20240105",
            universe=(("A", "强势"), ("B", "弱势")),
            dailies=dailies,
            initial_cash=100_000.0,
            verbose=False,
        )
        self.assertGreaterEqual(int(result.stats["n_buys"]), 1)
        buys = result.trades[result.trades["side"] == "buy"]
        self.assertTrue((buys["symbol"] == "A").all())

    def test_simulate_stop_exits_before_hold_days(self) -> None:
        from strategy.strategies._unreg_s6.portfolio import simulate_f3_select_f1_stop

        dates = pd.date_range("2024-01-02", periods=6, freq="B")
        opens = pd.DataFrame({"sA": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]}, index=dates)
        highs = opens.copy()
        lows = pd.DataFrame({"sA": [9.8, 9.8, 9.70, 9.8, 9.8, 9.8]}, index=dates)
        closes = opens.copy()
        factor = pd.DataFrame({"sA": [1.0] * 6}, index=dates)
        picks = {dates[0]: ["sA"]}

        eq, tr, stats = simulate_f3_select_f1_stop(
            factor=factor,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            picks=picks,
            bt_start=dates[0],
            hold_days=3,
            top_k=1,
            stop_pct=0.025,
            initial_cash=100_000.0,
            factor_label="test",
        )
        self.assertFalse(eq.empty)
        self.assertGreaterEqual(int(stats["n_buys"]), 1)
        self.assertGreaterEqual(int(stats["n_stop_exits"]), 1)
        sells = tr[tr["side"] == "sell"]
        self.assertTrue((sells["reason"] == "stop").any())

    def test_simulate_stop_exits_before_hold_days(self) -> None:
        from strategy.strategies._unreg_s6.portfolio import simulate_f3_select_f1_stop

        dates = pd.date_range("2024-01-02", periods=6, freq="B")
        # 构造：D0 信号 → D1 买 @10；D2 开盘10、低点跌破止损
        opens = pd.DataFrame({"sA": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]}, index=dates)
        highs = opens.copy()
        lows = pd.DataFrame({"sA": [9.8, 9.8, 9.70, 9.8, 9.8, 9.8]}, index=dates)
        closes = opens.copy()
        factor = pd.DataFrame({"sA": [1.0] * 6}, index=dates)
        picks = {dates[0]: ["sA"]}  # D0 收盘选中 → D1 开盘买

        eq, tr, stats = simulate_f3_select_f1_stop(
            factor=factor,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            picks=picks,
            bt_start=dates[0],
            hold_days=3,
            top_k=1,
            stop_pct=0.025,
            initial_cash=100_000.0,
            factor_label="test",
        )
        self.assertFalse(eq.empty)
        self.assertGreaterEqual(int(stats["n_buys"]), 1)
        self.assertGreaterEqual(int(stats["n_stop_exits"]), 1)
        sells = tr[tr["side"] == "sell"]
        self.assertTrue((sells["reason"] == "stop").any())


class Strategy3SlotBindingTests(unittest.TestCase):
    def test_strategy3_binds_fixed_hold_event_universe(self) -> None:
        from strategy import get_strategy, get_strategy_bindings

        strategy = get_strategy("strategy3")
        bindings = get_strategy_bindings("strategy3")
        self.assertEqual(strategy.id, "strategy3")
        self.assertEqual(strategy.factor_ids, ("factor5",))
        by_id = {binding.factor_id: binding for binding in bindings}
        self.assertEqual(by_id["factor5"].role, "universe")
        self.assertEqual(by_id["factor5"].params["max_positions"], 5)
        self.assertEqual(by_id["factor5"].params["max_per_theme"], 1)
        self.assertEqual(by_id["factor5"].params["hold_days"], 5)


if __name__ == "__main__":
    unittest.main()
