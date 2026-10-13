"""因子29：9:20–9:25 不可撤单阶段竞价强度。

信号必须在 09:25 撮合前由已观察到的指示价路径形成；正式成交价仅使用
经独立单股行情复核的 09:25 开盘价，禁止事后用最终开盘反造竞价信号。

策略十六绑定：竞价末段达到个股阈值则武装买卖；成交价=正式开盘。
例如圣阳/金安若 9:20 后路径已触及阈值，买入点就是当日正式开盘，
而不是 ceil(开盘×(1+entry))，更不是竞价指示价本身。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.open_break import DEFAULT_PCT, TICK_SIZE, entry_trigger_price, stop_trigger_price

FACTOR_ID = "factor29"
FACTOR_NAME = "因子29-竞价末段强度"
WINDOW_START = "09:20:00"
WINDOW_END = "09:25:00"


def quote_clock_hms(ts: Any) -> str:
    s = str(ts or "").strip().replace("T", " ", 1)
    if len(s) >= 19 and s[10:11] == " ":
        return s[11:19]
    if len(s) >= 8 and s[2:3] == ":":
        return s[:8]
    return ""


def quote_in_lock_window(ts: Any) -> bool:
    """仅 09:20:00 ≤ 行情时刻 < 09:25:00。9:15–9:19 与 9:25 本身都不算。"""
    clock = quote_clock_hms(ts)
    return bool(clock) and WINDOW_START <= clock < WINDOW_END


def _pos_px(value: Any) -> float | None:
    try:
        px = float(value or 0)
    except (TypeError, ValueError):
        return None
    if px <= 0:
        return None
    return round(px, 4)


def levels(
    baseline_px: float,
    *,
    threshold_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
    **_: Any,
) -> dict[str, float]:
    """以 9:20 后首个有效指示价计算对称触发线。"""
    base = float(baseline_px)
    if base <= 0:
        raise ValueError("baseline_px must be positive")
    return {
        "baseline": round(base, 4),
        "buy_trigger": float(
            entry_trigger_price(base, entry_pct=float(threshold_pct), tick=float(tick))
        ),
        "sell_trigger": float(
            stop_trigger_price(base, stop_pct=float(threshold_pct), tick=float(tick))
        ),
    }


def merge_auction_path(
    *,
    quote: dict[str, Any] | None = None,
    sticky: dict[str, Any] | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """合并行情里独立保存的 9:20–9:25 路径与同日粘滞。

    禁止用正式开盘/当日最高/现价回填竞价路径，避免 9:25 后lookahead。
    """
    day = str(session or "")[:10]
    q = quote if isinstance(quote, dict) else {}
    q_day = str(q.get("session") or day)[:10]
    raw_st = None
    if isinstance(sticky, dict):
        raw_st = sticky.get("f29_path") if isinstance(sticky.get("f29_path"), dict) else sticky
    st = raw_st if isinstance(raw_st, dict) else {}
    st_day = str(st.get("session") or "")[:10]
    if st_day and day and st_day != day:
        st = {}
    if q_day and day and q_day != day:
        q_path = {}
    else:
        q_path = {
            "baseline": _pos_px(q.get("_auction_baseline")),
            "high": _pos_px(q.get("_auction_high")),
            "low": _pos_px(q.get("_auction_low")),
            "ts": str(q.get("_auction_ts") or ""),
        }
    st_path = {
        "baseline": _pos_px(st.get("baseline")),
        "high": _pos_px(st.get("high")),
        "low": _pos_px(st.get("low")),
        "ts": str(st.get("ts") or ""),
    }
    baseline = q_path["baseline"] or st_path["baseline"]
    highs = [x for x in (q_path["high"], st_path["high"]) if x is not None]
    lows = [x for x in (q_path["low"], st_path["low"]) if x is not None]
    return {
        "session": day or q_day or st_day,
        "baseline": baseline,
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "ts": q_path["ts"] or st_path["ts"] or None,
    }


def observe_auction_tick(
    state: dict[str, Any] | None,
    *,
    last: float | None,
    ts: Any,
    session: str | None = None,
) -> dict[str, Any]:
    """只吸收锁定期指示现价；缺窗口或不合法价原样返回。"""
    prev = dict(state or {})
    day = str(session or prev.get("session") or "")[:10]
    if day:
        prev["session"] = day
    if not quote_in_lock_window(ts):
        return prev
    px = _pos_px(last)
    if px is None:
        return prev
    if _pos_px(prev.get("baseline")) is None:
        prev["baseline"] = px
        prev["high"] = px
        prev["low"] = px
    else:
        prev["high"] = round(max(float(prev.get("high") or px), px), 4)
        prev["low"] = round(min(float(prev.get("low") or px), px), 4)
    prev["ts"] = str(ts or "")
    return prev


def signal(
    *,
    baseline_px: float | None,
    auction_high: float | None,
    auction_low: float | None,
    threshold_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
    **_: Any,
) -> dict[str, Any]:
    """根据撮合前路径判定买卖武装；不读取 09:25 最终开盘。"""
    try:
        base = float(baseline_px or 0)
        high = float(auction_high or 0)
        low = float(auction_low or 0)
    except (TypeError, ValueError):
        base = high = low = 0.0
    if base <= 0 or high <= 0 or low <= 0:
        return {
            "ready": False,
            "hit_buy": False,
            "hit_sell": False,
            "baseline": None,
            "buy_trigger": None,
            "sell_trigger": None,
        }
    lv = levels(base, threshold_pct=threshold_pct, tick=tick)
    return {
        "ready": True,
        "hit_buy": high + 1e-12 >= lv["buy_trigger"],
        "hit_sell": low <= lv["sell_trigger"] + 1e-12,
        "auction_high": high,
        "auction_low": low,
        **lv,
    }


def fill_at_official_open(official_open: float | None) -> float | None:
    """武装后的成交价：只认正式开盘，不用竞价触发价。"""
    px = _pos_px(official_open)
    return px


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "9:20后首个有效竞价指示价为基准；9:25撮合前上涨/下跌达到个股阈值，"
        "分别武装买入/卖出。委托视为撮合前提交；成交须在正式开盘以单股行情复核后的"
        "开盘价结算，卖出遵守T+1。"
    ),
    rules_text=(
        "仅使用09:20:00≤行情时刻<09:25:00的point-in-time路径；"
        "不得用09:25最终开盘反推触发。缺少基准、路径、时间戳或开盘复核时失败关闭。"
        "成交价=正式开盘，不是ceil(开盘×(1+entry))，也不是竞价指示价。"
    ),
    implemented=True,
    levels=levels,
    signal=signal,
    meta={
        "kind": "closing_call_auction_strength",
        "category": "execution",
        "window": "09:20:00-09:24:59",
        "execution": "official_open_after_single_stock_audit",
        "default_threshold_pct": DEFAULT_PCT,
        "point_in_time": True,
        "status": "production_watch",
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "WINDOW_START",
    "WINDOW_END",
    "levels",
    "signal",
    "quote_in_lock_window",
    "merge_auction_path",
    "observe_auction_tick",
    "fill_at_official_open",
]
