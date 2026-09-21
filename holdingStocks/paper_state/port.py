"""PaperStatePort — strategy/watch must depend on this, not on PostgreSQL drivers."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from paper_state.models import (
    AccountSnapshot,
    DailyState,
    FullPaperState,
    PaperTrade,
    PositionRecord,
    WriterLease,
)

DEFAULT_ACCOUNT_ID = "default"
DEFAULT_LEASE_TTL_SEC = 45
DEFAULT_HEARTBEAT_INTERVAL_SEC = 15


class PaperStatePort(ABC):
    """Remote / local paper trading state repository."""

    @abstractmethod
    def backend_name(self) -> str: ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return {ok, backend, detail}."""

    # --- read ---
    @abstractmethod
    def get_account(self, account_id: str = DEFAULT_ACCOUNT_ID) -> AccountSnapshot | None: ...

    @abstractmethod
    def list_positions(
        self, account_id: str = DEFAULT_ACCOUNT_ID, *, open_only: bool = True
    ) -> list[PositionRecord]: ...

    @abstractmethod
    def list_trades(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
        *,
        session: str | None = None,
        limit: int = 5000,
    ) -> list[PaperTrade]: ...

    @abstractmethod
    def get_daily_state(
        self, account_id: str, trading_session_date: str
    ) -> DailyState | None: ...

    @abstractmethod
    def load_full_state(self, account_id: str = DEFAULT_ACCOUNT_ID) -> FullPaperState: ...

    # --- writer lease ---
    @abstractmethod
    def acquire_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        hostname: str,
        ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    ) -> WriterLease: ...

    @abstractmethod
    def heartbeat_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
        fencing_token: int,
        ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    ) -> WriterLease: ...

    @abstractmethod
    def release_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
    ) -> None: ...

    @abstractmethod
    def get_writer_lease(self, account_id: str = DEFAULT_ACCOUNT_ID) -> WriterLease | None: ...

    # --- mutations (must validate lease + fencing) ---
    @abstractmethod
    def apply_trade_mutation(
        self,
        *,
        account_id: str,
        trade: PaperTrade,
        position: PositionRecord,
        account: AccountSnapshot,
        expected_account_version: int,
        writer_id: str,
        lease_token: str,
        fencing_token: int,
        realized_today: dict[str, Any] | None = None,
        closed_today: dict[str, Any] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> tuple[AccountSnapshot, PositionRecord, PaperTrade]:
        """Atomic BUY/SELL: insert trade + update position + account (+ optional realized).

        Idempotent on trade.execution_id. Raises DuplicateExecutionError / StateConflictError /
        StaleWriterError / RemoteUnavailableError.
        """

    @abstractmethod
    def replace_full_state(
        self,
        state: FullPaperState,
        *,
        writer_id: str | None = None,
        lease_token: str | None = None,
        fencing_token: int | None = None,
        require_lease: bool = False,
    ) -> FullPaperState:
        """Migration / test import. Production path prefers apply_trade_mutation."""


def create_paper_state_port(
    backend: str | None = None,
    *,
    database_url: str | None = None,
    local_root: str | None = None,
) -> PaperStatePort:
    """Factory: PAPER_STATE_BACKEND=local_json|memory|postgres."""
    name = (backend or os.environ.get("PAPER_STATE_BACKEND") or "local_json").strip().lower()
    if name in ("memory", "mem"):
        from paper_state.memory import MemoryPaperStateAdapter

        return MemoryPaperStateAdapter()
    if name in ("local_json", "local", "json"):
        from paper_state.local_json import LocalJsonPaperStateAdapter
        from pathlib import Path

        root = Path(local_root) if local_root else Path(__file__).resolve().parent.parent
        return LocalJsonPaperStateAdapter(root)
    if name in ("postgres", "pg", "postgresql"):
        from paper_state.postgres import PostgresPaperStateAdapter

        url = database_url or os.environ.get("PAPER_DATABASE_URL") or ""
        return PostgresPaperStateAdapter(url)
    raise ValueError(f"unknown PAPER_STATE_BACKEND={name!r}")
