"""策略一专属自选：海量数据只进策略一，不进公共自选 / 策略十六交易池。"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_watch_modules() -> tuple:
    try:
        from strategy.watch_universe import (  # type: ignore
            SELF_WATCHLIST_PICKS,
            STRATEGY1_SELF_WATCHLIST_PICKS,
            self_watchlist_codes,
            strategy1_self_watchlist_codes,
        )
        from watch_config import strategy16_watchlist, strategy1_watchlist
        from strategy_picks_loader import load_strategy_picks

        return (
            SELF_WATCHLIST_PICKS,
            STRATEGY1_SELF_WATCHLIST_PICKS,
            self_watchlist_codes,
            strategy1_self_watchlist_codes,
            strategy16_watchlist,
            strategy1_watchlist,
            load_strategy_picks,
        )
    except ModuleNotFoundError:
        sys.modules.pop("strategy", None)
        sys.modules.pop("strategy.akq_math", None)
        pkg = types.ModuleType("strategy")
        pkg.__path__ = [str(ROOT / "strategy")]
        pkg.__package__ = "strategy"
        sys.modules["strategy"] = pkg
        akq = types.ModuleType("strategy.akq_math")
        akq.session_day_pnl = lambda *args, **kwargs: 0.0  # noqa: ARG005
        sys.modules["strategy.akq_math"] = akq
        from strategy.watch_universe import (  # type: ignore
            SELF_WATCHLIST_PICKS,
            STRATEGY1_SELF_WATCHLIST_PICKS,
            self_watchlist_codes,
            strategy1_self_watchlist_codes,
        )
        from watch_config import strategy16_watchlist, strategy1_watchlist
        from strategy_picks_loader import load_strategy_picks

        return (
            SELF_WATCHLIST_PICKS,
            STRATEGY1_SELF_WATCHLIST_PICKS,
            self_watchlist_codes,
            strategy1_self_watchlist_codes,
            strategy16_watchlist,
            strategy1_watchlist,
            load_strategy_picks,
        )


(
    SELF_WATCHLIST_PICKS,
    STRATEGY1_SELF_WATCHLIST_PICKS,
    self_watchlist_codes,
    strategy1_self_watchlist_codes,
    strategy16_watchlist,
    strategy1_watchlist,
    load_strategy_picks,
) = _load_watch_modules()


HAILIANG = ("603138", "海量数据")


class TestStrategy1SelfWatch(unittest.TestCase):
    def test_hailiang_registered_as_strategy1_self_only(self) -> None:
        self.assertIn(HAILIANG, STRATEGY1_SELF_WATCHLIST_PICKS)
        self.assertNotIn(HAILIANG, SELF_WATCHLIST_PICKS)
        self.assertIn("603138", strategy1_self_watchlist_codes())
        self.assertNotIn("603138", self_watchlist_codes())

    def test_strategy1_watchlist_marks_hailiang_as_self(self) -> None:
        rows = {str(w["code"]): w for w in strategy1_watchlist({})}
        self.assertIn("603138", rows)
        item = rows["603138"]
        self.assertEqual(item.get("name"), "海量数据")
        self.assertEqual(item.get("pool_src"), "self")
        self.assertEqual(item.get("池来源"), "自选")
        self.assertEqual(item.get("self_scope"), "strategy1")
        self.assertTrue(item.get("self_watch"))

    def test_strategy16_watchlist_excludes_hailiang(self) -> None:
        codes = {str(w["code"]) for w in strategy16_watchlist({})}
        self.assertNotIn("603138", codes)

    def test_strategy1_picks_include_hailiang_self(self) -> None:
        s1 = load_strategy_picks("strategy1")
        s16 = load_strategy_picks("strategy16")
        s1_items = {str(it.get("code")): it for it in s1.get("items") or []}
        s16_items = {str(it.get("code")): it for it in s16.get("items") or []}
        self.assertIn("603138", s1_items)
        self.assertEqual(s1_items["603138"].get("分类"), "自选")
        self.assertEqual(s1_items["603138"].get("self_scope"), "strategy1")
        self.assertNotIn("603138", s16_items)
        self.assertIn("策略一自选", str(s1.get("note") or ""))


if __name__ == "__main__":
    unittest.main()
