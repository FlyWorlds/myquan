from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import QuoteRecord

SINA_QUOTE_SOURCE = "sina_quote"


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


def parse_sina_quote_line(line: str, *, fetched_at: str | None = None) -> QuoteRecord | None:
    text = str(line or "").strip()
    if '="' not in text:
        return None
    left, raw = text.split('="', 1)
    code = left.split("_")[-1].lower()
    pure = code[2:] if code.startswith(("sz", "sh")) else code[-6:]
    parts = raw.rstrip('";').split(",")
    if len(parts) < 32:
        return None
    trade_date = parts[30] or None
    clock = parts[31] or ""
    quote_ts = f"{trade_date} {clock}" if trade_date and clock else None
    return QuoteRecord(
        code=pure.zfill(6),
        source=SINA_QUOTE_SOURCE,
        fetched_at=fetched_at or _now(),
        trade_date=trade_date,
        name=parts[0],
        open=_f(parts[1]),
        prev_close=_f(parts[2]),
        last=_f(parts[3]),
        high=_f(parts[4]),
        low=_f(parts[5]),
        amount=_f(parts[9]),
        quote_ts=quote_ts,
    )
