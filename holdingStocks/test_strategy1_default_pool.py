"""默认交易池切到策略一：买入/预警只认策略一，策略十六旧仓卖出后清空。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_config import (  # noqa: E402
    STRATEGY_ID,
    leftover_open_position_codes,
    portfolio_pool_codes,
    primary_watchlist,
    prune_portfolio_pool,
    strategy1_codes,
    strategy_watchlist_codes,
)
from watch_snapshot import filter_portfolio_holdings  # noqa: E402


def test_default_strategy_is_strategy1() -> None:
    assert STRATEGY_ID == "strategy1"
    codes = strategy_watchlist_codes()
    assert "002104" in codes
    assert "603301" in codes
    assert strategy1_codes() == codes


def test_leftover_strategy16_held_until_sold() -> None:
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
    assert leftover == {"002580"}
    primary = {str(w["code"]) for w in primary_watchlist(holdings)}
    assert "002580" in primary
    assert "002104" in primary
    pruned = prune_portfolio_pool(dict(holdings))
    assert "002580" in pruned


def test_leftover_strategy16_cleared_after_sell() -> None:
    holdings = {
        "portfolio_pool": ["002580", "002104"],
        "positions": {
            "002580": {"qty": 0, "cost": 18.5, "buy_time": "2026-10-20 09:31:00", "name": "圣阳股份"},
            "002104": {"qty": 0},
        },
        "realized_today": {},
        "closed_today": {},
    }
    assert leftover_open_position_codes(holdings) == set()
    pruned = prune_portfolio_pool(holdings)
    assert "002580" not in pruned
    assert "002104" in pruned
    codes = portfolio_pool_codes(holdings)
    assert "002580" not in codes
    assert "002104" in codes


def test_holdings_tab_alerts_only_strategy1() -> None:
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
    codes = [str(r["代码"]) for r in picked]
    assert codes == ["002104"]

    held = filter_portfolio_holdings(
        [rows[2]],
        portfolio_codes={"002580"},
        strategy_codes={"002104"},
        phase="continuous",
    )
    assert [str(r["代码"]) for r in held] == ["002580"]
    assert int(held[0].get("持仓") or 0) == 400


def test_watch_tabs_strategy1_then_strategy16() -> None:
    from index import _load_watch_strategy_tabs

    ids = [str(t["id"]) for t in _load_watch_strategy_tabs() if t.get("watch_tab")]
    assert ids[:3] == ["strategy1", "strategy16", "strategy16b"]
    assert ids == [
        "strategy1",
        "strategy16",
        "strategy16b",
        "strategy3",
        "strategy8",
        "strategy15",
        "strategy17",
    ]


if __name__ == "__main__":
    test_default_strategy_is_strategy1()
    test_leftover_strategy16_held_until_sold()
    test_leftover_strategy16_cleared_after_sell()
    test_holdings_tab_alerts_only_strategy1()
    test_watch_tabs_strategy1_then_strategy16()
    print("ok")
