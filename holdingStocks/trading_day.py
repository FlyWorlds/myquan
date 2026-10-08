"""交易日生命周期：日结 / 跨日 rollover / P&L 基线（非平仓）。

口径真源（与账户 UI 对齐）：

TRADING_DAY_SOURCE_OF_TRUTH = trading_session_date()
  · 交易日 = 当日；周末/交易所休市日锚定上一交易日（不创建假 session）

SETTLEMENT_TIME_SEMANTICS = 连续竞价结束后 phase==closed（15:00 后）
  · POSITION_SETTLEMENT = 收盘盯市记账（不改 qty / cost，不写 SELL）
  · POSITION_EXIT = 纸面卖出（realized_today）；二者严禁混用

OFFICIAL_CLOSE_SOURCE = 行情源收盘后 last（新浪/东财 SSE 现价，15:00 后视作正式收盘）
CLOSE_PRICE_FALLBACK = 当日 1 分钟末根 close → 再退日线最近收盘

POSITION_COST_BASIS = 买入均价 cost（跨日不改）
POSITION_CUMULATIVE_PNL = (mark - cost) * qty
POSITION_DAY_PNL =
  昨仓 (mark - previous_close) * qty；
  今买 (mark - buy_cost) * qty
STOCK_DAY_CHANGE = (mark - previous_close) / previous_close * 100
  · 新交易日尚无有效现价：显示 0（不得沿用上一交易日涨跌幅）

ACCOUNT_OPEN_ROLLOVER = account_total_open(T+1) = closing_equity(T)
ACCOUNT_TODAY_PNL = current_equity - account_total_open
ACCOUNT_TOTAL_PNL = current_equity - paper_equity_base
"""

from __future__ import annotations

from typing import Any

from watch_config import (
    normalize_signal_session,
    prev_trading_day,
    trading_session_date,
)

SETTLE_KIND_POSITION = "POSITION_SETTLEMENT"
SETTLE_KIND_EXIT = "POSITION_EXIT"

OFFICIAL_CLOSE_SOURCE = "quote_last_after_close"
CLOSE_PRICE_FALLBACK = "session_1m_last_close|daily_prev_close"


def current_trading_session(now: Any | None = None) -> str:
    return str(trading_session_date(now))


def previous_trading_session(session: Any | None = None) -> str:
    sess = normalize_signal_session(session or trading_session_date())
    return str(prev_trading_day(sess))


def promote_quote_session(session: Any, *, now: Any | None = None) -> str:
    """行情盘前常仍标上一交易日；信号/账户日与日历对齐。"""
    cal = current_trading_session(now)
    raw = normalize_signal_session(session, now=now)
    if str(raw)[:10] < cal[:10]:
        return cal
    return str(raw)[:10]


def stock_day_change_pct(mark: Any, previous_close: Any) -> float | None:
    """(mark - previous_close) / previous_close * 100。"""
    try:
        m = float(mark)
        p = float(previous_close)
    except (TypeError, ValueError):
        return None
    if p <= 0 or m != m or p != p:
        return None
    return round((m / p - 1.0) * 100.0, 2)


def sanitize_day_change_for_session(
    *,
    quote_session: Any,
    calendar_session: str,
    mark: Any,
    previous_close: Any,
    day_chg_pct: Any = None,
) -> float | None:
    """新交易日不得沿用上一交易日涨跌幅。

    · quote_session < calendar：尚无本 session 有效行情 → 0
    · 否则：优先用 (mark/prev_close-1)；缺省才用传入 day_chg_pct
    """
    cal = str(calendar_session or "")[:10]
    q_sess = str(quote_session or "")[:10]
    if cal and q_sess and q_sess < cal:
        return 0.0
    chg = stock_day_change_pct(mark, previous_close)
    if chg is not None:
        return chg
    if day_chg_pct is None or day_chg_pct == "":
        return None
    try:
        return round(float(day_chg_pct), 2)
    except (TypeError, ValueError):
        return None


def overnight_preopen_quote(
    *,
    calendar_session: str,
    previous_close: float,
    last_ts: str | None = None,
) -> dict[str, Any]:
    """新交易日盘前：现价=昨收，涨跌幅=0（不展示上一日 day change）。"""
    px = float(previous_close)
    return {
        "session": str(calendar_session)[:10],
        "open": px,
        "high": px,
        "low": px,
        "last": px,
        "prev_close": px,
        "day_chg_pct": 0.0,
        "last_ts": last_ts or "",
        "_preopen_baseline": True,
    }


def resolve_official_close(
    *,
    quote_last: Any = None,
    minute_last_close: Any = None,
    daily_close: Any = None,
) -> tuple[float | None, str]:
    """收盘盯市价：正式 last → 1m 末根 → 日线收盘。返回 (price, source)."""
    for src, val in (
        (OFFICIAL_CLOSE_SOURCE, quote_last),
        ("session_1m_last_close", minute_last_close),
        ("daily_prev_close", daily_close),
    ):
        try:
            px = float(val)
        except (TypeError, ValueError):
            continue
        if px > 0 and px == px:
            return px, src
    return None, "none"


def position_cumulative_pnl(mark: Any, cost: Any, qty: int) -> float | None:
    try:
        m = float(mark)
        c = float(cost)
        q = int(qty)
    except (TypeError, ValueError):
        return None
    if q <= 0 or c <= 0 or m != m:
        return None
    return round((m - c) * q, 2)


def position_day_pnl(
    *,
    mark: Any,
    qty: int,
    cost: Any = None,
    previous_close: Any = None,
    bought_today: bool = False,
) -> float | None:
    try:
        m = float(mark)
        q = int(qty)
    except (TypeError, ValueError):
        return None
    if q <= 0 or m != m:
        return None
    if bought_today:
        try:
            c = float(cost)
        except (TypeError, ValueError):
            return None
        if c <= 0:
            return None
        return round((m - c) * q, 2)
    try:
        p = float(previous_close)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    return round((m - p) * q, 2)


def account_today_pnl(current_equity: Any, account_open: Any) -> float | None:
    try:
        cur = float(current_equity)
        op = float(account_open)
    except (TypeError, ValueError):
        return None
    if cur != cur or op != op:
        return None
    return round(cur - op, 2)


def account_today_return_pct(day_pnl: Any, account_open: Any) -> float | None:
    try:
        d = float(day_pnl)
        op = float(account_open)
    except (TypeError, ValueError):
        return None
    if op <= 0 or d != d or op != op:
        return None
    return round(d / op * 100.0, 2)


def account_total_pnl(current_equity: Any, paper_base: Any) -> float | None:
    try:
        cur = float(current_equity)
        base = float(paper_base)
    except (TypeError, ValueError):
        return None
    if base <= 0 or cur != cur:
        return None
    return round(cur - base, 2)


def build_position_settlement_marks(
    rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """POSITION_SETTLEMENT 收盘盯市行：只记 mark，不改仓。"""
    out: list[dict[str, Any]] = []
    for r in rows or []:
        try:
            qty = int(r.get("持仓") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        code = str(r.get("代码") or r.get("code") or "").strip()
        if not code:
            continue
        close_px = r.get("现价") if r.get("现价") is not None else r.get("last")
        cost = r.get("成本") if r.get("成本") is not None else r.get("cost")
        out.append(
            {
                "code": code,
                "name": r.get("名称") or r.get("name"),
                "qty": qty,
                "cost": cost,
                "close": close_px,
                "day_pnl": r.get("当日盈亏") if "当日盈亏" in r else r.get("day_pnl"),
                "upnl": r.get("浮盈") if "浮盈" in r else r.get("upnl"),
                "settle_kind": SETTLE_KIND_POSITION,
            }
        )
    return out


def needs_session_rollover(
    data: dict[str, Any],
    *,
    session: str,
) -> bool:
    """stored_session < current → 需要一次跨日 heal（同日幂等）。"""
    sess = str(session or "")[:10]
    if len(sess) < 10:
        return False
    open_sess = str(data.get("account_total_open_session") or "")[:10]
    last_sess = str(data.get("last_session") or "")[:10]
    if open_sess and open_sess < sess:
        return True
    if last_sess and last_sess < sess:
        return True
    # 有非当日平仓留痕也要 rollover 清理
    for bag in ("realized_today", "closed_today"):
        raw = data.get(bag)
        if not isinstance(raw, dict):
            continue
        for rec in raw.values():
            if not isinstance(rec, dict):
                continue
            d = str(rec.get("session") or "")[:10]
            if d and d < sess:
                return True
    return False


def filter_today_realized(
    realized: dict[str, Any] | None,
    *,
    session: str,
) -> dict[str, Any]:
    """只保留当前 trading session 的今日平仓；历史仍在 trades ledger。"""
    day = str(session or "")[:10]
    raw = realized if isinstance(realized, dict) else {}
    return {
        k: v
        for k, v in raw.items()
        if isinstance(v, dict) and str(v.get("session") or "")[:10] == day
    }
