"""策略七五槽位、事件补仓与因子1止损的确定性测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from strategy.strategies.strategy7.portfolio import simulate_factor5_event_slots_f1_stop


def _panel(
    *,
    low_overrides: dict[tuple[int, str], float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-01-05", periods=5, freq="B")
    columns = ["A", "B", "C", "D", "E", "F"]
    opens = pd.DataFrame(10.0, index=dates, columns=columns)
    lows = pd.DataFrame(10.0, index=dates, columns=columns)
    closes = pd.DataFrame(10.0, index=dates, columns=columns)
    for (index, symbol), value in (low_overrides or {}).items():
        lows.iloc[index, lows.columns.get_loc(symbol)] = value
    return opens, lows, closes


class Strategy7SlotTests(unittest.TestCase):
    def test_event_candidates_leave_unfilled_slots_as_cash(self) -> None:
        opens, lows, closes = _panel()
        dates = opens.index
        equity, trades, slots, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={dates[0]: ["A", "B"]},
            bt_start=dates[0],
            max_positions=5,
            initial_cash=100_000,
        )
        buys = trades[trades["side"] == "buy"]
        self.assertEqual(len(buys), 2)
        self.assertTrue((slots["occupied_slots"] <= 2).all())
        self.assertEqual(int(slots.iloc[-1]["empty_slots"]), 3)
        self.assertEqual(stats["n_event_entries"], 2)
        self.assertGreater(float(equity.iloc[-1]["cash"]), 0)

    def test_factor1_stop_releases_slot_then_daily_pool_refills(self) -> None:
        # A、B 先建仓；A 在第3日触发因子1止损，C 作为同一事件池未买入候选，
        # 于下一交易日按时间驱动补入。
        opens, lows, closes = _panel(low_overrides={(2, "A"): 9.0})
        dates = opens.index
        _, trades, slots, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={dates[0]: ["A", "B", "C"]},
            bt_start=dates[0],
            max_positions=2,
            initial_cash=100_000,
        )
        self.assertEqual(stats["n_factor1_stops"], 1)
        self.assertTrue(
            ((trades["symbol"] == "A") & (trades["reason"] == "factor1_stop")).any()
        )
        c_buy = trades[(trades["symbol"] == "C") & (trades["side"] == "buy")]
        self.assertEqual(c_buy.iloc[0]["reason"], "daily_replenish")
        self.assertEqual(int(slots.iloc[-1]["occupied_slots"]), 2)

    def test_new_event_refills_stop_slot_and_tplus_one_blocks_same_day_sale(self) -> None:
        # A 在买入日低点跌破也不得卖出（T+1）；次日止损后，C 的新事件在再下一
        # 个交易日开盘优先补入。
        opens, lows, closes = _panel(low_overrides={(1, "A"): 9.0, (2, "A"): 9.0})
        dates = opens.index
        _, trades, _, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={dates[0]: ["A"], dates[2]: ["C"]},
            bt_start=dates[0],
            max_positions=1,
            initial_cash=100_000,
        )
        a_sells = trades[(trades["symbol"] == "A") & (trades["side"] == "sell")]
        self.assertEqual(a_sells.iloc[0]["date"], dates[2])
        c_buy = trades[(trades["symbol"] == "C") & (trades["side"] == "buy")]
        self.assertEqual(c_buy.iloc[0]["date"], dates[3])
        self.assertEqual(c_buy.iloc[0]["reason"], "event_entry")
        self.assertEqual(stats["n_event_entries"], 2)

    def test_no_event_keeps_all_slots_empty(self) -> None:
        opens, lows, closes = _panel()
        dates = opens.index
        equity, trades, slots, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={},
            bt_start=dates[0],
            max_positions=5,
            initial_cash=100_000,
        )
        self.assertTrue(trades.empty)
        self.assertTrue((slots["occupied_slots"] == 0).all())
        self.assertEqual(stats["n_buys"], 0)
        self.assertTrue((equity["cash"] == 100_000).all())

    def test_fixed_hold_exits_without_factor1_stop(self) -> None:
        opens, lows, closes = _panel()
        dates = opens.index
        _, trades, _, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={dates[0]: ["A"]},
            bt_start=dates[0],
            max_positions=1,
            use_factor1_stop=False,
            hold_days=2,
            initial_cash=100_000,
        )
        sell = trades[trades["side"] == "sell"].iloc[0]
        self.assertEqual(sell["reason"], "time_exit")
        self.assertEqual(sell["date"], dates[3])
        self.assertEqual(stats["n_factor1_stops"], 0)
        self.assertEqual(stats["n_time_exits"], 1)

    def test_new_theme_replaces_oldest_when_slots_full(self) -> None:
        opens, lows, closes = _panel()
        dates = opens.index
        _, trades, _, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={dates[0]: ["A"], dates[1]: ["B"]},
            bt_start=dates[0],
            max_positions=1,
            use_factor1_stop=False,
            hold_days=10,
            code_themes={"A": "memory", "B": "power"},
            initial_cash=100_000,
        )
        replacement = trades[(trades["symbol"] == "A") & (trades["side"] == "sell")].iloc[0]
        b_buy = trades[(trades["symbol"] == "B") & (trades["side"] == "buy")].iloc[0]
        self.assertEqual(replacement["reason"], "new_theme_replace")
        self.assertEqual(replacement["date"], dates[2])
        self.assertEqual(b_buy["date"], dates[2])
        self.assertEqual(stats["n_replacements"], 1)

    def test_same_theme_event_replaces_previous_theme_holding(self) -> None:
        opens, lows, closes = _panel()
        dates = opens.index
        _, trades, _, stats = simulate_factor5_event_slots_f1_stop(
            opens=opens,
            lows=lows,
            closes=closes,
            picks={dates[0]: ["A"], dates[1]: ["B"]},
            bt_start=dates[0],
            max_positions=2,
            use_factor1_stop=False,
            hold_days=10,
            code_themes={"A": "memory", "B": "memory"},
            initial_cash=100_000,
        )
        replacement = trades[(trades["symbol"] == "A") & (trades["side"] == "sell")].iloc[0]
        self.assertEqual(replacement["reason"], "concept_replace")
        self.assertTrue(((trades["symbol"] == "B") & (trades["side"] == "buy")).any())
        self.assertEqual(stats["n_replacements"], 1)


if __name__ == "__main__":
    unittest.main()
