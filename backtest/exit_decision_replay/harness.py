"""Shared read-only evaluation loop for exit replay and case finding.

Never enables USE_UNIFIED_EXIT_ENGINE. Both orchestrators receive the same context.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from backtest.exit_decision_replay.catalog import normalize_rule_id
from backtest.strategy1_pool_1m.run import _prep_daily, _prep_minutes
from holdingStocks.index import _paper_exit_decision_legacy
from strategy.core.exit_decision import ExitAction, ReasonCode, paper_reason_to_code
from strategy.exit_rules.engine import ExitDecisionEngine
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.exit_rules.shadow import (
    build_exit_context_from_paper_kwargs,
    compare_paper_vs_exit,
)
from strategy.exit_rules.working_stop import evaluate_working_stop
from strategy.open_break import is_t1_buy_day
from strategy.pullback_wave_stop import (
    eval_multi_tp_bar,
    realized_vol_daily,
    replay_factor26_1m,
    working_stop_price,
)


@dataclass(frozen=True)
class HoldingInterval:
    buy_ts: pd.Timestamp
    buy_px: float
    sell_ts: pd.Timestamp | None


@dataclass
class EvalRow:
    symbol: str
    timestamp: pd.Timestamp
    session: str
    interval_no: int
    paper_kwargs: dict[str, Any]
    legacy: dict[str, Any]
    decision: Any
    compared: Any
    can_sell: bool
    path_action: dict[str, Any]
    signals: dict[str, bool]
    winner_rule: str
    legacy_rule: str
    exact: bool
    match_price_exact: bool
    match_factor: bool
    match_reason: bool
    entry_price: float
    working_stop: float
    last: float
    path_available: bool
    position: int


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


def daily_by_session(daily: pd.DataFrame) -> dict[str, dict[str, float | None]]:
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


def _legacy_qty_ratio(legacy: dict[str, Any]) -> float | None:
    if not legacy.get("hit"):
        return None
    if str(legacy.get("action_kind") or "") == "half":
        return 0.5
    return 1.0


def _winner_rule(decision: Any, legacy: dict[str, Any]) -> str:
    if decision.action == ExitAction.SELL and decision.quantity_ratio < 1.0 - 1e-12:
        return "PATH_HALF"
    code = decision.reason_code.value
    if code != ReasonCode.NONE.value:
        return code
    if decision.show_only:
        return paper_reason_to_code(legacy.get("reason"), legacy.get("kind")).value
    return ReasonCode.NONE.value


def row_matches_rule(row: EvalRow, rule: str | None) -> bool:
    if not rule:
        return True
    rid = normalize_rule_id(rule)
    if rid == "PATH_HALF":
        half = bool(
            row.legacy.get("hit") and str(row.legacy.get("action_kind") or "") == "half"
        ) or (
            row.decision.action == ExitAction.SELL
            and float(row.decision.quantity_ratio) < 1.0 - 1e-12
        )
        return half or bool(row.signals.get("path_half"))
    if rid.startswith("PATH_"):
        stop = str(row.path_action.get("stop_kind") or row.path_action.get("reason") or "")
        mapping = {
            "PATH_HALF_GAIN": "half_gain",
            "PATH_VOL_GIVEBACK": "vol_giveback",
            "PATH_HARD_FROM_COST": "hard_from_cost",
            "PATH_HARD_GAP": "hard_open_dump",
            "PATH_LADDER_FULL_15": "ladder_full_15",
            "PATH_PEAK_PULLBACK": ("peak_pullback", "peak_pullback_clear"),
            "PATH_T1_PEAK_TRAIL": "t1_peak_trail",
        }
        expect = mapping.get(rid)
        if expect is None:
            return row.winner_rule == "PATH" or bool(row.signals.get("path"))
        if isinstance(expect, tuple):
            return stop in expect
        return stop == expect
    if rid == "WORKING_STOP":
        return bool(row.signals.get("working_stop")) or row.winner_rule == "WORKING_STOP"
    if rid == "OPEN_PROTECT":
        return bool(row.signals.get("open_protect")) or row.winner_rule == "OPEN_PROTECT"
    if rid == "PATH":
        return bool(row.signals.get("path")) or row.winner_rule in ("PATH", "PATH_HALF")
    if rid == "T1_BLOCK":
        return row.winner_rule == "T1_BLOCK" or (
            not row.can_sell and bool(row.signals.get("would_sell"))
        )
    return row.winner_rule == rid or row.legacy_rule == rid


def row_in_window(
    row: EvalRow,
    *,
    symbol: str | None = None,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> bool:
    if symbol and str(row.symbol).zfill(6) != str(symbol).zfill(6):
        return False
    session = row.session
    if date and session != str(date)[:10]:
        return False
    if start and session < str(start)[:10]:
        return False
    if end and session > str(end)[:10]:
        return False
    return True


def is_rule_candidate(row: EvalRow, rule: str) -> bool:
    """True when the named rule's *signal* is on (not necessarily the winner)."""
    rid = normalize_rule_id(rule)
    if rid == "WORKING_STOP":
        return bool(row.signals.get("working_stop"))
    if rid == "OPEN_PROTECT":
        return bool(row.signals.get("open_protect"))
    if rid == "PATH":
        return bool(row.signals.get("path"))
    if rid == "PATH_HALF":
        return bool(row.signals.get("path_half"))
    if rid == "T1_BLOCK":
        return (not row.can_sell) and bool(row.signals.get("would_sell"))
    return row_matches_rule(row, rid)


def iter_symbol_evaluations(
    *,
    code: str,
    daily: pd.DataFrame,
    minutes: pd.DataFrame,
    entry_pct: float,
    pullback_pct: float,
    days: int,
) -> Iterator[EvalRow]:
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
    sessions = daily_by_session(daily)
    engine = ExitDecisionEngine()

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
            can_sell = not is_t1_buy_day(interval.buy_ts.strftime("%Y-%m-%d"), session)
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
            legacy_kwargs = {k: v for k, v in paper_kwargs.items() if k != "symbol"}
            legacy = _paper_exit_decision_legacy(**legacy_kwargs)
            ctx = build_exit_context_from_paper_kwargs(**paper_kwargs)
            decision = engine.evaluate(ctx)
            compared = compare_paper_vs_exit(legacy, decision, ctx)

            open_sig = bool(evaluate_overnight_open_protect(ctx).triggered)
            last_sig = bool(evaluate_working_stop(ctx).triggered)
            path_sig = bool(paper_kwargs["path_hit"] and float(paper_kwargs["path_fill_px"] or 0) > 0)
            path_half = str(action.get("kind") or "") == "half" or (
                str(paper_kwargs["path_action_kind"]).lower() == "half"
            )
            would_sell = bool(open_sig or last_sig or path_sig)

            legacy_reason_code = paper_reason_to_code(
                legacy.get("reason"), legacy.get("kind")
            ).value
            new_reason_code = decision.reason_code.value
            legacy_price = (
                float(legacy.get("fill_px") or 0) if legacy.get("hit") else None
            )
            new_price = (
                float(decision.price)
                if decision.action == ExitAction.SELL and decision.price is not None
                else None
            )
            match_price_exact = (
                legacy_price is None
                and new_price is None
                or legacy_price is not None
                and new_price is not None
                and abs(legacy_price - new_price) <= 1e-6
            )
            legacy_factor = (
                "factor26" if str(legacy.get("kind") or "") == "path" else None
            )
            match_factor = legacy_factor == decision.factor_id
            match_reason = legacy_reason_code == new_reason_code
            exact = (
                compared.match_action
                and match_price_exact
                and compared.match_qty
                and match_factor
                and match_reason
            )
            winner = _winner_rule(decision, legacy)
            row = EvalRow(
                symbol=code,
                timestamp=ts,
                session=session,
                interval_no=interval_no,
                paper_kwargs=paper_kwargs,
                legacy=legacy,
                decision=decision,
                compared=compared,
                can_sell=can_sell,
                path_action=action,
                signals={
                    "open_protect": open_sig,
                    "working_stop": last_sig,
                    "path": path_sig,
                    "path_half": path_half,
                    "would_sell": would_sell,
                },
                winner_rule=winner,
                legacy_rule=legacy_reason_code,
                exact=exact,
                match_price_exact=match_price_exact,
                match_factor=match_factor,
                match_reason=match_reason,
                entry_price=float(interval.buy_px),
                working_stop=float(working_stop or 0),
                last=float(bar_close),
                path_available=bool(action),
                position=int(qty),
            )
            yield row

            peak = peak_after
            session_peak = session_peak_after
            if str(action.get("kind") or "") == "half":
                qty = max(1, qty - int(action.get("shares") or qty // 2))
                tp_stage = 1
            if legacy.get("hit") and str(legacy.get("action_kind") or "") != "half":
                break


def accumulate_row(totals: dict[str, int], row: EvalRow) -> dict[str, Any] | None:
    """Update counters. Return a mismatch payload when exact is false."""
    totals["evaluations"] = totals.get("evaluations", 0) + 1
    totals[f"legacy_{_action_of_legacy(row.legacy).lower()}"] = (
        totals.get(f"legacy_{_action_of_legacy(row.legacy).lower()}", 0) + 1
    )
    totals[f"unified_{row.decision.action.value.lower()}"] = (
        totals.get(f"unified_{row.decision.action.value.lower()}", 0) + 1
    )
    if row.exact:
        totals["exact_match"] = totals.get("exact_match", 0) + 1
        mismatch = None
    else:
        totals["mismatch"] = totals.get("mismatch", 0) + 1
        klass = row.compared.mismatch_class or "G"
        totals[f"mismatch_{klass}"] = totals.get(f"mismatch_{klass}", 0) + 1
        mismatch = {
            **asdict(row.compared),
            "timestamp": row.timestamp.isoformat(),
            "interval": row.interval_no,
            "legacy_reason_code": row.legacy_rule,
            "new_reason_code": row.decision.reason_code.value,
            "match_price_exact": row.match_price_exact,
            "match_factor": row.match_factor,
            "match_reason": row.match_reason,
            "winner_rule": row.winner_rule,
        }
    if row.legacy.get("hit"):
        totals["legacy_sell_exact_action_price_quantity"] = totals.get(
            "legacy_sell_exact_action_price_quantity", 0
        ) + int(row.compared.match_action and row.match_price_exact and row.compared.match_qty)
        totals["legacy_sell_exact_action_price_quantity_reason"] = totals.get(
            "legacy_sell_exact_action_price_quantity_reason", 0
        ) + int(
            row.compared.match_action
            and row.match_price_exact
            and row.compared.match_qty
            and row.match_reason
        )
        totals[f"legacy_sell_reason_{row.legacy_rule.lower()}"] = (
            totals.get(f"legacy_sell_reason_{row.legacy_rule.lower()}", 0) + 1
        )
        totals["legacy_sell_action_parity"] = totals.get("legacy_sell_action_parity", 0) + int(
            row.compared.match_action
        )
        totals["legacy_sell_price_parity"] = totals.get("legacy_sell_price_parity", 0) + int(
            row.match_price_exact
        )
        totals["legacy_sell_qty_parity"] = totals.get("legacy_sell_qty_parity", 0) + int(
            row.compared.match_qty
        )
        totals["legacy_sell_reason_parity"] = totals.get("legacy_sell_reason_parity", 0) + int(
            row.match_reason
        )
        if str(row.legacy.get("action_kind") or "") == "half":
            totals["legacy_partial_sell"] = totals.get("legacy_partial_sell", 0) + 1
            totals["legacy_partial_qty_parity"] = totals.get(
                "legacy_partial_qty_parity", 0
            ) + int(row.compared.match_qty)
    if row.decision.action == ExitAction.SELL and row.decision.quantity_ratio < 1.0 - 1e-12:
        totals["unified_partial_sell"] = totals.get("unified_partial_sell", 0) + 1
    if not row.can_sell:
        totals["t1_evaluations"] = totals.get("t1_evaluations", 0) + 1
        if row.winner_rule == "T1_BLOCK":
            totals["t1_block"] = totals.get("t1_block", 0) + 1
        if row.signals.get("would_sell"):
            totals["t1_would_sell"] = totals.get("t1_would_sell", 0) + 1
            if row.signals.get("open_protect"):
                totals["t1_would_open_protect"] = totals.get("t1_would_open_protect", 0) + 1
            if row.signals.get("working_stop"):
                totals["t1_would_working_stop"] = totals.get("t1_would_working_stop", 0) + 1
            if row.signals.get("path"):
                totals["t1_would_factor26"] = totals.get("t1_would_factor26", 0) + 1
    if row.path_action:
        totals["factor26_path_evaluations"] = totals.get("factor26_path_evaluations", 0) + 1
    if row.signals.get("path_half"):
        totals["half_position_evaluations"] = totals.get("half_position_evaluations", 0) + 1
    if row.signals.get("working_stop"):
        totals["working_stop_signal"] = totals.get("working_stop_signal", 0) + 1
    if row.winner_rule == "WORKING_STOP" and row.legacy.get("hit"):
        totals["working_stop_sell"] = totals.get("working_stop_sell", 0) + 1
    if row.signals.get("open_protect") and row.signals.get("working_stop"):
        totals["collision_open_protect_working_stop"] = (
            totals.get("collision_open_protect_working_stop", 0) + 1
        )
    if row.signals.get("working_stop") and row.signals.get("path"):
        totals["collision_working_stop_path"] = (
            totals.get("collision_working_stop_path", 0) + 1
        )
    if row.signals.get("open_protect") and row.signals.get("path"):
        totals["collision_open_protect_path"] = (
            totals.get("collision_open_protect_path", 0) + 1
        )
    return mismatch


def candidate_payload(row: EvalRow, rule: str) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "date": row.session,
        "timestamp": row.timestamp.isoformat(),
        "entry_price": row.entry_price,
        "working_stop": row.working_stop,
        "last": row.last,
        "path_available": row.path_available,
        "position": row.position,
        "source": "factor26_1m_replay_generated_entries",
        "expected_rule": normalize_rule_id(rule),
        "winner_rule": row.winner_rule,
        "legacy_action": _action_of_legacy(row.legacy),
        "unified_action": row.decision.action.value,
        "legacy_rule": row.legacy_rule,
        "signals": dict(row.signals),
        "can_sell": row.can_sell,
        "path_stop_kind": str(
            row.path_action.get("stop_kind") or row.path_action.get("reason") or ""
        ),
        "quantity_ratio_legacy": _legacy_qty_ratio(row.legacy),
        "quantity_ratio_unified": (
            float(row.decision.quantity_ratio)
            if row.decision.action == ExitAction.SELL
            else None
        ),
        "exact": row.exact,
    }
