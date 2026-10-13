from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DataSourceResult:
    source: str
    fetched_at: str
    trade_date: str | None
    status: str
    rows: list[dict[str, Any]]
    latency_ms: int | None = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuoteRecord:
    code: str
    source: str
    fetched_at: str
    trade_date: str | None = None
    name: str = ""
    last: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    amount: float | None = None
    quote_ts: str | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "trade_date": self.trade_date,
            "name": self.name,
            "last": self.last,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "amount": self.amount,
            "quote_ts": self.quote_ts,
        }


@dataclass(frozen=True)
class LimitUpRecord:
    code: str
    name: str
    price: float | None
    pct: float | None
    amount_yi: float | None
    turnover_pct: float | None
    float_cap_yi: float | None
    seal_fund_yi: float | None
    first_seal: str
    last_seal: str
    break_times: int | None
    limit_days: int | None
    industry: str
    zt_stat: str
    source: str
    trade_date: str | None
    fetched_at: str

    def as_row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "pct": self.pct,
            "amount_yi": self.amount_yi,
            "turnover_pct": self.turnover_pct,
            "float_cap_yi": self.float_cap_yi,
            "seal_fund_yi": self.seal_fund_yi,
            "first_seal": self.first_seal,
            "last_seal": self.last_seal,
            "break_times": self.break_times,
            "limit_days": self.limit_days,
            "industry": self.industry,
            "zt_stat": self.zt_stat,
            "source": self.source,
            "trade_date": self.trade_date,
            "fetched_at": self.fetched_at,
        }
