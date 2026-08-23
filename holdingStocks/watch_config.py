"""盯盘标的池与代码工具（唯一真源；index 从此处导入）。

当前锁定：**策略一 = 因子1 + 因子2（回撤预警）**。
定案宇宙：凯盛 / 天通 / 科创综指 **置顶** + 中证拟合池其余。
策略三（旧号策略七）三票完整配置保留为 S7_WATCHLIST（含因子4）；改 STRATEGY_ID / USE_FACTOR4 / WATCHLIST 可切换。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from strategy.open_break import DEFAULT_PCT, TICK_SIZE, is_t1_buy_day

# 默认定盘：策略一 + 因子1/因子2
STRATEGY_ID = "strategy1"
FACTOR_ID = "factor1"
FACTOR2_ID = "factor2"
FACTOR4_ID = "factor4"
STRATEGY_NAME = "策略一·因子1+因子2"
# 策略三（旧号策略七）才叠因子4；策略一关闭
USE_FACTOR4 = False

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
    entry_pct: float | None = None,
    stop_pct: float | None = None,
    tick: float = TICK_SIZE,
    t0: bool = False,
    limit_down_pct: float = 0.10,
    prev_entry_mode: str = "yin_or_small_yang",
    factor4_kind: str | None = None,
    factor4_params: dict[str, Any] | None = None,
    factor4_stop_widen_mult: float | None = None,
) -> dict[str, Any]:
    c = code_key(code)
    ep = float(entry_pct if entry_pct is not None else pct)
    sp = float(stop_pct if stop_pct is not None else pct)
    item: dict[str, Any] = {
        "code": c,
        "sina": sina_of(c),
        "market": market_of(c),
        "name": name,
        "pct": ep,  # 兼容旧字段=入场阈值
        "entry_pct": ep,
        "stop_pct": sp,
        "tick": float(tick),
        "t0": bool(t0),
        "limit_down_pct": float(limit_down_pct),
        "prev_entry_mode": prev_entry_mode,
    }
    if factor4_kind is not None:
        item["factor4_kind"] = factor4_kind
    if factor4_params is not None:
        item["factor4_params"] = dict(factor4_params)
    if factor4_stop_widen_mult is not None:
        item["factor4_stop_widen_mult"] = float(factor4_stop_widen_mult)
    return item


def limit_down_pct_of(code: str) -> float:
    """主板约10%；创业板/科创板约20%；ETF 约10%。涨停幅度相同。"""
    c = code_key(code)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


limit_up_pct_of = limit_down_pct_of


# ---------------------------------------------------------------------------
# 策略三默认宇宙（与 strategy.config / 旧 strategy7.default_s7_universe 对齐）
# ---------------------------------------------------------------------------
S7_WATCHLIST: list[dict[str, Any]] = [
    watch_item(
        "600552",
        "凯盛科技",
        pct=0.025,
        factor4_kind="roc",
        factor4_params={"n": 60, "enter_raw": 0.10, "exit_raw": 0.02},
        factor4_stop_widen_mult=1.5,
    ),
    watch_item(
        "600330",
        "天通股份",
        pct=0.03,
        factor4_kind="roc_ma",
        factor4_params={"n": 40, "ma_n": 60, "enter_raw": 0.0, "exit_raw": 0.0},
        factor4_stop_widen_mult=1.3,  # 牛市止损≈3.9%，避免原2x→6%过大
    ),
    watch_item(
        "589680",
        "科创综指ETF鹏华",
        entry_pct=0.025,
        stop_pct=0.035,
        tick=0.001,
        t0=False,
        limit_down_pct=0.10,
        factor4_kind="roc_ma",
        factor4_params={"n": 60, "ma_n": 60},
        factor4_stop_widen_mult=2.0,
    ),
]

# ---------------------------------------------------------------------------
# 中证500+1000 契合池（策略一默认）
# ---------------------------------------------------------------------------
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

_WATCH_PCT: dict[str, float] = {
    "002290": 0.03,
    "002636": 0.03,
    "002738": 0.03,
    "002747": 0.03,
    "002979": 0.03,
    "301389": 0.03,
    "301458": 0.03,
    "301550": 0.03,
    "301600": 0.03,
    "600105": 0.03,
    "600206": 0.03,
    "600330": 0.03,
    "601020": 0.03,
    "603119": 0.03,
    "002378": 0.02,
    "301678": 0.02,
    "603083": 0.02,
}

FIT_WATCHLIST: list[dict[str, Any]] = [
    watch_item(
        c,
        n,
        pct=_WATCH_PCT.get(code_key(c), DEFAULT_PCT),
        limit_down_pct=limit_down_pct_of(c),
    )
    for c, n in _FIT_WATCH
]

# 定案置顶三票（策略一阈值；与 S7 宇宙同码，不含因子4）
PINNED_WATCHLIST: list[dict[str, Any]] = [
    watch_item("600552", "凯盛科技", pct=0.025),
    watch_item("600330", "天通股份", pct=0.03),
    watch_item(
        "589680",
        "科创综指ETF鹏华",
        entry_pct=0.025,
        stop_pct=0.035,
        tick=0.001,
        t0=False,
        limit_down_pct=0.10,
    ),
]

_pinned_codes = {code_key(w["code"]) for w in PINNED_WATCHLIST}

# 现行盯盘：置顶三票 + 拟合池其余（去重）
WATCHLIST: list[dict[str, Any]] = list(PINNED_WATCHLIST) + [
    w for w in FIT_WATCHLIST if code_key(w["code"]) not in _pinned_codes
]

# 切策略三：STRATEGY_ID="strategy3"; USE_FACTOR4=True; WATCHLIST=list(S7_WATCHLIST)


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
    """当日盈亏 = 现价盯市盈亏。"""
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
