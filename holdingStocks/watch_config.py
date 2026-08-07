"""盯盘标的池与代码工具（唯一真源；index 从此处导入）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from strategy.open_break import DEFAULT_PCT, TICK_SIZE, is_t1_buy_day

# 默认定盘：策略一 + 因子1（开盘±2.5%）；与 strategy 注册表一致
STRATEGY_ID = "strategy1"
FACTOR_ID = "factor1"
STRATEGY_NAME = "策略一·因子1"

# 中证500+1000 契合池（夏普≥1 且策略超额>0，按夏普降序）
# 明细：../backtest/universe_zz500_1000/fit_sharpe1_excess.csv
# 改盯盘池：只改这里（勿在 index.py 再维护一份）
_FIT_WATCH: list[tuple[str, str]] = [
    ("001389", "广合科技"),
    ("600552", "凯盛科技"),
    ("603083", "剑桥科技"),
    ("601208", "东材科技"),
    ("603306", "华懋科技"),
    ("002335", "科华数据"),
    ("001339", "智微智能"),
    ("002636", "金安国纪"),
    ("600105", "永鼎股份"),
    ("000880", "潍柴重机"),
    ("600330", "天通股份"),
]

# 竞价结束后强制刷新盯盘开盘价
OPEN_PRICE_REFRESH_HOUR = 9
OPEN_PRICE_REFRESH_MINUTE = 26

INDEX_WATCH: list[dict[str, str]] = [
    {"code": "sh000001", "name": "上证指数", "market": "上证"},
    {"code": "sz399001", "name": "深证成指", "market": "深证"},
]


def code_key(code: str) -> str:
    return "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]


def sina_of(code: str) -> str:
    c = code_key(code)
    return f"sh{c}" if c.startswith(("5", "6")) else f"sz{c}"


def market_of(code: str) -> str:
    return "上证" if sina_of(code).startswith("sh") else "深证"


def watch_item(
    code: str,
    name: str,
    *,
    pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
    t0: bool = False,
    limit_down_pct: float = 0.10,
    prev_entry_mode: str = "yin_or_small_yang",
) -> dict[str, Any]:
    c = code_key(code)
    return {
        "code": c,
        "sina": sina_of(c),
        "market": market_of(c),
        "name": name,
        "pct": float(pct),
        "tick": float(tick),
        "t0": bool(t0),
        "limit_down_pct": float(limit_down_pct),
        "prev_entry_mode": prev_entry_mode,
    }


WATCHLIST: list[dict[str, Any]] = [watch_item(c, n) for c, n in _FIT_WATCH]


def empty_position(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": meta["name"],
        "market": meta["market"],
        "qty": 0,
        "available": None,
        "cost": None,
        "today_cost": None,
        "buy_time": None,
        "note": "",
    }


def sellable_qty(
    pos: dict[str, Any],
    qty: int,
    buy_time: str | None,
    session: str,
    *,
    t0: bool = False,
) -> int:
    """可卖数量。

    - T+0：整仓可卖
    - 买入当日（T+1）：以 available 为准（通常 0）；未填则整仓不可卖
    - 非买入日（隔夜仓）：available>0 取其与 qty 较小值；
      available 缺失或为 0 视为未维护，回退整仓可卖（避免卡死止损结算）
    """
    if qty <= 0:
        return 0
    if t0:
        return int(qty)
    t1 = is_t1_buy_day(buy_time, session)
    raw = pos.get("available")
    try:
        avail = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        avail = None

    if t1:
        if avail is None:
            return 0
        return max(0, min(avail, int(qty)))

    if avail is not None and avail > 0:
        return max(0, min(avail, int(qty)))
    return int(qty)


def calc_day_pnl(
    *,
    last: float,
    qty: int,
    available: int,
    cost: float | None,
    prev_close: float | None,
    open_px: float,
    today_cost: float | None = None,
    buy_time: str | None = None,
    session: str | None = None,
    t0: bool = False,
) -> tuple[float | None, float | None, float | None]:
    """当日盈亏 = 现价盯市盈亏。

    - 隔夜仓：全仓 (现价 − 昨收) × qty
    - 今日买入：今买部分 (现价 − 今日成交价)；若仍有隔夜可用则按昨收
    """
    if qty <= 0:
        return None, None, None
    last = float(last)
    open_px = float(open_px)
    cost_f = float(cost) if cost is not None else None
    today_f = float(today_cost) if today_cost is not None else None
    prev = float(prev_close) if prev_close is not None and float(prev_close) > 0 else None
    bought_today = (not t0) and bool(session) and is_t1_buy_day(buy_time, str(session))

    if not bought_today:
        base = prev if prev is not None else open_px
        day_pnl = (last - base) * int(qty)
        day_base = base * int(qty)
        if day_base <= 0:
            return round(day_pnl, 2), None, None
        return (
            round(day_pnl, 2),
            round(day_pnl / day_base * 100.0, 2),
            round(day_base, 2),
        )

    avail = max(0, min(int(available), int(qty)))
    locked = int(qty) - avail
    day_pnl = 0.0
    day_base = 0.0
    if avail > 0:
        base_ov = prev if prev is not None else open_px
        day_pnl += (last - base_ov) * avail
        day_base += base_ov * avail
    if locked > 0:
        base_td = (
            today_f
            if today_f is not None
            else (cost_f if cost_f is not None else open_px)
        )
        day_pnl += (last - base_td) * locked
        day_base += base_td * locked
    if day_base <= 0:
        return round(day_pnl, 2), None, None
    return round(day_pnl, 2), round(day_pnl / day_base * 100.0, 2), round(day_base, 2)


def find_meta(code: str, watchlist: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    key = code_key(code)
    items = watchlist if watchlist is not None else WATCHLIST
    for item in items:
        if item["code"] == key:
            return item
    codes = "/".join(w["code"] for w in items)
    raise KeyError(f"不在监控列表: {code}（仅支持 {codes}）")


def watchlist_codes_label(watchlist: list[dict[str, Any]] | None = None) -> str:
    items = watchlist if watchlist is not None else WATCHLIST
    return " / ".join(w["code"] for w in items)
