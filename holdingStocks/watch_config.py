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

# 中证500+1000 契合池（夏普≥1.0 且超额>0，剔科创；多阈值优选，按夏普降序）
# 明细：../backtest/universe_zz500_1000/fit_sharpe1_excess.csv / multi_pct_excess.csv
# 改盯盘池：只改这里（勿在 index.py 再维护一份）
# 标的专属阈值：未列出的用 DEFAULT_PCT（±2.5%）；见 multi_pct 优选结果
_FIT_WATCH: list[tuple[str, str]] = [
    ("301600", "慧翰股份"),
    ("001389", "广合科技"),
    ("002290", "禾盛新材"),
    ("301392", "汇成真空"),
    ("301205", "联特科技"),
    ("600552", "凯盛科技"),
    ("601208", "东材科技"),
    ("301550", "斯菱智驱"),
    ("002636", "金安国纪"),
    ("301678", "新恒汇"),
    ("600105", "永鼎股份"),
    ("603083", "剑桥科技"),
    ("001339", "智微智能"),
    ("600330", "天通股份"),
    ("600206", "有研新材"),
    ("002979", "雷赛智能"),
    ("301389", "隆扬电子"),
    ("002378", "章源钨业"),
    ("002738", "中矿资源"),
    ("603119", "浙江荣泰"),
    ("603306", "华懋科技"),
    ("601020", "华钰矿业"),
    ("301458", "钧崴电子"),
    ("002335", "科华数据"),
    ("002747", "埃斯顿"),
]

# 个股覆盖默认开盘±pct（未列出的用 DEFAULT_PCT）
_WATCH_PCT: dict[str, float] = {
    "002290": 0.03,  # ±3.0%
    "002636": 0.03,  # ±3.0%
    "002738": 0.03,  # ±3.0%
    "002747": 0.03,  # ±3.0%
    "002979": 0.03,  # ±3.0%
    "301389": 0.03,  # ±3.0%
    "301458": 0.03,  # ±3.0%
    "301550": 0.03,  # ±3.0%
    "301600": 0.03,  # ±3.0%
    "600105": 0.03,  # ±3.0%
    "600206": 0.03,  # ±3.0%
    "600330": 0.03,  # ±3.0%
    "601020": 0.03,  # ±3.0%
    "603119": 0.03,  # ±3.0%
    "002378": 0.02,  # ±2.0%
    "301678": 0.02,  # ±2.0%
    "603083": 0.02,  # ±2.0%
}

# 集合竞价 09:15–09:30：盘面价无连续交易意义，此间不触发买卖/止损结算/微信预警
AUCTION_START_HOUR = 9
AUCTION_START_MINUTE = 15
# 连续竞价开始后方可触发因子信号
SIGNAL_ACTIVE_HOUR = 9
SIGNAL_ACTIVE_MINUTE = 30

# 开盘价强制刷新（连续竞价开始，避开竞价脏价）
OPEN_PRICE_REFRESH_HOUR = 9
OPEN_PRICE_REFRESH_MINUTE = 30

INDEX_WATCH: list[dict[str, str]] = [
    {"code": "sh000001", "name": "上证指数", "market": "上证"},
    {"code": "sz399001", "name": "深证成指", "market": "深证"},
]


def is_signal_window(now: Any | None = None) -> bool:
    """连续竞价开始后才允许因子触发/止损结算/微信预警。

    09:15–09:30 集合竞价盘面价无连续交易意义，此间返回 False。
    """
    from datetime import datetime as _dt

    ts = now if isinstance(now, _dt) else _dt.now()
    return (int(ts.hour) * 60 + int(ts.minute)) >= (
        SIGNAL_ACTIVE_HOUR * 60 + SIGNAL_ACTIVE_MINUTE
    )


def is_auction_window(now: Any | None = None) -> bool:
    """是否处于集合竞价时段 09:15–09:30（不含 09:30）。"""
    from datetime import datetime as _dt

    ts = now if isinstance(now, _dt) else _dt.now()
    t = int(ts.hour) * 60 + int(ts.minute)
    start = AUCTION_START_HOUR * 60 + AUCTION_START_MINUTE
    end = SIGNAL_ACTIVE_HOUR * 60 + SIGNAL_ACTIVE_MINUTE
    return start <= t < end


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


def limit_down_pct_of(code: str) -> float:
    """主板约10%；创业板/科创板约20%。"""
    c = code_key(code)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


WATCHLIST: list[dict[str, Any]] = [
    watch_item(
        c,
        n,
        pct=_WATCH_PCT.get(code_key(c), DEFAULT_PCT),
        limit_down_pct=limit_down_pct_of(c),
    )
    for c, n in _FIT_WATCH
]


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
