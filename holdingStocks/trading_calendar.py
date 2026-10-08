"""A-share trading calendar helpers.

The watch process must decide a signal/session date before market data is fully
ready. Runtime network calls are intentionally avoided here; known exchange
closures are kept as a small deterministic table, with an optional local JSON
override for future years.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
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
