"""Find historical exit-rule candidates from existing 1m replay holdings.

Does not change exit rules or construct prices. Candidates are bars where a
rule's signal is on; the winner may still be a higher-priority rule.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HOLDING = ROOT / "holdingStocks"
for path in (ROOT, HOLDING):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backtest.exit_decision_replay.catalog import normalize_rule_id  # noqa: E402
from backtest.exit_decision_replay.harness import (  # noqa: E402
    candidate_payload,
    is_rule_candidate,
    iter_symbol_evaluations,
    row_in_window,
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

CORPUS_NAME = {
    "WORKING_STOP": "working_stop.json",
    "OPEN_PROTECT": "open_protect.json",
    "PATH": "factor26.json",
    "PATH_HALF": "half_position.json",
    "T1_BLOCK": "t1_block.json",
}


def find_cases(
    *,
    rule: str,
    days: int,
    pool: str,
    source: str,
    refresh: bool,
    max_symbols: int | None = None,
    symbol: str | None = None,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    winners_only: bool = False,
) -> dict[str, Any]:
    rid = normalize_rule_id(rule)
    rows = _load_pool(pool)
    if symbol:
        want = str(symbol).zfill(6)
        rows = [item for item in rows if str(item.get("code") or "").zfill(6) == want]
    if max_symbols is not None:
        rows = rows[: max(0, int(max_symbols))]

    cases: list[dict[str, Any]] = []
    scanned = 0
    for item in rows:
        code = str(item.get("code") or "").zfill(6)
        sina = str(item.get("sina") or _sina(code)).lower()
        entry_pct = float(item.get("entry_pct") or item.get("pct") or DEFAULT_ENTRY_PCT)
        pullback_pct = float(
            item.get("stop_pct") or item.get("pct") or DEFAULT_PULLBACK_PCT
        )
        daily = _daily(sina)
        minutes = _minutes(sina, refresh=refresh, days=days, source=source)
        for row in iter_symbol_evaluations(
            code=code,
            daily=daily,
            minutes=minutes,
            entry_pct=entry_pct,
            pullback_pct=pullback_pct,
            days=days,
        ):
            scanned += 1
            if not row_in_window(row, symbol=code, date=date, start=start, end=end):
                continue
            if not is_rule_candidate(row, rid):
                continue
            if winners_only:
                if rid == "PATH_HALF" and row.winner_rule != "PATH_HALF":
                    continue
                if rid == "PATH" and row.winner_rule not in ("PATH", "PATH_HALF"):
                    continue
                if rid not in ("PATH", "PATH_HALF") and row.winner_rule != rid:
                    continue
            cases.append(candidate_payload(row, rid))
        print(f"{code}: scanned, candidates so far={len(cases)}", flush=True)

    cases = _keep_event_oriented(cases, rule_id=rid)
    return _payload_from_cases(
        rid=rid,
        cases=cases,
        scanned=scanned,
        days=days,
        pool=pool,
        source=source,
    )


SCAN_RULES = ("WORKING_STOP", "OPEN_PROTECT", "PATH", "PATH_HALF", "T1_BLOCK")


def _payload_from_cases(
    *,
    rid: str,
    cases: list[dict[str, Any]],
    scanned: int,
    days: int,
    pool: str,
    source: str,
) -> dict[str, Any]:
    winners = [c for c in cases if c.get("winner_rule") == rid]
    if rid == "PATH_HALF":
        winners = [
            c
            for c in cases
            if c.get("winner_rule") == "PATH_HALF"
            or c.get("quantity_ratio_legacy") == 0.5
        ]
    sells = [c for c in cases if c.get("legacy_action") == "SELL"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_id": rid,
        "evidence_grade": "historical",
        "source": "factor26_1m_replay_generated_entries",
        "market_data": source,
        "days": int(days),
        "pool": pool,
        "evaluations_scanned": scanned,
        "candidate_count": len(cases),
        "winner_count": len(winners),
        "sell_count": len(sells),
        "paper_execution": False,
        "use_unified_exit_engine": False,
        "note": (
            "Candidates are historical bars where the rule signal is on. "
            "A higher-priority rule may still win. Prices are not synthesized."
        ),
        "cases": cases,
    }


def _keep_event_oriented(
    cases: list[dict[str, Any]],
    *,
    rule_id: str | None = None,
) -> list[dict[str, Any]]:
    """Keep all SELL/winners; for idle or T1_BLOCK keep first bar per symbol+date."""
    out: list[dict[str, Any]] = []
    seen_idle: set[tuple[str, str]] = set()
    t1 = rule_id == "T1_BLOCK"
    for case in cases:
        sell = case.get("legacy_action") == "SELL"
        winner = case.get("winner_rule") == case.get("expected_rule")
        half_win = case.get("winner_rule") == "PATH_HALF"
        rare = bool((case.get("signals") or {}).get("path"))
        if (sell or winner or half_win) and not t1:
            out.append(case)
            continue
        if t1 and rare:
            out.append(case)
            continue
        key = (str(case.get("symbol")), str(case.get("date")))
        if key in seen_idle:
            continue
        seen_idle.add(key)
        out.append(case)
    return out


def find_all_cases(
    *,
    days: int,
    pool: str,
    source: str,
    refresh: bool,
    max_symbols: int | None = None,
    symbol: str | None = None,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    winners_only: bool = False,
) -> dict[str, dict[str, Any]]:
    rows = _load_pool(pool)
    if symbol:
        want = str(symbol).zfill(6)
        rows = [item for item in rows if str(item.get("code") or "").zfill(6) == want]
    if max_symbols is not None:
        rows = rows[: max(0, int(max_symbols))]
    buckets: dict[str, list[dict[str, Any]]] = {rid: [] for rid in SCAN_RULES}
    scanned = 0
    for item in rows:
        code = str(item.get("code") or "").zfill(6)
        sina = str(item.get("sina") or _sina(code)).lower()
        entry_pct = float(item.get("entry_pct") or item.get("pct") or DEFAULT_ENTRY_PCT)
        pullback_pct = float(
            item.get("stop_pct") or item.get("pct") or DEFAULT_PULLBACK_PCT
        )
        daily = _daily(sina)
        minutes = _minutes(sina, refresh=refresh, days=days, source=source)
        for row in iter_symbol_evaluations(
            code=code,
            daily=daily,
            minutes=minutes,
            entry_pct=entry_pct,
            pullback_pct=pullback_pct,
            days=days,
        ):
            scanned += 1
            if not row_in_window(row, symbol=code, date=date, start=start, end=end):
                continue
            for rid in SCAN_RULES:
                if not is_rule_candidate(row, rid):
                    continue
                if winners_only:
                    if rid == "PATH_HALF" and row.winner_rule != "PATH_HALF":
                        continue
                    if rid == "PATH" and row.winner_rule not in ("PATH", "PATH_HALF"):
                        continue
                    if rid not in ("PATH", "PATH_HALF") and row.winner_rule != rid:
                        continue
                buckets[rid].append(candidate_payload(row, rid))
        print(
            f"{code}: scanned={scanned} "
            + " ".join(f"{k}={len(v)}" for k, v in buckets.items()),
            flush=True,
        )
    out: dict[str, dict[str, Any]] = {}
    for rid, cases in buckets.items():
        slim = _keep_event_oriented(cases, rule_id=rid)
        out[rid] = _payload_from_cases(
            rid=rid,
            cases=slim,
            scanned=scanned,
            days=days,
            pool=pool,
            source=source,
        )
        out[rid]["raw_candidate_count"] = len(cases)
        out[rid]["raw_winner_count"] = sum(
            1 for c in cases if c.get("winner_rule") == rid
        )
    return out


def write_corpus(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    slim = {
        "rule_id": payload["rule_id"],
        "evidence_grade": payload["evidence_grade"],
        "source": payload["source"],
        "generated_at": payload["generated_at"],
        "note": payload["note"],
        "candidate_count": payload["candidate_count"],
        "winner_count": payload["winner_count"],
        "sell_count": payload["sell_count"],
        "raw_candidate_count": payload.get("raw_candidate_count"),
        "raw_winner_count": payload.get("raw_winner_count"),
        "cases": [
            {
                "symbol": c["symbol"],
                "date": c["date"],
                "timestamp": c["timestamp"],
                "source": c["source"],
                "expected_rule": c["expected_rule"],
                "winner_rule": c["winner_rule"],
                "legacy_action": c["legacy_action"],
                "entry_price": c["entry_price"],
                "working_stop": c["working_stop"],
                "last": c["last"],
                "path_available": c["path_available"],
                "position": c["position"],
                "can_sell": c["can_sell"],
                "signals": c["signals"],
                "path_stop_kind": c.get("path_stop_kind"),
                "quantity_ratio_legacy": c.get("quantity_ratio_legacy"),
                "quantity_ratio_unified": c.get("quantity_ratio_unified"),
            }
            for c in payload["cases"]
        ],
    }
    path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find historical exit-rule candidates (no rule changes)"
    )
    parser.add_argument("--rule", required=True)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--pool", default=POOL_STRATEGY1)
    parser.add_argument("--source", choices=("ak", "auto", "panda"), default="ak")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--winners-only", action="store_true")
    parser.add_argument("--write-corpus", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    common = dict(
        days=args.days,
        pool=args.pool,
        source=args.source,
        refresh=args.refresh,
        max_symbols=args.max_symbols,
        symbol=args.symbol,
        date=args.date,
        start=args.start,
        end=args.end,
        winners_only=args.winners_only,
    )
    if str(args.rule).strip().upper() in ("ALL", "*"):
        payloads = find_all_cases(**common)
        summary = {}
        for rid, payload in payloads.items():
            name = CORPUS_NAME.get(rid, f"{rid.lower()}.json")
            out = args.output / name if args.output else (
                CORPUS / name if args.write_corpus else OUT / f"find_{rid.lower()}.json"
            )
            if args.write_corpus or args.output is not None:
                write_corpus(payload, out)
                print(f"wrote {out}", flush=True)
            summary[rid] = {
                "candidate_count": payload["candidate_count"],
                "winner_count": payload["winner_count"],
                "sell_count": payload["sell_count"],
                "raw_candidate_count": payload.get("raw_candidate_count"),
                "evaluations_scanned": payload["evaluations_scanned"],
            }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    payload = find_cases(rule=args.rule, **common)
    rid = payload["rule_id"]
    out = args.output
    if out is None:
        name = CORPUS_NAME.get(rid, f"{rid.lower()}.json")
        out = CORPUS / name if args.write_corpus else OUT / f"find_{rid.lower()}.json"
    if args.write_corpus or args.output is not None:
        write_corpus(payload, out)
        print(f"wrote {out}", flush=True)
    print(
        json.dumps(
            {
                "rule_id": rid,
                "candidate_count": payload["candidate_count"],
                "winner_count": payload["winner_count"],
                "sell_count": payload["sell_count"],
                "evaluations_scanned": payload["evaluations_scanned"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
