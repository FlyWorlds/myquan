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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HOLDING = ROOT / "holdingStocks"
for path in (ROOT, HOLDING):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backtest.strategy1_pool_1m.run import (  # noqa: E402
    POOL_STRATEGY1,
    _daily,
    _load_pool,
    _minutes,
    _prep_daily,
    _prep_minutes,
    _sina,
)
from holdingStocks.index import _paper_exit_decision_legacy  # noqa: E402
from strategy.core.exit_decision import ExitAction, paper_reason_to_code  # noqa: E402
from strategy.exit_rules.engine import ExitDecisionEngine  # noqa: E402
from strategy.exit_rules.shadow import (  # noqa: E402
    build_exit_context_from_paper_kwargs,
    compare_paper_vs_exit,
)
from strategy.open_break import is_t1_buy_day  # noqa: E402
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
    eval_multi_tp_bar,
    realized_vol_daily,
    replay_factor26_1m,
    working_stop_price,
)

OUT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class HoldingInterval:
    buy_ts: pd.Timestamp
    buy_px: float
    sell_ts: pd.Timestamp | None


def _as_ts(value: Any) -> pd.Timestamp | None:
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Asia/Shanghai").tz_localize(None)
    return ts


def holding_intervals(trades: list[dict[str, Any]]) -> list[HoldingInterval]:
    """Convert existing Factor26 replay trades into buy-to-full-exit windows."""
    ordered = sorted(
        (t for t in trades if _as_ts(t.get("ts")) is not None),
        key=lambda t: _as_ts(t.get("ts")),
    )
    intervals: list[HoldingInterval] = []
    opened: tuple[pd.Timestamp, float] | None = None
    for trade in ordered:
        ts = _as_ts(trade.get("ts"))
        if ts is None:
            continue
        side = str(trade.get("side") or "").lower()
        if side == "buy":
            if opened is not None:
                intervals.append(HoldingInterval(opened[0], opened[1], None))
            opened = (ts, float(trade.get("px") or 0))
            continue
        if side != "sell" or opened is None:
            continue
        if str(trade.get("note") or "") == "ladder_half_10":
            continue
        intervals.append(HoldingInterval(opened[0], opened[1], ts))
        opened = None
    if opened is not None:
        intervals.append(HoldingInterval(opened[0], opened[1], None))
    return intervals


def _daily_by_session(daily: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    frame = _prep_daily(daily)
    rows: dict[str, dict[str, float | None]] = {}
    prev_close: float | None = None
    for _, row in frame.iterrows():
        session = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
        rows[session] = {
            "open": float(row["open"]),
            "prev_close": prev_close,
            "vol20": realized_vol_daily(
                frame.loc[frame["date"] < row["date"], "close"].tolist()
            ),
        }
        prev_close = float(row["close"])
    return rows


def _action_of_legacy(result: dict[str, Any]) -> str:
    return "SELL" if result.get("hit") else "HOLD"


def replay_symbol(
    *,
    code: str,
    daily: pd.DataFrame,
    minutes: pd.DataFrame,
    entry_pct: float,
    pullback_pct: float,
    days: int,
) -> tuple[Counter[str], list[dict[str, Any]]]:
    """Replay all generated holding windows for one symbol."""
    prepared_minutes = _prep_minutes(minutes)
    report = replay_factor26_1m(
        daily,
        minutes,
        entry_pct=entry_pct,
        pullback_pct=pullback_pct,
        last_n_days=days,
        allow_attack=False,
    )
    intervals = holding_intervals(list(report.get("trades") or []))
    sessions = _daily_by_session(daily)
    engine = ExitDecisionEngine()
    totals: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []

    for interval_no, interval in enumerate(intervals, start=1):
        bars = prepared_minutes[prepared_minutes["ts"] > interval.buy_ts]
        if interval.sell_ts is not None:
            bars = bars[bars["ts"] <= interval.sell_ts]
        if bars.empty or interval.buy_px <= 0:
            continue

        qty = 1000
        tp_stage = 0
        peak = float(interval.buy_px)
        session_peak = 0.0
        current_session = ""
        for _, bar in bars.sort_values("ts").iterrows():
            ts = _as_ts(bar["ts"])
            if ts is None:
                continue
            session = ts.strftime("%Y-%m-%d")
            if session != current_session:
                current_session = session
                session_peak = 0.0
            day = sessions.get(session)
            if day is None:
                continue
            can_sell = not is_t1_buy_day(
                interval.buy_ts.strftime("%Y-%m-%d"), session
            )
            bar_open = float(bar["open"])
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])
            day_open = float(day["open"] or bar_open)
            vol20 = day["vol20"]
            ev = eval_multi_tp_bar(
                bar_open=bar_open,
                bar_high=bar_high,
                bar_low=bar_low,
                cost_px=interval.buy_px,
                peak_before=peak,
                shares=qty,
                tp_stage=tp_stage,
                can_sell=can_sell,
                overnight_armed=False,
                day_open=day_open,
                hard_pct=pullback_pct,
                vol20_daily=vol20,
                session_peak_before=session_peak,
            )
            action = dict(ev.get("action") or {})
            peak_after = float(ev.get("peak_after") or peak)
            session_peak_after = float(ev.get("session_peak_after") or session_peak)
            _, working_stop = working_stop_price(
                cost_px=interval.buy_px,
                peak_high=peak_after,
                session_peak=session_peak_after,
                day_open=day_open,
                hard_pct=pullback_pct,
                vol20_daily=vol20,
            )
            paper_kwargs = {
                "symbol": code,
                "qty": qty,
                "sellable": qty if can_sell else 0,
                "t1_today": not can_sell,
                "last": bar_close,
                "open_px": day_open,
                "prev_close": day.get("prev_close"),
                "cost": interval.buy_px,
                "peak_high": peak,
                "working_stop": working_stop,
                "path_hit": bool(action),
                "path_fill_px": float(action.get("fill_px") or 0),
                "path_action_kind": str(action.get("kind") or ""),
                "path_stop_kind": str(action.get("stop_kind") or action.get("reason") or ""),
                "signal_ok": True,
                "buy_time": interval.buy_ts.strftime("%Y-%m-%d"),
                "session": session,
            }
            legacy_kwargs = {
                key: value for key, value in paper_kwargs.items() if key != "symbol"
            }
            legacy = _paper_exit_decision_legacy(**legacy_kwargs)
            ctx = build_exit_context_from_paper_kwargs(**paper_kwargs)
            decision = engine.evaluate(ctx)
            compared = compare_paper_vs_exit(legacy, decision, ctx)

            legacy_reason_code = paper_reason_to_code(
                legacy.get("reason"), legacy.get("kind")
            ).value
            new_reason_code = decision.reason_code.value
            legacy_factor = (
                "factor26" if str(legacy.get("kind") or "") == "path" else None
            )
            match_factor = legacy_factor == decision.factor_id
            match_reason = legacy_reason_code == new_reason_code
            exact = (
                compared.match_action
                and compared.match_price
                and compared.match_qty
                and match_factor
                and match_reason
            )

            totals["evaluations"] += 1
            totals[f"legacy_{_action_of_legacy(legacy).lower()}"] += 1
            totals[f"unified_{decision.action.value.lower()}"] += 1
            if exact:
                totals["exact_match"] += 1
            else:
                totals["mismatch"] += 1
                totals[f"mismatch_{compared.mismatch_class or 'G'}"] += 1
                mismatches.append(
                    {
                        **asdict(compared),
                        "timestamp": ts.isoformat(),
                        "interval": interval_no,
                        "legacy_reason_code": legacy_reason_code,
                        "new_reason_code": new_reason_code,
                        "match_factor": match_factor,
                        "match_reason": match_reason,
                    }
                )
            if legacy.get("hit"):
                totals["legacy_sell_action_price_qty_match"] += int(
                    compared.match_action
                    and compared.match_price
                    and compared.match_qty
                )
            if not can_sell:
                totals["t1_evaluations"] += 1
            if action:
                totals["factor26_path_evaluations"] += 1
            if str(action.get("kind") or "") == "half":
                totals["half_position_evaluations"] += 1

            peak = peak_after
            session_peak = session_peak_after
            if str(action.get("kind") or "") == "half":
                qty = max(1, qty - int(action.get("shares") or qty // 2))
                tp_stage = 1
            if legacy.get("hit") and str(legacy.get("action_kind") or "") != "half":
                break

    totals["symbols_with_intervals"] = int(bool(intervals))
    totals["holding_intervals"] = len(intervals)
    return totals, mismatches


def run_replay(
    *,
    days: int,
    pool: str,
    source: str,
    refresh: bool,
    max_symbols: int | None = None,
    output_dir: Path = OUT,
) -> dict[str, Any]:
    rows = _load_pool(pool)
    if max_symbols is not None:
        rows = rows[: max(0, int(max_symbols))]
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
        )
        totals.update(symbol_totals)
        mismatches.extend(symbol_mismatches)
        symbols.append(
            {
                "symbol": code,
                "minute_rows": len(minutes),
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
        "days": int(days),
        "pool": pool,
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
    args = parser.parse_args()
    result = run_replay(
        days=args.days,
        pool=args.pool,
        source=args.source,
        refresh=args.refresh,
        max_symbols=args.max_symbols,
        output_dir=args.output_dir,
    )
    print(json.dumps(result["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
