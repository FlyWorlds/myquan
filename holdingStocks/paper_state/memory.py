"""In-memory PaperStatePort — unit tests / dry-run without filesystem."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from paper_state.errors import (
    DuplicateExecutionError,
    LeaseConflictError,
    StaleWriterError,
    StateConflictError,
)
from paper_state.models import (
    AccountSnapshot,
    DailyState,
    FullPaperState,
    PaperTrade,
    PositionRecord,
    WriterLease,
)
from paper_state.port import DEFAULT_ACCOUNT_ID, DEFAULT_LEASE_TTL_SEC, PaperStatePort


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MemoryPaperStateAdapter(PaperStatePort):
    def __init__(self) -> None:
        self._accounts: dict[str, AccountSnapshot] = {}
        self._positions: dict[str, dict[str, PositionRecord]] = {}
        self._trades: dict[str, list[PaperTrade]] = {}
        self._exec_ids: dict[str, set[str]] = {}
        self._daily: dict[str, dict[str, DailyState]] = {}
        self._leases: dict[str, WriterLease] = {}
        self._extras: dict[str, dict[str, Any]] = {}

    def backend_name(self) -> str:
        return "memory"

    def health(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory", "detail": "in-process"}

    def get_account(self, account_id: str = DEFAULT_ACCOUNT_ID) -> AccountSnapshot | None:
        a = self._accounts.get(account_id)
        return copy.deepcopy(a) if a else None

    def list_positions(
        self, account_id: str = DEFAULT_ACCOUNT_ID, *, open_only: bool = True
    ) -> list[PositionRecord]:
        rows = list((self._positions.get(account_id) or {}).values())
        if open_only:
            rows = [p for p in rows if int(p.qty or 0) > 0]
        return [copy.deepcopy(p) for p in rows]

    def list_trades(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
        *,
        session: str | None = None,
        limit: int = 5000,
    ) -> list[PaperTrade]:
        rows = list(self._trades.get(account_id) or [])
        if session:
            day = str(session)[:10]
            rows = [t for t in rows if str(t.trading_session_date)[:10] == day]
        return [copy.deepcopy(t) for t in rows[-int(limit) :]]

    def get_daily_state(
        self, account_id: str, trading_session_date: str
    ) -> DailyState | None:
        d = (self._daily.get(account_id) or {}).get(str(trading_session_date)[:10])
        return copy.deepcopy(d) if d else None

    def load_full_state(self, account_id: str = DEFAULT_ACCOUNT_ID) -> FullPaperState:
        acc = self.get_account(account_id) or AccountSnapshot(account_id=account_id)
        extras = copy.deepcopy(self._extras.get(account_id) or {})
        return FullPaperState(
            account=acc,
            positions=self.list_positions(account_id, open_only=False),
            trades=self.list_trades(account_id, limit=100_000),
            daily=list((self._daily.get(account_id) or {}).values()),
            realized_today=extras.get("realized_today") or {},
            closed_today=extras.get("closed_today") or {},
            slot_queue=extras.get("slot_queue") or {},
            factor_memory=extras.get("factor_memory") or {},
            factor2=extras.get("factor2") or {},
            portfolio_pool=list(extras.get("portfolio_pool") or []),
            runtime_extras={
                k: v
                for k, v in extras.items()
                if k
                not in (
                    "realized_today",
                    "closed_today",
                    "slot_queue",
                    "factor_memory",
                    "factor2",
                    "portfolio_pool",
                )
            },
        )

    def _lease_alive(self, lease: WriterLease | None) -> bool:
        if lease is None:
            return False
        try:
            exp = datetime.strptime(lease.lease_expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return False
        return exp > _utc_now()

    def acquire_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        hostname: str,
        ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    ) -> WriterLease:
        cur = self._leases.get(account_id)
        if self._lease_alive(cur) and cur and cur.writer_id != writer_id:
            raise LeaseConflictError(
                f"ACTIVE_WRITER_EXISTS writer_id={cur.writer_id} host={cur.hostname}"
            )
        fencing = int(cur.fencing_token) + 1 if cur else 1
        now = _utc_now()
        lease = WriterLease(
            account_id=account_id,
            writer_id=writer_id,
            hostname=hostname,
            lease_token=uuid.uuid4().hex,
            fencing_token=fencing,
            lease_expires_at=_iso(now + timedelta(seconds=int(ttl_sec))),
            heartbeat_at=_iso(now),
        )
        self._leases[account_id] = lease
        return copy.deepcopy(lease)

    def heartbeat_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
        fencing_token: int,
        ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    ) -> WriterLease:
        cur = self._leases.get(account_id)
        if (
            cur is None
            or cur.writer_id != writer_id
            or cur.lease_token != lease_token
            or int(cur.fencing_token) != int(fencing_token)
        ):
            raise StaleWriterError("lease token / fencing mismatch")
        now = _utc_now()
        cur.heartbeat_at = _iso(now)
        cur.lease_expires_at = _iso(now + timedelta(seconds=int(ttl_sec)))
        self._leases[account_id] = cur
        return copy.deepcopy(cur)

    def release_writer_lease(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
    ) -> None:
        cur = self._leases.get(account_id)
        if cur and cur.writer_id == writer_id and cur.lease_token == lease_token:
            del self._leases[account_id]

    def get_writer_lease(self, account_id: str = DEFAULT_ACCOUNT_ID) -> WriterLease | None:
        cur = self._leases.get(account_id)
        if not self._lease_alive(cur):
            return None
        return copy.deepcopy(cur)

    def _require_writer(
        self,
        *,
        account_id: str,
        writer_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> None:
        cur = self._leases.get(account_id)
        if not self._lease_alive(cur):
            raise StaleWriterError("lease expired or missing")
        assert cur is not None
        if (
            cur.writer_id != writer_id
            or cur.lease_token != lease_token
            or int(cur.fencing_token) != int(fencing_token)
        ):
            raise StaleWriterError("stale writer rejected")

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
        self._require_writer(
            account_id=account_id,
            writer_id=writer_id,
            lease_token=lease_token,
            fencing_token=fencing_token,
        )
        exec_id = str(trade.execution_id or trade.trade_id)
        seen = self._exec_ids.setdefault(account_id, set())
        if exec_id in seen:
            raise DuplicateExecutionError(exec_id)
        cur_acc = self._accounts.get(account_id)
        if cur_acc is None:
            raise StateConflictError("account missing")
        if int(cur_acc.version) != int(expected_account_version):
            raise StateConflictError(
                f"account version {cur_acc.version} != expected {expected_account_version}"
            )
        # atomic in-memory swap
        new_acc = copy.deepcopy(account)
        new_acc.account_id = account_id
        new_acc.version = int(cur_acc.version) + 1
        new_pos = copy.deepcopy(position)
        new_pos.account_id = account_id
        new_trade = copy.deepcopy(trade)
        new_trade.account_id = account_id
        self._accounts[account_id] = new_acc
        self._positions.setdefault(account_id, {})[new_pos.symbol] = new_pos
        self._trades.setdefault(account_id, []).append(new_trade)
        seen.add(exec_id)
        bucket = self._extras.setdefault(account_id, {})
        if realized_today is not None:
            bucket["realized_today"] = copy.deepcopy(realized_today)
        if closed_today is not None:
            bucket["closed_today"] = copy.deepcopy(closed_today)
        if extras:
            bucket.update(copy.deepcopy(extras))
        return copy.deepcopy(new_acc), copy.deepcopy(new_pos), copy.deepcopy(new_trade)

    def replace_full_state(
        self,
        state: FullPaperState,
        *,
        writer_id: str | None = None,
        lease_token: str | None = None,
        fencing_token: int | None = None,
        require_lease: bool = False,
    ) -> FullPaperState:
        aid = state.account.account_id
        if require_lease:
            if writer_id is None or lease_token is None or fencing_token is None:
                raise StaleWriterError("lease required")
            self._require_writer(
                account_id=aid,
                writer_id=writer_id,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
        self._accounts[aid] = copy.deepcopy(state.account)
        self._positions[aid] = {p.symbol: copy.deepcopy(p) for p in state.positions}
        self._trades[aid] = [copy.deepcopy(t) for t in state.trades]
        self._exec_ids[aid] = {
            str(t.execution_id or t.trade_id) for t in state.trades if t.trade_id
        }
        self._daily[aid] = {
            str(d.trading_session_date)[:10]: copy.deepcopy(d) for d in state.daily
        }
        self._extras[aid] = {
            "realized_today": copy.deepcopy(state.realized_today),
            "closed_today": copy.deepcopy(state.closed_today),
            "slot_queue": copy.deepcopy(state.slot_queue),
            "factor_memory": copy.deepcopy(state.factor_memory),
            "factor2": copy.deepcopy(state.factor2),
            "portfolio_pool": list(state.portfolio_pool),
            **copy.deepcopy(state.runtime_extras),
        }
        return self.load_full_state(aid)
