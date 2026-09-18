"""Real-minute replay parity for legacy paper exit vs ExitDecisionEngine.

This is a read-only decision comparison.  It never calls paper execution,
changes positions, writes a ledger, or enables USE_UNIFIED_EXIT_ENGINE.

Minute OHLC and entry events come from the existing strategy1_pool_1m replay.
For every held minute, both exit orchestrators receive the exact same context.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HOLDING = ROOT / "holdingStocks"
for path in (ROOT, HOLDING):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backtest.exit_decision_replay.catalog import normalize_rule_id  # noqa: E402
from backtest.exit_decision_replay.harness import (  # noqa: E402
    HoldingInterval,
    accumulate_row,
    holding_intervals,
    iter_symbol_evaluations,
    row_in_window,
    row_matches_rule,
)
from backtest.strategy1_pool_1m.run import (  # noqa: E402
    POOL_STRATEGY1,
    _daily,
    _load_pool,
    _minutes,
    _sina,
)
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
)

OUT = Path(__file__).resolve().parent
CORPUS = OUT / "corpus"


def load_corpus(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("cases") or [])


def _corpus_keys(cases: list[dict[str, Any]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for case in cases:
        symbol = str(case.get("symbol") or "").zfill(6)
        ts = str(case.get("timestamp") or "")
        if symbol and ts:
            keys.add((symbol, ts[:19]))
    return keys


def replay_symbol(
    *,
    code: str,
    daily: pd.DataFrame,
    minutes: pd.DataFrame,
    entry_pct: float,
    pullback_pct: float,
    days: int,
    rule: str | None = None,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    corpus_keys: set[tuple[str, str]] | None = None,
) -> tuple[Counter[str], list[dict[str, Any]]]:
    """Replay holding windows for one symbol, optionally filtered by rule/date/corpus."""
    totals: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    intervals_seen = 0
    last_interval = 0
    for row in iter_symbol_evaluations(
        code=code,
        daily=daily,
        minutes=minutes,
        entry_pct=entry_pct,
        pullback_pct=pullback_pct,
        days=days,
    ):
        last_interval = max(last_interval, row.interval_no)
        if not row_in_window(row, symbol=code, date=date, start=start, end=end):
            continue
        if rule and not row_matches_rule(row, rule):
            continue
        if corpus_keys is not None:
            key = (str(row.symbol).zfill(6), row.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
            if key not in corpus_keys:
                continue
        mismatch = accumulate_row(totals, row)
        if mismatch is not None:
            mismatches.append(mismatch)
        intervals_seen = last_interval

    totals["symbols_with_intervals"] = int(last_interval > 0)
    totals["holding_intervals"] = last_interval if intervals_seen or last_interval else 0
    if last_interval:
        totals["holding_intervals"] = last_interval
        totals["symbols_with_intervals"] = 1
    else:
        totals["symbols_with_intervals"] = 0
        totals["holding_intervals"] = 0
    return totals, mismatches


def run_replay(
    *,
    days: int,
    pool: str,
    source: str,
    refresh: bool,
    max_symbols: int | None = None,
    output_dir: Path = OUT,
    rule: str | None = None,
    symbol: str | None = None,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    rows = _load_pool(pool)
    if symbol:
        want = str(symbol).zfill(6)
        rows = [item for item in rows if str(item.get("code") or "").zfill(6) == want]
    if max_symbols is not None:
        rows = rows[: max(0, int(max_symbols))]
    corpus_keys = _corpus_keys(load_corpus(corpus)) if corpus else None
    rule_id = normalize_rule_id(rule) if rule else None
    totals: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []

    for item in rows:
        code = str(item.get("code") or "").zfill(6)
        sina = str(item.get("sina") or _sina(code)).lower()
        entry_pct = float(item.get("entry_pct") or item.get("pct") or DEFAULT_ENTRY_PCT)
        pullback_pct = float(
            item.get("stop_pct") or item.get("pct") or DEFAULT_PULLBACK_PCT
        )
        daily = _daily(sina)
        minutes = _minutes(sina, refresh=refresh, days=days, source=source)
        symbol_totals, symbol_mismatches = replay_symbol(
            code=code,
            daily=daily,
            minutes=minutes,
            entry_pct=entry_pct,
            pullback_pct=pullback_pct,
            days=days,
            rule=rule_id,
            date=date,
            start=start,
            end=end,
            corpus_keys=corpus_keys,
        )
        totals.update(symbol_totals)
        mismatches.extend(symbol_mismatches)
        symbols.append(
            {
                "symbol": code,
                "minute_rows": len(minutes),
                "minute_start": (
                    str(pd.to_datetime(minutes["ts"]).min())
                    if not minutes.empty and "ts" in minutes
                    else None
                ),
                "minute_end": (
                    str(pd.to_datetime(minutes["ts"]).max())
                    if not minutes.empty and "ts" in minutes
                    else None
                ),
                **dict(symbol_totals),
            }
        )
        print(
            f"{code}: rows={len(minutes)} eval={symbol_totals['evaluations']} "
            f"sell={symbol_totals['legacy_sell']} mismatch={symbol_totals['mismatch']}",
            flush=True,
        )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_shadow_replay",
        "market_data": source,
        "position_source": "factor26_1m_replay_generated_entries",
        "paper_execution": False,
        "use_unified_exit_engine": False,
        "shadow_unified_exit_engine": False,
        "days": int(days),
        "pool": pool,
        "rule": rule_id,
        "symbol_filter": str(symbol).zfill(6) if symbol else None,
        "date": date,
        "start": start,
        "end": end,
        "corpus": str(corpus) if corpus else None,
        "symbols_requested": len(rows),
        "symbols": symbols,
        "totals": dict(totals),
        "mismatch_classes": {
            "A": "quantity semantics / potential bug",
            "B": "known design difference",
            "C": "context missing",
            "D": "rule order",
            "E": "price semantics",
            "F": "legacy special/show semantics",
            "G": "unknown",
        },
        "limitations": [
            "Real minute OHLC with replay-generated positions; not a historical paper-ledger replay.",
            "AKShare source is limited to its currently available recent minute window.",
            "Both engines receive identical normalized DecisionContext inputs.",
            "Coverage-driven filters (--rule/--corpus) still walk bars to rebuild peak/working_stop.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "replay_mismatches.json").write_text(
        json.dumps(mismatches, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only real-minute Legacy vs Unified exit parity replay"
    )
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--pool", default=POOL_STRATEGY1)
    parser.add_argument("--source", choices=("ak", "auto", "panda"), default="ak")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--rule", default=None, help="WORKING_STOP / OPEN_PROTECT / PATH / ...")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--date", default=None, help="Single session YYYY-MM-DD")
    parser.add_argument("--start", default=None, help="Inclusive session YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Inclusive session YYYY-MM-DD")
    parser.add_argument("--corpus", type=Path, default=None)
    args = parser.parse_args()
    result = run_replay(
        days=args.days,
        pool=args.pool,
        source=args.source,
        refresh=args.refresh,
        max_symbols=args.max_symbols,
        output_dir=args.output_dir,
        rule=args.rule,
        symbol=args.symbol,
        date=args.date,
        start=args.start,
        end=args.end,
        corpus=args.corpus,
    )
    print(json.dumps(result["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
