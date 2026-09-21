"""Local JSON adapter — migration / test / local fallback (not multi-writer production)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from paper_state.errors import RemoteUnavailableError
from paper_state.memory import MemoryPaperStateAdapter
from paper_state.models import (
    AccountSnapshot,
    DailyState,
    FullPaperState,
    PaperTrade,
    PositionRecord,
)
from paper_state.port import DEFAULT_ACCOUNT_ID


def _code_key(code: str) -> str:
    return str(code or "").strip().zfill(6)[-6:]


def holdings_to_full_state(
    holdings: dict[str, Any],
    *,
    trades_rows: list[dict[str, Any]] | None = None,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> FullPaperState:
    """Map current holdings.json (+ optional trades.jsonl rows) → FullPaperState."""
    sess = str(
        holdings.get("account_total_open_session")
        or holdings.get("last_session")
        or ""
    )[:10] or None
    account = AccountSnapshot(
        account_id=account_id,
        paper_equity_base=_as_float(holdings.get("paper_equity_base")),
        account_cash=_as_float(holdings.get("account_cash")),
        account_total=_as_float(holdings.get("account_total")),
        account_total_open=_as_float(holdings.get("account_total_open")),
        account_total_open_session=sess,
        trading_session_date=sess,
        last_session=str(holdings.get("last_session") or "")[:10] or None,
        paper_pnl_start=str(holdings.get("paper_pnl_start") or "") or None,
        version=1,
        updated_at=str(holdings.get("updated_at") or "") or None,
        extra={
            "updated_host": holdings.get("updated_host"),
            "watch_status_reset_session": holdings.get("watch_status_reset_session"),
        },
    )
    positions: list[PositionRecord] = []
    raw_pos = holdings.get("positions") or {}
    if isinstance(raw_pos, dict):
        for code, pos in raw_pos.items():
            if not isinstance(pos, dict):
                continue
            positions.append(
                PositionRecord(
                    account_id=account_id,
                    symbol=_code_key(str(code)),
                    qty=int(pos.get("qty") or 0),
                    available=_as_int(pos.get("available")),
                    cost=_as_float(pos.get("cost")),
                    today_cost=_as_float(pos.get("today_cost")),
                    buy_time=str(pos.get("buy_time") or "") or None,
                    name=str(pos.get("name") or ""),
                    market=str(pos.get("market") or ""),
                    note=str(pos.get("note") or ""),
                    peak_high=_as_float(pos.get("peak_high")),
                    overnight_peak=_as_float(pos.get("overnight_peak")),
                    overnight_peak_session=str(pos.get("overnight_peak_session") or "")
                    or None,
                    stop_noted=bool(pos.get("stop_noted")),
                    stop_noted_px=_as_float(pos.get("stop_noted_px")),
                    stop_noted_session=str(pos.get("stop_noted_session") or "") or None,
                    tp_stage=int(pos.get("tp_stage") or 0),
                    last_tp_ts=str(pos.get("last_tp_ts") or "") or None,
                    version=1,
                    extra={k: v for k, v in pos.items() if k not in _POS_KNOWN},
                )
            )
    trades: list[PaperTrade] = []
    for i, rec in enumerate(trades_rows or []):
        if not isinstance(rec, dict):
            continue
        side = str(rec.get("side") or "").lower()
        if side in ("买", "买入"):
            side = "buy"
        elif side in ("卖", "卖出", "stop"):
            side = "sell"
        if side not in ("buy", "sell"):
            continue
        code = _code_key(str(rec.get("code") or ""))
        if not code:
            continue
        ts = str(rec.get("time") or rec.get("ts") or "")
        sess_t = str(rec.get("session") or ts)[:10]
        tid = str(rec.get("id") or f"local-{sess_t}-{side}-{code}-{i}")
        trades.append(
            PaperTrade(
                trade_id=tid,
                account_id=account_id,
                symbol=code,
                side=side,
                qty=int(rec.get("qty") or 0),
                fill_price=float(rec.get("price") or 0),
                trading_session_date=sess_t,
                executed_at=ts or sess_t,
                execution_id=str(rec.get("execution_id") or tid),
                cost_basis=_as_float(rec.get("cost") or rec.get("avg_cost")),
                realized_pnl=_as_float(rec.get("pnl")),
                reason_code=str(rec.get("reason") or ""),
                strategy_id=str(rec.get("strategy_id") or ""),
                note=str(rec.get("note") or ""),
                after_qty=_as_int(rec.get("after_qty")),
                payload=dict(rec),
            )
        )
    daily: list[DailyState] = []
    settlements = holdings.get("daily_settlements") or {}
    if isinstance(settlements, dict):
        for day, payload in settlements.items():
            if not isinstance(payload, dict):
                continue
            daily.append(
                DailyState(
                    account_id=account_id,
                    trading_session_date=str(day)[:10],
                    opening_equity=_as_float(payload.get("account_open")),
                    closing_equity=_as_float(
                        payload.get("closing_equity") or payload.get("account_total")
                    ),
                    settled=bool(payload.get("final") or payload.get("settled")),
                    settled_at=str(payload.get("settled_at") or "") or None,
                    payload=dict(payload),
                )
            )
    return FullPaperState(
        account=account,
        positions=positions,
        trades=trades,
        daily=daily,
        realized_today=dict(holdings.get("realized_today") or {}),
        closed_today=dict(holdings.get("closed_today") or {}),
        slot_queue=dict(holdings.get("slot_queue") or {}),
        factor_memory=dict(holdings.get("factor_memory") or {}),
        factor2=dict(holdings.get("factor2") or {}),
        portfolio_pool=[
            _code_key(str(c)) for c in (holdings.get("portfolio_pool") or [])
        ],
        runtime_extras={
            "alert_sticky": holdings.get("alert_sticky"),
            "strategy": holdings.get("strategy"),
        },
    )


_POS_KNOWN = frozenset(
    {
        "qty",
        "available",
        "cost",
        "today_cost",
        "buy_time",
        "name",
        "market",
        "note",
        "peak_high",
        "overnight_peak",
        "overnight_peak_session",
        "stop_noted",
        "stop_noted_px",
        "stop_noted_session",
        "tp_stage",
        "last_tp_ts",
        "code",
    }
)


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def state_content_hash(state: FullPaperState) -> str:
    """Stable hash for migration verification (order-normalized)."""
    blob = {
        "account": {
            "cash": state.account.account_cash,
            "open": state.account.account_total_open,
            "base": state.account.paper_equity_base,
            "session": state.account.trading_session_date,
        },
        "positions": sorted(
            [
                {
                    "s": p.symbol,
                    "q": p.qty,
                    "c": p.cost,
                    "bt": p.buy_time,
                    "ph": p.peak_high,
                    "op": p.overnight_peak,
                    "sn": p.stop_noted,
                    "snp": p.stop_noted_px,
                    "tp": p.tp_stage,
                }
                for p in state.positions
                if int(p.qty or 0) > 0
            ],
            key=lambda x: x["s"],
        ),
        "trades": sorted(
            [
                {
                    "id": t.trade_id,
                    "s": t.symbol,
                    "side": t.side,
                    "q": t.qty,
                    "px": t.fill_price,
                    "d": t.trading_session_date,
                }
                for t in state.trades
            ],
            key=lambda x: (x["d"], x["id"]),
        ),
        "realized": sorted((state.realized_today or {}).keys()),
    }
    raw = json.dumps(blob, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class LocalJsonPaperStateAdapter(MemoryPaperStateAdapter):
    """Read local holdings.json / trades.jsonl into memory port; writes stay in-memory unless export.

    Multi-writer production must NOT use this backend.
    Network failure on postgres must NOT fall back to mutating these files.
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = Path(root)
        self.holdings_path = self.root / "holdings.json"
        self.trades_path = self.root / "trades.jsonl"
        self._hydrate()

    def backend_name(self) -> str:
        return "local_json"

    def health(self) -> dict[str, Any]:
        return {
            "ok": self.holdings_path.is_file(),
            "backend": "local_json",
            "detail": str(self.holdings_path),
            "multi_writer_safe": False,
        }

    def _hydrate(self) -> None:
        if not self.holdings_path.is_file():
            return
        holdings = json.loads(self.holdings_path.read_text(encoding="utf-8"))
        trades_rows: list[dict[str, Any]] = []
        if self.trades_path.is_file():
            for line in self.trades_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    trades_rows.append(rec)
        state = holdings_to_full_state(holdings, trades_rows=trades_rows)
        self.replace_full_state(state, require_lease=False)

    def assert_no_local_fallback_write(self) -> None:
        """Explicit guard for NETWORK_FAILURE_NO_LOCAL_WRITE tests."""
        raise RemoteUnavailableError(
            "REMOTE_STATE_UNAVAILABLE: local JSON fallback write is forbidden"
        )
