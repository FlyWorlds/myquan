"""盯盘标的池与代码工具（唯一真源；index 从此处导入）。

当前锁定：**策略一 = 因子1 + 因子2（回撤预警）**。
定案宇宙：因子13 宽宇宙换池（无置顶；及格才入池）。
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

# 早盘节点（A 股集合竞价 + 连续竞价）
AUCTION_START_HOUR = 9
AUCTION_START_MINUTE = 15  # 9:15 起拉竞价行情；报单可撤
AUCTION_NO_CANCEL_HOUR = 9
AUCTION_NO_CANCEL_MINUTE = 20  # 9:20 起不可撤单
AUCTION_OPEN_HOUR = 9
AUCTION_OPEN_MINUTE = 25  # 9:25 开盘价确定 → 算过门/买点/止损
SIGNAL_ACTIVE_HOUR = 9
SIGNAL_ACTIVE_MINUTE = 30  # 9:30 连续竞价 → 触发买卖/止损结算/微信

# 开盘价强制刷新（与 9:25 对齐）
OPEN_PRICE_REFRESH_HOUR = AUCTION_OPEN_HOUR
OPEN_PRICE_REFRESH_MINUTE = AUCTION_OPEN_MINUTE

# watch 里程碑：(时, 分, 日志标签, 动作 reseed|open|refresh)
AUCTION_MILESTONES: tuple[tuple[int, int, str, str], ...] = (
    (9, 15, "竞价开始·拉行情（可撤单）", "reseed"),
    (9, 20, "竞价·不可撤单", "refresh"),
    (9, 25, "开盘价确定·算阈值/过门", "open"),
    (9, 30, "连续竞价·信号触发", "refresh"),
)

INDEX_WATCH: list[dict[str, str]] = [
    {"code": "sh000001", "name": "上证指数", "market": "上证"},
    {"code": "sz399001", "name": "深证成指", "market": "深证"},
]


def _clock_minutes(now: Any | None = None) -> int:
    from datetime import datetime as _dt

    ts = now if isinstance(now, _dt) else _dt.now()
    return int(ts.hour) * 60 + int(ts.minute)


def market_phase(now: Any | None = None) -> str:
    """盘前 / 竞价可撤 / 竞价不可撤 / 阈值盯盘 / 连续竞价。"""
    m = _clock_minutes(now)
    a15 = AUCTION_START_HOUR * 60 + AUCTION_START_MINUTE
    a20 = AUCTION_NO_CANCEL_HOUR * 60 + AUCTION_NO_CANCEL_MINUTE
    a25 = AUCTION_OPEN_HOUR * 60 + AUCTION_OPEN_MINUTE
    a30 = SIGNAL_ACTIVE_HOUR * 60 + SIGNAL_ACTIVE_MINUTE
    if m < a15:
        return "pre_auction"
    if m < a20:
        return "auction_cancel"
    if m < a25:
        return "auction_locked"
    if m < a30:
        return "open_set"
    return "continuous"


def market_phase_label(phase: str | None = None, *, now: Any | None = None) -> str:
    ph = phase or market_phase(now)
    labels = {
        "pre_auction": "盘前（9:15 前）",
        "auction_cancel": "集合竞价·可撤单（9:15–9:20）",
        "auction_locked": "集合竞价·不可撤单（9:20–9:25）",
        "open_set": "开盘价已出·阈值盯盘（9:25–9:30）",
        "continuous": "连续竞价·信号触发（9:30 起）",
    }
    return labels.get(ph, ph)


def is_auction_quote_window(now: Any | None = None) -> bool:
    """9:15 起拉竞价行情（watch 高频刷新）。"""
    return _clock_minutes(now) >= (
        AUCTION_START_HOUR * 60 + AUCTION_START_MINUTE
    )


def is_threshold_ready(now: Any | None = None) -> bool:
    """9:25 起用开盘价算过门/买点/止损（9:30 前不结算）。"""
    return _clock_minutes(now) >= (
        AUCTION_OPEN_HOUR * 60 + AUCTION_OPEN_MINUTE
    )


def is_signal_window(now: Any | None = None) -> bool:
    """9:30 起才允许因子触发/止损结算/微信预警。"""
    return _clock_minutes(now) >= (
        SIGNAL_ACTIVE_HOUR * 60 + SIGNAL_ACTIVE_MINUTE
    )


def is_auction_window(now: Any | None = None) -> bool:
    """是否处于集合竞价时段 09:15–09:30（不含 09:30）。"""
    t = _clock_minutes(now)
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


def is_mainboard_pool(code: str) -> bool:
    """策略一股票池：沪深主板（剔创业板/科创板/北交所）。"""
    c = code_key(code)
    if c.startswith(("688", "689", "300", "301")):
        return False
    if c.startswith(("8", "4")):
        return False
    return True


# ---------------------------------------------------------------------------
# 策略三默认宇宙（与 strategy.config 对齐；S7 为历史命名）
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
# 因子13 宽宇宙换池（无置顶；及格才入池）
# ---------------------------------------------------------------------------
_FIT_WATCH: list[tuple[str, str]] = [
    ("002104", "恒宝股份"),
    ("603301", "振德医疗"),
    ("601609", "金田股份"),
    ("600301", "华锡有色"),
    ("002093", "国脉科技"),
    ("601020", "华钰矿业"),
    ("603256", "宏和科技"),
    ("002779", "中坚科技"),
    ("002015", "协鑫能科"),
    ("600967", "内蒙一机"),
]

_WATCH_PCT: dict[str, float] = {
    "002093": 0.03,
    "002779": 0.03,
    "600301": 0.03,
    "601020": 0.03,
    "603301": 0.03,
    "601609": 0.02,
}

FIT_WATCHLIST: list[dict[str, Any]] = [
    watch_item(
        c,
        n,
        pct=_WATCH_PCT.get(code_key(c), DEFAULT_PCT),
        limit_down_pct=limit_down_pct_of(c),
    )
    for c, n in _FIT_WATCH
    if is_mainboard_pool(c)
]

# 现行盯盘：与契合池一致（无置顶；因子13 及格才入池）
WATCHLIST: list[dict[str, Any]] = list(FIT_WATCHLIST)

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
