"""A-share trading calendar helpers.

The watch process must decide a signal/session date before market data is fully
ready. Runtime network calls are intentionally avoided here; known exchange
closures are kept as a small deterministic table, with an optional local JSON
override for future years.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OVERRIDE_PATH = ROOT / "trading_calendar_overrides.json"

# Shanghai Stock Exchange 2026 holiday schedule. Weekends are closed separately.
# Source: SSE "Stock Market Holiday Schedule (2026)".
_SSE_2026_CLOSED = frozenset(
    {
        # New Year
        "2026-01-01",
        "2026-01-02",
        # Spring Festival
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",
        "2026-02-19",
        "2026-02-20",
        "2026-02-23",
        # Qingming Festival
        "2026-04-06",
        # Labour Day
        "2026-05-01",
        "2026-05-04",
        "2026-05-05",
        # Dragon Boat Festival
        "2026-06-19",
        # Mid-Autumn Festival
        "2026-09-25",
        # National Day
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    }
)

_BUILTIN_CLOSED = _SSE_2026_CLOSED
_OVERRIDE_CACHE: tuple[float | None, set[str]] | None = None


def _to_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()


def _load_override_closed() -> set[str]:
    """Load optional local closed dates.

    Supported shapes:
      {"closed": ["2027-01-01", ...]}
      ["2027-01-01", ...]
    """
    global _OVERRIDE_CACHE
    try:
        st = OVERRIDE_PATH.stat()
    except OSError:
        _OVERRIDE_CACHE = (None, set())
        return set()
    mtime = float(st.st_mtime)
    if _OVERRIDE_CACHE is not None and _OVERRIDE_CACHE[0] == mtime:
        return set(_OVERRIDE_CACHE[1])
    try:
        raw = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        _OVERRIDE_CACHE = (mtime, set())
        return set()
    vals = raw.get("closed") if isinstance(raw, dict) else raw
    out: set[str] = set()
    if isinstance(vals, list):
        for item in vals:
            try:
                out.add(str(_to_date(item)))
            except (TypeError, ValueError):
                continue
    _OVERRIDE_CACHE = (mtime, out)
    return set(out)


def closed_dates() -> set[str]:
    return set(_BUILTIN_CLOSED) | _load_override_closed()


def is_trading_day(day: Any) -> bool:
    d = _to_date(day)
    if d.weekday() >= 5:
        return False
    return str(d) not in closed_dates()


def last_trading_day_on_or_before(day: Any) -> date:
    d = _to_date(day)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def previous_trading_day(day: Any) -> date:
    d = _to_date(day) - timedelta(days=1)
    return last_trading_day_on_or_before(d)


def trading_session_date(now: Any | None = None) -> date:
    ts = now if isinstance(now, datetime) else datetime.now()
    return last_trading_day_on_or_before(ts.date())


def normalize_signal_session(session: Any | None = None, *, now: Any | None = None) -> str:
    raw = str(session or "").strip()
    if not raw:
        return str(trading_session_date(now))
    try:
        day = _to_date(raw)
    except (TypeError, ValueError):
        return str(trading_session_date(now))
    return str(last_trading_day_on_or_before(day))


def effective_watch_session(now: Any | None = None) -> str:
    """当前盯盘展示、统计与对账所锚定的交易日 session。

    规则：
    · 非交易日（周末、法定休市日）：锚定上一个已完成交易日（如周六周日锚定上周五）。
    · 交易日 09:00 之前：尚未进入早盘重置节点，属于上一个交易日的复盘展示期，锚定上一交易日。
    · 交易日 09:00 及之后：早盘重置已触发，锚定当前交易日。
    """
    if now is None:
        ts = datetime.now()
    elif isinstance(now, datetime):
        ts = now
    elif isinstance(now, date):
        ts = datetime.combine(now, time(9, 30))
    else:
        raw = str(now).strip().replace("T", " ")
        try:
            if len(raw) >= 19:
                ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            elif len(raw) >= 16:
                ts = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            else:
                ts = datetime.combine(_to_date(raw), time(9, 30))
        except Exception:
            ts = datetime.now()
    d = ts.date()
    if not is_trading_day(d):
        return str(last_trading_day_on_or_before(d))
    if (ts.hour, ts.minute) < (9, 0):
        return str(previous_trading_day(d))
    return str(d)


def sentiment_session_context(now: Any | None = None) -> dict[str, Any]:
    """短线情绪栏的时间节点与交易日状态把控设计模式。

    时钟节点控制规范：
    1. 节假日/周末：算上一个交易日（休市复盘展示）；
    2. 交易日 00:00 ~ 09:20 之前：算上一个交易日（盘前复盘展示，严禁拿当日未开盘空数据覆盖）；
    3. 交易日 09:20 ~ 09:25：集合竞价过渡阶段；
    4. 交易日 09:25 及之后到 24:00：算当天。
       - 09:25 ~ 15:05：盘中实时分笔更新，显示当时更新的最新实时数据；
       - 15:05 ~ 24:00：今日已收盘，定格展示全天情绪终值与风控结论。
    """
    if now is None:
        ts = datetime.now()
    elif isinstance(now, datetime):
        ts = now
    elif isinstance(now, date):
        ts = datetime.combine(now, time(9, 30))
    else:
        raw = str(now).strip().replace("T", " ")
        try:
            if len(raw) >= 19:
                ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            elif len(raw) >= 16:
                ts = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            else:
                ts = datetime.combine(_to_date(raw), time(9, 30))
        except Exception:
            ts = datetime.now()

    d = ts.date()
    hm = (ts.hour, ts.minute)

    # 1. 节假日 / 周末
    if not is_trading_day(d):
        target_date = str(last_trading_day_on_or_before(d - timedelta(days=1)))
        return {
            "target_date": target_date,
            "is_today": False,
            "is_live": False,
            "phase": "holiday_closed",
            "phase_label": "非交易日休市",
            "tip": f"节假日休市：定格展示上一个交易日({target_date})的情绪终值与连板梯队",
            "now_str": ts.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 2. 交易日 00:00 ~ 09:20 盘前
    if hm < (9, 20):
        target_date = str(previous_trading_day(d))
        return {
            "target_date": target_date,
            "is_today": False,
            "is_live": False,
            "phase": "pre_market_replay",
            "phase_label": "盘前复盘锁定",
            "tip": f"盘前未开盘(0:00~9:20)：锁定展示上一个交易日({target_date})情绪终值，9:25后切换当日实时数据",
            "now_str": ts.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 3. 交易日 09:20 ~ 09:25 集合竞价撮合
    if hm < (9, 25):
        target_date = str(d)
        return {
            "target_date": target_date,
            "is_today": True,
            "is_live": False,
            "phase": "auction_transition",
            "phase_label": "集合竞价撮合中",
            "tip": "早盘9:20~9:25集合竞价撮合中，9:25产出今日首笔实时涨跌停板",
            "now_str": ts.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 4. 交易日 09:25 ~ 15:05 盘中实时更新时段
    if hm < (15, 5):
        target_date = str(d)
        return {
            "target_date": target_date,
            "is_today": True,
            "is_live": True,
            "phase": "intraday_live",
            "phase_label": "盘中实时更新",
            "tip": "交易时段：实时更新当前最新分笔涨跌停家数、连板梯队与题材共振",
            "now_str": ts.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 5. 交易日 15:05 ~ 24:00 收盘后定格
    target_date = str(d)
    return {
        "target_date": target_date,
        "is_today": True,
        "is_live": False,
        "phase": "post_market_closed",
        "phase_label": "已收盘定格",
        "tip": f"今日已收盘：定格展示今日({target_date})全天短线情绪终值与风控结论",
        "now_str": ts.strftime("%Y-%m-%d %H:%M:%S"),
    }


