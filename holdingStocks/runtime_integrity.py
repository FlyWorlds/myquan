"""Runtime ledger integrity checks for paper trading and strategy16.

The checks are read-only. They are meant to catch the class of problems that
are easy to miss in the UI: a trade still present after being voided, strategy
events losing their per-symbol threshold, or simulator state drifting away from
its latest event.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "trades.jsonl"
VOIDED_TRADES = ROOT / "trades.voided.jsonl"
STRATEGY_EVENTS = ROOT / "strategy_signal_events.json"
STRATEGY_STATE = ROOT / "strategy_sim_state.json"

BLOCK_TRADING = "block_trading"
WARNING = "warning"


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    severity: str
    kind: str
    message: str
    detail: dict[str, Any]


def _code(v: Any) -> str:
    return str(v or "").strip().zfill(6)[-6:]


def _float_key(v: Any) -> str:
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return ""


def _int_key(v: Any) -> str:
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return ""


def _trade_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    ts = str(row.get("time") or row.get("ts") or row.get("executed_at") or "")[:19]
    session = str(row.get("session") or ts[:10])
    return (
        session,
        ts,
        _code(row.get("code") or row.get("symbol")),
        str(row.get("side") or "").lower(),
        _float_key(row.get("price")),
        _int_key(row.get("qty")),
    )


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def find_live_void_conflicts(
    *,
    trades_path: Path = TRADES,
    voided_path: Path = VOIDED_TRADES,
) -> list[IntegrityIssue]:
    """Same paper trade must not exist in both live and voided logs."""
    live = _load_jsonl(trades_path)
    voided = _load_jsonl(voided_path)
    live_by_key = {_trade_key(row): row for row in live}
    issues: list[IntegrityIssue] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in voided:
        key = _trade_key(row)
        if key in seen or key not in live_by_key:
            continue
        seen.add(key)
        code = key[2]
        issues.append(
            IntegrityIssue(
                code=code,
                severity=BLOCK_TRADING,
                kind="live_trade_also_voided",
                message=f"{code} 交易同时存在于 live trades 与 voided trades",
                detail={
                    "trade_key": list(key),
                    "voided_reason": row.get("voided_reason") or row.get("void_reason"),
                },
            )
        )
    return issues


def find_strategy16_event_threshold_issues(
    *,
    events_path: Path = STRATEGY_EVENTS,
    start_date: str | None = None,
) -> list[IntegrityIssue]:
    """strategy16 BUY events should carry entry_pct unless it is resolvable.

    The production rule is: strategy16 threshold table first, DEFAULT_PCT as the
    final fallback. Therefore a historical event missing entry_pct is not by
    itself an issue when the project can still resolve the strategy threshold.
    """
    try:
        from watch_config import DEFAULT_PCT, load_strategy16_thr_map
    except ImportError:  # pragma: no cover
        from holdingStocks.watch_config import DEFAULT_PCT, load_strategy16_thr_map

    thrs = load_strategy16_thr_map()
    raw = _load_json(events_path, {})
    events = raw.get("events") if isinstance(raw, dict) else []
    if not isinstance(events, list):
        return []
    issues: list[IntegrityIssue] = []
    seen: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("strategy_id") or "") != "strategy16":
            continue
        if str(ev.get("side") or "").upper() != "BUY":
            continue
        session = str(ev.get("trading_session_date") or ev.get("trigger_time") or "")[:10]
        if start_date and session and session < str(start_date)[:10]:
            continue
        code = _code(ev.get("symbol"))
        raw_pct = ev.get("entry_pct")
        try:
            pct = float(raw_pct)
        except (TypeError, ValueError):
            pct = 0.0
        if pct > 0:
            continue
        resolved = thrs.get(code, DEFAULT_PCT)
        try:
            if float(resolved) > 0:
                continue
        except (TypeError, ValueError):
            pass
        event_id = str(ev.get("event_id") or f"{code}:{session}:{ev.get('trigger_time')}")
        if event_id in seen:
            continue
        seen.add(event_id)
        issues.append(
            IntegrityIssue(
                code=code,
                severity=WARNING,
                kind="strategy16_buy_missing_entry_pct",
                message=f"{code} 策略16 BUY 事件缺少 entry_pct，后续可能被默认阈值误读",
                detail={
                    "event_id": ev.get("event_id"),
                    "trigger_time": ev.get("trigger_time"),
                    "trigger_price": ev.get("trigger_price"),
                    "buy_level": ev.get("buy_level"),
                },
            )
        )
    return issues


def find_strategy_state_event_drift(
    *,
    state_path: Path = STRATEGY_STATE,
    events_path: Path = STRATEGY_EVENTS,
) -> list[IntegrityIssue]:
    """LONG simulator state should align with its latest strategy16 BUY event."""
    raw_state = _load_json(state_path, {})
    books = raw_state.get("books") if isinstance(raw_state, dict) else {}
    if not isinstance(books, dict):
        return []
    raw_events = _load_json(events_path, {})
    events = raw_events.get("events") if isinstance(raw_events, dict) else []
    if not isinstance(events, list):
        events = []

    latest_buy: dict[str, dict[str, Any]] = {}
    latest_side: dict[str, str] = {}
    for ev in events:
        if not isinstance(ev, dict) or str(ev.get("strategy_id") or "") != "strategy16":
            continue
        code = _code(ev.get("symbol"))
        side = str(ev.get("side") or "").upper()
        latest_side[code] = side
        if side == "BUY":
            latest_buy[code] = ev

    issues: list[IntegrityIssue] = []
    for key, book in books.items():
        if not isinstance(book, dict) or str(book.get("strategy_id") or "") != "strategy16":
            continue
        code = _code(book.get("symbol") or key)
        if str(book.get("state") or "").upper() != "LONG":
            continue
        ev = latest_buy.get(code)
        if not ev:
            issues.append(
                IntegrityIssue(
                    code=code,
                    severity=WARNING,
                    kind="long_state_without_buy_event",
                    message=f"{code} 模拟器 LONG 状态找不到对应 BUY 事件",
                    detail={"book_key": key, "entry_price": book.get("entry_price")},
                )
            )
            continue
        if latest_side.get(code) == "SELL":
            issues.append(
                IntegrityIssue(
                    code=code,
                    severity=WARNING,
                    kind="long_state_after_latest_sell",
                    message=f"{code} 模拟器仍为 LONG，但最近事件为 SELL",
                    detail={"book_key": key, "entry_price": book.get("entry_price")},
                )
            )
            continue
        try:
            entry = float(book.get("entry_price") or 0)
            trigger = float(ev.get("trigger_price") or 0)
        except (TypeError, ValueError):
            entry = trigger = 0.0
        if entry > 0 and trigger > 0 and abs(entry - trigger) > 0.01:
            issues.append(
                IntegrityIssue(
                    code=code,
                    severity=WARNING,
                    kind="long_entry_event_price_mismatch",
                    message=f"{code} 模拟器入场价与最新 BUY 事件价不一致",
                    detail={
                        "book_key": key,
                        "entry_price": book.get("entry_price"),
                        "event_trigger_price": ev.get("trigger_price"),
                        "event_id": ev.get("event_id"),
                    },
                )
            )
    return issues


def run_integrity_checks(
    *,
    root: Path = ROOT,
    strategy16_start_date: str | None = None,
) -> list[IntegrityIssue]:
    return [
        *find_live_void_conflicts(
            trades_path=root / "trades.jsonl",
            voided_path=root / "trades.voided.jsonl",
        ),
        *find_strategy16_event_threshold_issues(
            events_path=root / "strategy_signal_events.json",
            start_date=strategy16_start_date,
        ),
        *find_strategy_state_event_drift(
            state_path=root / "strategy_sim_state.json",
            events_path=root / "strategy_signal_events.json",
        ),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT, help="holdingStocks runtime directory")
    ap.add_argument("--strategy16-start-date", default=None)
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = ap.parse_args()

    issues = run_integrity_checks(
        root=args.root,
        strategy16_start_date=args.strategy16_start_date,
    )
    payload = [asdict(x) for x in issues]
    if args.json:
        print(json.dumps({"ok": not issues, "issues": payload}, ensure_ascii=False, indent=2))
    elif not issues:
        print("runtime integrity ok")
    else:
        for item in payload:
            print(f"[{item['severity']}] {item['kind']} {item['code']}: {item['message']}")
            print(json.dumps(item["detail"], ensure_ascii=False, sort_keys=True))
    return 1 if any(x.severity == BLOCK_TRADING for x in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
