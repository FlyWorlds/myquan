from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import QuoteRecord

TENCENT_QUOTE_SOURCE = "tencent_quote"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def parse_tencent_quote_line(line: str, *, fetched_at: str | None = None) -> QuoteRecord | None:
    """Parse one Tencent quote line like ``v_sz000001="..."``.

    Tencent occasionally changes field count.  This parser only relies on the
    stable early fields used by common free quote endpoints.
    """
    text = str(line or "").strip()
    if '="' not in text:
        return None
    left, raw = text.split('="', 1)
    code = left.split("_")[-1].lower()
    if code.startswith(("sz", "sh")):
        pure = code[2:]
    else:
        pure = code[-6:]
    parts = raw.rstrip('";').split("~")
    if len(parts) < 6:
        return None
    trade_date = ""
    quote_ts = None
    if len(parts) > 30 and parts[30]:
        stamp = str(parts[30])
        if len(stamp) >= 14 and stamp[:8].isdigit():
            trade_date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
            quote_ts = f"{trade_date} {stamp[8:10]}:{stamp[10:12]}:{stamp[12:14]}"
    return QuoteRecord(
        code=pure.zfill(6),
        source=TENCENT_QUOTE_SOURCE,
        fetched_at=fetched_at or _now(),
        trade_date=trade_date or None,
        name=parts[1] if len(parts) > 1 else "",
        last=_f(parts[3] if len(parts) > 3 else None),
        prev_close=_f(parts[4] if len(parts) > 4 else None),
        open=_f(parts[5] if len(parts) > 5 else None),
        amount=_f(parts[37] if len(parts) > 37 else None),
        quote_ts=quote_ts,
    )
