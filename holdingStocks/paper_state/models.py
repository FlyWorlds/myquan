"""Paper state value objects (path-independent; no absolute Windows/Mac paths)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _code_key(code: str) -> str:
    return str(code or "").strip().zfill(6)[-6:]


@dataclass
class AccountSnapshot:
    account_id: str
    paper_equity_base: float | None = None
    account_cash: float | None = None
    account_total: float | None = None
    account_total_open: float | None = None
    account_total_open_session: str | None = None
    trading_session_date: str | None = None
    last_session: str | None = None
    paper_pnl_start: str | None = None
    version: int = 0
    updated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class PositionRecord:
    account_id: str
    symbol: str
    qty: int = 0
    available: int | None = None
    cost: float | None = None
    today_cost: float | None = None
    buy_time: str | None = None
    name: str = ""
    market: str = ""
    note: str = ""
    peak_high: float | None = None
    overnight_peak: float | None = None
    overnight_peak_session: str | None = None
    stop_noted: bool = False
    stop_noted_px: float | None = None
    stop_noted_session: str | None = None
    tp_stage: int = 0
    last_tp_ts: str | None = None
    version: int = 0
    updated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol = _code_key(self.symbol)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperTrade:
    trade_id: str
    account_id: str
    symbol: str
    side: str  # buy | sell
    qty: int
    fill_price: float
    trading_session_date: str
    executed_at: str
    execution_id: str | None = None
    cost_basis: float | None = None
    realized_pnl: float | None = None
    reason_code: str = ""
    strategy_id: str = ""
    note: str = ""
    after_qty: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol = _code_key(self.symbol)
        self.side = str(self.side or "").strip().lower()
        if self.execution_id is None:
            self.execution_id = self.trade_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyState:
    account_id: str
    trading_session_date: str
    opening_equity: float | None = None
    closing_equity: float | None = None
    settled: bool = False
    settled_at: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriterLease:
    account_id: str
    writer_id: str
    hostname: str
    lease_token: str
    fencing_token: int
    lease_expires_at: str  # ISO UTC
    heartbeat_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FullPaperState:
    """Migration / round-trip bundle."""

    account: AccountSnapshot
    positions: list[PositionRecord] = field(default_factory=list)
    trades: list[PaperTrade] = field(default_factory=list)
    daily: list[DailyState] = field(default_factory=list)
    realized_today: dict[str, Any] = field(default_factory=dict)
    closed_today: dict[str, Any] = field(default_factory=dict)
    slot_queue: dict[str, Any] = field(default_factory=dict)
    factor_memory: dict[str, Any] = field(default_factory=dict)
    factor2: dict[str, Any] = field(default_factory=dict)
    portfolio_pool: list[str] = field(default_factory=list)
    runtime_extras: dict[str, Any] = field(default_factory=dict)

    def open_positions(self) -> list[PositionRecord]:
        return [p for p in self.positions if int(p.qty or 0) > 0]
