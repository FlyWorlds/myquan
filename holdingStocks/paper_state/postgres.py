"""PostgreSQL adapter skeleton — production remote source of truth (R2+).

R1: schema + connection/health + raise if URL missing.
Full SQL mutation paths land when PAPER_DATABASE_URL is provisioned (R2).
"""

from __future__ import annotations

from typing import Any

from paper_state.errors import RemoteUnavailableError
from paper_state.models import (
    AccountSnapshot,
    DailyState,
    FullPaperState,
    PaperTrade,
    PositionRecord,
    WriterLease,
)
from paper_state.port import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_LEASE_TTL_SEC,
    PaperStatePort,
)


class PostgresPaperStateAdapter(PaperStatePort):
    """Postgres PaperStatePort.

    Requires env ``PAPER_DATABASE_URL`` (never commit secrets).
    Optional dependency: ``psycopg`` / ``psycopg2`` — imported lazily.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = str(database_url or "").strip()
        self._conn = None

    def backend_name(self) -> str:
        return "postgres"

    def _connect(self) -> Any:
        if not self.database_url:
            raise RemoteUnavailableError(
                "REMOTE_STATE_UNAVAILABLE: PAPER_DATABASE_URL not set"
            )
        if self._conn is not None:
            return self._conn
        try:
            import psycopg  # type: ignore

            self._conn = psycopg.connect(self.database_url)
            return self._conn
        except ImportError:
            try:
                import psycopg2  # type: ignore

                self._conn = psycopg2.connect(self.database_url)
                return self._conn
            except ImportError as e:
                raise RemoteUnavailableError(
                    "REMOTE_STATE_UNAVAILABLE: install psycopg or psycopg2"
                ) from e
        except Exception as e:  # noqa: BLE001
            raise RemoteUnavailableError(
                f"REMOTE_STATE_UNAVAILABLE: {e}"
            ) from e

    def health(self) -> dict[str, Any]:
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            return {"ok": True, "backend": "postgres", "detail": "connected"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "backend": "postgres", "detail": str(e)}

    def get_account(self, account_id: str = DEFAULT_ACCOUNT_ID) -> AccountSnapshot | None:
        raise RemoteUnavailableError("postgres get_account not wired in R1 — use R2")

    def list_positions(
        self, account_id: str = DEFAULT_ACCOUNT_ID, *, open_only: bool = True
    ) -> list[PositionRecord]:
        raise RemoteUnavailableError("postgres list_positions not wired in R1")

    def list_trades(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
        *,
        session: str | None = None,
        limit: int = 5000,
    ) -> list[PaperTrade]:
        raise RemoteUnavailableError("postgres list_trades not wired in R1")

    def get_daily_state(
        self, account_id: str, trading_session_date: str
    ) -> DailyState | None:
        raise RemoteUnavailableError("postgres get_daily_state not wired in R1")

    def load_full_state(self, account_id: str = DEFAULT_ACCOUNT_ID) -> FullPaperState:
        raise RemoteUnavailableError("postgres load_full_state not wired in R1")

    def acquire_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        hostname: str,
        ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    ) -> WriterLease:
        raise RemoteUnavailableError("postgres acquire_writer_lease not wired in R1")

    def heartbeat_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
        fencing_token: int,
        ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    ) -> WriterLease:
        raise RemoteUnavailableError("postgres heartbeat not wired in R1")

    def release_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
    ) -> None:
        raise RemoteUnavailableError("postgres release not wired in R1")

    def get_writer_lease(self, account_id: str = DEFAULT_ACCOUNT_ID) -> WriterLease | None:
        raise RemoteUnavailableError("postgres get_writer_lease not wired in R1")

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
        realized_today: dict | None = None,
        closed_today: dict | None = None,
        extras: dict | None = None,
    ) -> tuple[AccountSnapshot, PositionRecord, PaperTrade]:
        # Explicit: never silently write local JSON on remote failure.
        raise RemoteUnavailableError(
            "REMOTE_STATE_UNAVAILABLE: postgres apply_trade_mutation not wired in R1; "
            "NEW PAPER MUTATION PAUSED — no local fallback write"
        )

    def replace_full_state(
        self,
        state: FullPaperState,
        *,
        writer_id: str | None = None,
        lease_token: str | None = None,
        fencing_token: int | None = None,
        require_lease: bool = False,
    ) -> FullPaperState:
        raise RemoteUnavailableError("postgres replace_full_state not wired in R1")
