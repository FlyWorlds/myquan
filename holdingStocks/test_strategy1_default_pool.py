"""默认交易池切到策略一：买入/预警只认策略一，策略十六旧仓卖出后清空。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_config import (  # noqa: E402
    QUOTE_DRIVEN_ENABLED,
    STRATEGY_ID,
    factor29_auction_enabled,
    leftover_open_position_codes,
    portfolio_pool_codes,
    primary_watchlist,
    prune_portfolio_pool,
    quote_driven_enabled,
    strategy1_codes,
    strategy_watchlist_codes,
)
from watch_snapshot import filter_portfolio_holdings  # noqa: E402


class TestStrategy1DefaultPool(unittest.TestCase):
    def test_default_strategy_is_strategy1(self) -> None:
        self.assertEqual(STRATEGY_ID, "strategy1")
        codes = strategy_watchlist_codes()
        self.assertIn("002104", codes)
        self.assertIn("603301", codes)
        self.assertEqual(strategy1_codes(), codes)

    def test_leftover_strategy16_held_until_sold(self) -> None:
        holdings = {
            "portfolio_pool": ["002580", "002104"],
            "positions": {
                "002580": {"qty": 400, "cost": 18.5, "buy_time": "2026-10-20 09:31:00", "name": "圣阳股份"},
                "002104": {"qty": 200, "cost": 10.0},
            },
            "realized_today": {},
            "closed_today": {},
        }
        leftover = leftover_open_position_codes(holdings)
        self.assertEqual(leftover, {"002580"})
        primary = {str(w["code"]) for w in primary_watchlist(holdings)}
        self.assertIn("002580", primary)
        self.assertIn("002104", primary)
        pruned = prune_portfolio_pool(dict(holdings))
        self.assertIn("002580", pruned)

    def test_leftover_strategy16_cleared_after_sell(self) -> None:
        holdings = {
            "portfolio_pool": ["002580", "002104"],
            "positions": {
                "002580": {"qty": 0, "cost": 18.5, "buy_time": "2026-10-20 09:31:00", "name": "圣阳股份"},
                "002104": {"qty": 0},
            },
            "realized_today": {},
            "closed_today": {},
        }
        self.assertEqual(leftover_open_position_codes(holdings), set())
        pruned = prune_portfolio_pool(holdings)
        self.assertNotIn("002580", pruned)
        self.assertIn("002104", pruned)
        codes = portfolio_pool_codes(holdings)
        self.assertNotIn("002580", codes)
        self.assertIn("002104", codes)

    def test_holdings_tab_alerts_only_strategy1(self) -> None:
        rows = [
            {
                "代码": "002104",
                "名称": "恒宝",
                "持仓": 0,
                "持仓状态": "待买入",
                "预警": "将买入",
                "近买点": True,
                "距买点%": 0.4,
            },
            {
                "代码": "002580",
                "名称": "圣阳",
                "持仓": 0,
                "持仓状态": "待买入",
                "预警": "将买入",
                "近买点": True,
                "距买点%": 0.2,
            },
            {
                "代码": "002580",
                "名称": "圣阳持仓",
                "持仓": 400,
                "持仓状态": "已经买入",
                "距买点%": 1.0,
            },
        ]
        picked = filter_portfolio_holdings(
            [
                rows[0],
                {
                    "代码": "002580",
                    "名称": "圣阳",
                    "持仓": 0,
                    "持仓状态": "待买入",
                    "预警": "将买入",
                    "近买点": True,
                    "距买点%": 0.2,
                },
            ],
            portfolio_codes={"002104", "002580"},
            strategy_codes={"002104"},
            phase="continuous",
        )
        self.assertEqual([str(r["代码"]) for r in picked], ["002104"])

        held = filter_portfolio_holdings(
            [rows[2]],
            portfolio_codes={"002580"},
            strategy_codes={"002104"},
            phase="continuous",
        )
        self.assertEqual([str(r["代码"]) for r in held], ["002580"])
        self.assertEqual(int(held[0].get("持仓") or 0), 400)

    def test_quote_driven_and_factor29_on_strategy1(self) -> None:
        self.assertEqual(STRATEGY_ID, "strategy1")
        self.assertTrue(QUOTE_DRIVEN_ENABLED)
        self.assertTrue(quote_driven_enabled())
        self.assertTrue(factor29_auction_enabled())
        from condition_buy import make_order
        from strategy.registry import get_strategy_bindings

        ids = {b.factor_id for b in get_strategy_bindings("strategy1") if b.enabled}
        self.assertIn("factor29", ids)
        rec = make_order(
            code="002104",
            session="2026-10-28",
            open_px=10.0,
            price=10.25,
            entry_pct=0.025,
            tick=0.01,
            armed_at="2026-10-28 09:25:01",
            quote_at="2026-10-28 09:25:00",
            name="恒宝",
            market="SZ",
        )
        self.assertEqual(rec["strategy"], "strategy1")
        self.assertEqual(rec["kind"], "breakout")

    def test_watch_tabs_strategy1_then_strategy16(self) -> None:
        from index import _load_watch_strategy_tabs

        ids = [str(t["id"]) for t in _load_watch_strategy_tabs() if t.get("watch_tab")]
        self.assertEqual(ids[:3], ["strategy1", "strategy16", "strategy16b"])
        self.assertEqual(
            ids,
            [
                "strategy1",
                "strategy16",
                "strategy16b",
                "strategy3",
                "strategy8",
                "strategy15",
            ],
        )
        self.assertNotIn("strategy17", ids)


if __name__ == "__main__":
    unittest.main()
