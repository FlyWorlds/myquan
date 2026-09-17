"""纸面买卖明细账本（JSON 文件，代替数据库）。

每笔买入入槽、卖出平仓（含半仓）写入 ``trade_ledger.json``，供交割单页查询。
字段含：代码/名称/方向/价格/仓位/金额/单笔盈亏/账户余额/买卖理由。
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LEDGER_FILE = ROOT / "trade_ledger.json"
_LOCK = threading.RLock()


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _code_key(code: str) -> str:
    return str(code or "").strip().zfill(6)[-6:]


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def empty_ledger() -> dict[str, Any]:
    return {"updated_at": None, "entries": []}


def load_ledger() -> dict[str, Any]:
    with _LOCK:
        if not LEDGER_FILE.is_file():
            return empty_ledger()
        try:
            raw = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return empty_ledger()
        if not isinstance(raw, dict):
            return empty_ledger()
        entries = raw.get("entries")
        if not isinstance(entries, list):
            raw["entries"] = []
        return raw


def save_ledger(data: dict[str, Any]) -> None:
    with _LOCK:
        data["updated_at"] = _now()
        tmp = LEDGER_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(LEDGER_FILE)


def _reason_text(side: str, note: str, reason: str = "") -> str:
    text = str(note or reason or "").strip()
    if text:
        return text
    return "买入入槽" if side == "buy" else "卖出平仓"


def _raw_account_cash(holdings: dict[str, Any] | None) -> float | None:
    """允许负现金（_as_money 会把 ≤0 当成无）。"""
    if not isinstance(holdings, dict):
        return None
    return _as_float(holdings.get("account_cash"))


def build_ledger_entry(
    record: dict[str, Any],
    *,
    holdings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 trades 行 + 账本快照拼交割单字段。"""
    side = str(record.get("side") or "").strip().lower()
    if side in ("买", "买入"):
        side = "buy"
    elif side in ("卖", "卖出", "stop"):
        side = "sell"
    code = _code_key(str(record.get("code") or ""))
    price = _as_float(record.get("price")) or 0.0
    qty = int(record.get("qty") or 0)
    amount = round(price * qty, 2) if price > 0 and qty > 0 else 0.0
    cost = _as_float(record.get("cost") or record.get("avg_cost"))
    pnl = _as_float(record.get("pnl"))
    pnl_pct = _as_float(record.get("pnl_pct"))
    if side == "sell" and pnl is None and cost is not None and cost > 0 and qty > 0:
        pnl = round((price - cost) * qty, 2)
        pnl_pct = round((price / cost - 1.0) * 100.0, 2)
    day_pnl = _as_float(record.get("day_pnl"))
    day_pnl_pct = _as_float(record.get("day_pnl_pct"))
    cash_after = _as_float(record.get("account_cash_after"))
    if cash_after is None:
        cash_after = _raw_account_cash(holdings)
    note = str(record.get("note") or "")
    reason = str(record.get("reason") or "")
    ts = str(record.get("time") or _now())
    return {
        "id": str(record.get("id") or uuid.uuid4().hex[:12]),
        "time": ts,
        "session": str(record.get("session") or ts[:10]),
        "side": side,
        "code": code,
        "name": str(record.get("name") or code),
        "market": str(record.get("market") or ""),
        "price": round(price, 4) if price else 0.0,
        "qty": qty,
        "after_qty": int(record.get("after_qty") or 0),
        "amount": amount,
        "cost": None if cost is None else round(cost, 4),
        "pnl": None if pnl is None else round(pnl, 2),
        "pnl_pct": None if pnl_pct is None else round(pnl_pct, 2),
        "day_pnl": None if day_pnl is None else round(day_pnl, 2),
        "day_pnl_pct": None if day_pnl_pct is None else round(day_pnl_pct, 2),
        "account_cash_after": None if cash_after is None else round(cash_after, 2),
        "action_kind": str(record.get("action_kind") or ""),
        "buy_time": str(record.get("buy_time") or "") or None,
        "reason": _reason_text(side, note, reason),
        "reason_detail": str(record.get("reason_detail") or note or reason or ""),
        "note": note,
    }


def record_trade_ledger(
    record: dict[str, Any],
    *,
    holdings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一笔买卖明细。"""
    if holdings is None:
        try:
            from index import load_holdings

            holdings = load_holdings()
        except Exception:  # noqa: BLE001
            holdings = None
    entry = build_ledger_entry(record, holdings=holdings)
    if not entry.get("code") or entry.get("qty", 0) <= 0:
        return entry
    with _LOCK:
        data = load_ledger()
        data.setdefault("entries", []).append(entry)
        save_ledger(data)
    return entry


def list_ledger_entries(
    *,
    code: str | None = None,
    session: str | None = None,
    side: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    data = load_ledger()
    rows = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
    if code:
        ck = _code_key(code)
        rows = [e for e in rows if _code_key(str(e.get("code") or "")) == ck]
    if session:
        sess = str(session)[:10]
        rows = [e for e in rows if str(e.get("session") or "")[:10] == sess]
    if side:
        sl = str(side).strip().lower()
        rows = [e for e in rows if str(e.get("side") or "").lower() == sl]
    rows = list(reversed(rows))  # 新→旧
    total = len(rows)
    lim = max(1, min(int(limit or 500), 2000))
    off = max(0, int(offset or 0))
    page = rows[off : off + lim]
    buy_amt = sum(float(e.get("amount") or 0) for e in rows if e.get("side") == "buy")
    sell_amt = sum(float(e.get("amount") or 0) for e in rows if e.get("side") == "sell")
    sell_pnl = sum(float(e.get("pnl") or 0) for e in rows if e.get("side") == "sell")
    return {
        "updated_at": data.get("updated_at"),
        "total": total,
        "offset": off,
        "limit": lim,
        "summary": {
            "buy_amount": round(buy_amt, 2),
            "sell_amount": round(sell_amt, 2),
            "sell_pnl": round(sell_pnl, 2),
            "count": total,
        },
        "entries": page,
    }


def backfill_from_trades_jsonl(
    trades_path: Path | None = None,
    *,
    force: bool = False,
) -> int:
    """从 trades.jsonl 冷启动灌入（账本为空或 force）。"""
    path = trades_path or (ROOT / "trades.jsonl")
    with _LOCK:
        data = load_ledger()
        if (data.get("entries") or []) and not force:
            return 0
        if not path.is_file():
            return 0
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            # 纠账备注行仍保留，便于审计
            entries.append(build_ledger_entry(rec, holdings=None))
        data["entries"] = entries
        data["backfilled_from"] = str(path.name)
        data["backfilled_at"] = _now()
        save_ledger(data)
        return len(entries)


def api_trades_payload(query: str) -> tuple[int, dict[str, Any]]:
    """解析 ``/api/trades?...`` 查询串。"""
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(query).query)
    code = (qs.get("code") or [None])[0]
    session = (qs.get("session") or [None])[0]
    side = (qs.get("side") or [None])[0]
    try:
        limit = int((qs.get("limit") or ["200"])[0])
    except (TypeError, ValueError):
        limit = 200
    try:
        offset = int((qs.get("offset") or ["0"])[0])
    except (TypeError, ValueError):
        offset = 0
    # 首次空账本自动灌入
    backfill_from_trades_jsonl()
    return 200, list_ledger_entries(
        code=code,
        session=session,
        side=side,
        limit=limit,
        offset=offset,
    )
