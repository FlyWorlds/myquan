"""Export a strategy16 reconciliation CSV.

The report joins four surfaces when available:
  1. UI snapshot row (sell level / paper status)
  2. paper trades.jsonl decision rows
  3. strategy simulator events
  4. factor26 1m replay from already-available snapshot fields

It is deliberately read-only and avoids fetching remote market data.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WATCH_META = ROOT / "holdings_watch.json"
EVENTS = ROOT / "strategy_signal_events.json"
TRADES = ROOT / "trades.jsonl"
OUT = ROOT / "runs" / "strategy16_reconcile_sample.csv"


def _code(v: Any) -> str:
    return str(v or "").strip().zfill(6)[-6:]


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
        try:
            row = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _snapshot_rows(snap: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("strategyRows", "rows", "watchRows", "holdings"):
        vals = snap.get(key)
        if isinstance(vals, list):
            rows.extend([x for x in vals if isinstance(x, dict)])
    tabs = snap.get("strategyTabs")
    if isinstance(tabs, list):
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            vals = tab.get("rows") or tab.get("picks")
            if isinstance(vals, list):
                rows.extend([x for x in vals if isinstance(x, dict)])
    return rows


def build_report(*, sample: int = 10, out_path: Path = OUT) -> Path:
    snap = _load_json(WATCH_META, {})
    events_raw = _load_json(EVENTS, {})
    events = [e for e in events_raw.get("events", []) if isinstance(e, dict)] if isinstance(events_raw, dict) else []
    trades = _load_jsonl(TRADES)

    rows_by_code: dict[str, dict[str, Any]] = {}
    for row in _snapshot_rows(snap if isinstance(snap, dict) else {}):
        code = _code(row.get("代码") or row.get("code") or row.get("symbol"))
        if code and code != "000000":
            rows_by_code.setdefault(code, row)

    recent_events = [
        e for e in events if str(e.get("strategy_id") or "") == "strategy16"
    ][-max(1, sample * 3) :]
    codes: list[str] = []
    for e in reversed(recent_events):
        c = _code(e.get("symbol"))
        if c and c not in codes:
            codes.append(c)
        if len(codes) >= sample:
            break
    for c in rows_by_code:
        if len(codes) >= sample:
            break
        if c not in codes:
            codes.append(c)

    trades_by_code: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        c = _code(t.get("code") or t.get("symbol") or t.get("证券代码"))
        if c:
            trades_by_code.setdefault(c, []).append(t)

    event_by_code: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        c = _code(e.get("symbol"))
        if c:
            event_by_code.setdefault(c, []).append(e)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "code",
        "name",
        "ui_sell_level",
        "ui_buy_level",
        "ui_status",
        "paper_last_side",
        "paper_last_time",
        "paper_last_reason",
        "sim_last_side",
        "sim_last_time",
        "sim_last_price",
        "sim_execution_model",
        "factor26_replay_side",
        "factor26_replay_px",
        "factor26_replay_note",
        "reconcile_note",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in codes:
            row = rows_by_code.get(c, {})
            paper = (trades_by_code.get(c) or [{}])[-1]
            sim = (event_by_code.get(c) or [{}])[-1]
            # Snapshot rows currently expose replay comparison status but not the whole 1m trace.
            replay_side = row.get("策略回放触发侧") or row.get("last_trigger_side")
            replay_px = row.get("策略回放触发价") or row.get("last_trigger_px")
            note = "ok"
            if not row:
                note = "missing_ui_snapshot_row"
            elif not replay_side and not replay_px:
                note = "missing_factor26_replay_fields_or_minutes"
            w.writerow(
                {
                    "code": c,
                    "name": row.get("名称") or row.get("name") or paper.get("name") or "",
                    "ui_sell_level": row.get("卖出侧价") or row.get("止损") or "",
                    "ui_buy_level": row.get("买点") or row.get("买入侧价") or "",
                    "ui_status": row.get("持仓状态") or row.get("策略状态") or "",
                    "paper_last_side": paper.get("side") or paper.get("type") or "",
                    "paper_last_time": paper.get("time") or paper.get("ts") or paper.get("executed_at") or "",
                    "paper_last_reason": paper.get("reason") or paper.get("reason_code") or paper.get("note") or "",
                    "sim_last_side": sim.get("side") or "",
                    "sim_last_time": sim.get("trigger_time") or "",
                    "sim_last_price": sim.get("trigger_price") or "",
                    "sim_execution_model": sim.get("execution_model") or "",
                    "factor26_replay_side": replay_side or "",
                    "factor26_replay_px": replay_px or "",
                    "factor26_replay_note": row.get("策略回放说明") or "",
                    "reconcile_note": note,
                }
            )
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    path = build_report(sample=args.sample, out_path=args.out)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
