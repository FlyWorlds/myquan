# -*- coding: utf-8 -*-
"""Cross-resolution harness: same synthetic ticks → Realtime + BT-1m.

Contract: docs/TRADING_ENGINE_CONTRACT.md
Does NOT demote realtime to 1m; does NOT invent tick timestamps for BT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from strategy.pullback_wave_stop import (
    CURRENT_INTRABAR_POLICY,
    eval_multi_tp_bar,
    raise_position_peak_high,
    working_stop_price,
)

DiffClass = Literal[
    "MATCH",
    "STRATEGY_DIFFERENCE",
    "EXECUTION_DIFFERENCE",
    "RESOLUTION_DIFFERENCE",
    "CAPITAL_DIFFERENCE",
    "FEE_DIFFERENCE",
    "TEMPORAL_VIOLATION",
]


@dataclass(frozen=True)
class SynthTick:
    ts: datetime
    price: float


@dataclass
class EngineSnapshot:
    bar_minute: datetime
    peak_high: float
    stop_kind: str
    stop_px: float
    should_exit: bool
    exit_kind: str
    decision_at: datetime | None = None
    peak_high_at: datetime | None = None
    tp_stage: int = 0
    overnight_armed: bool = False
    intrabar_ambiguous: bool = False
    resolution: str = ""
    resolution_policy: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiffRecord:
    bar_minute: datetime
    classification: DiffClass
    reason: str
    realtime: EngineSnapshot | None
    bt: EngineSnapshot | None
    evidence: dict[str, Any] = field(default_factory=dict)
    first_divergence_at: datetime | None = None


def _divergence_evidence(
    *,
    reason: str,
    rt: EngineSnapshot | None,
    bt: EngineSnapshot | None,
    ticks_in_bar: list[SynthTick] | None = None,
    peak_before_bar: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """REQUIRED evidence payload — RESOLUTION without this is invalid."""
    amb = bool(bt.intrabar_ambiguous) if bt else False
    tick_amb = False
    if ticks_in_bar is not None and peak_before_bar is not None and rt is not None:
        tick_amb = _bar_has_order_ambiguity(
            ticks_in_bar, float(rt.meta.get("cost") or 0) or 1.0, peak_before_bar
        )
    ev: dict[str, Any] = {
        "classification_reason": reason,
        "first_divergence_at": (rt.decision_at or bt.bar_minute) if (rt or bt) else None,
        "rt_state_before": {
            "peak_high": rt.peak_high if rt else None,
            "stop": (rt.stop_kind, rt.stop_px) if rt else None,
            "exit_kind": rt.exit_kind if rt else None,
        },
        "bt_state_before": {
            "peak_high": bt.peak_high if bt else None,
            "stop": (bt.stop_kind, bt.stop_px) if bt else None,
            "exit_kind": bt.exit_kind if bt else None,
        },
        "rt_observation": (rt.meta if rt else None),
        "bt_bar": (bt.meta if bt else None),
        "rt_decision": {
            "should_exit": rt.should_exit if rt else None,
            "exit_kind": rt.exit_kind if rt else None,
            "decision_at": rt.decision_at if rt else None,
        },
        "bt_decision": {
            "should_exit": bt.should_exit if bt else None,
            "exit_kind": bt.exit_kind if bt else None,
            "bar": bt.bar_minute if bt else None,
        },
        "intrabar_ambiguous": amb,
        "tick_order_ambiguous": tick_amb,
        "temporal_granularity_compatible": temporal_granularity_compatible(rt, bt),
    }
    if extra:
        ev.update(extra)
    return ev


def temporal_granularity_compatible(
    rt: EngineSnapshot | None, bt: EngineSnapshot | None
) -> bool:
    """Realtime decision_at may be second-level; BT only has bar minute.

    Compatible iff no RT decision, or RT decision falls in BT bar minute window.
    Never invents BT second-level timestamps.
    """
    if rt is None or bt is None:
        return True
    if rt.decision_at is None:
        return True
    return minute_floor(rt.decision_at) == bt.bar_minute


def minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def aggregate_1m_ohlc(ticks: list[SynthTick]) -> list[dict[str, Any]]:
    """Honest 1m OHLC aggregation — no synthetic intrabar timestamps."""
    if not ticks:
        return []
    buckets: dict[datetime, list[float]] = {}
    order: list[datetime] = []
    for t in ticks:
        m = minute_floor(t.ts)
        if m not in buckets:
            buckets[m] = []
            order.append(m)
        buckets[m].append(float(t.price))
    bars: list[dict[str, Any]] = []
    for m in order:
        px = buckets[m]
        bars.append(
            {
                "ts": m,
                "open": px[0],
                "high": max(px),
                "low": min(px),
                "close": px[-1],
                "ticks": [t for t in ticks if minute_floor(t.ts) == m],
            }
        )
    return bars


def _stop_state(
    *,
    cost: float,
    peak: float,
    session_peak: float,
    day_open: float,
    overnight_armed: bool,
    vol20: float | None,
) -> tuple[str, float]:
    return working_stop_price(
        cost_px=cost,
        peak_high=peak,
        session_peak=session_peak,
        day_open=day_open,
        overnight_armed=overnight_armed,
        vol20_daily=vol20,
    )


def run_realtime_ticks(
    ticks: list[SynthTick],
    *,
    cost: float,
    shares: int = 400,
    peak_seed: float | None = None,
    overnight_armed: bool = False,
    day_open: float | None = None,
    vol20: float | None = 0.05,
    can_sell: bool = True,
    tp_stage: int = 0,
) -> tuple[list[EngineSnapshot], list[dict[str, Any]]]:
    """Tick-driven mini engine (last-leg). Does NOT use PRIORITY_ENVELOPE."""
    peak = float(peak_seed if peak_seed is not None else cost)
    peak_at: datetime | None = None
    session_peak = float(day_open or cost)
    day_o = float(day_open or (ticks[0].price if ticks else cost))
    exits: list[dict[str, Any]] = []
    # per-minute last snapshot after processing all ticks in that minute
    by_minute: dict[datetime, EngineSnapshot] = {}
    exited = False
    stage = int(tp_stage)
    sh = int(shares)

    for t in ticks:
        if exited:
            break
        m = minute_floor(t.ts)
        px = float(t.price)
        new_peak = raise_position_peak_high(
            persisted_peak=peak,
            entry_price=cost,
            quote_last=px,
            allow_quote_day_high=False,
        )
        if new_peak > peak + 1e-12:
            peak = new_peak
            peak_at = t.ts
        session_peak = max(session_peak, px)
        kind, stop = _stop_state(
            cost=cost,
            peak=peak,
            session_peak=session_peak,
            day_open=day_o,
            overnight_armed=overnight_armed,
            vol20=vol20,
        )
        should = bool(can_sell and stop > 0 and px <= stop + 1e-12)
        snap = EngineSnapshot(
            bar_minute=m,
            peak_high=peak,
            stop_kind=kind,
            stop_px=float(stop),
            should_exit=should,
            exit_kind=kind if should else "",
            decision_at=t.ts if should else None,
            peak_high_at=peak_at,
            tp_stage=stage,
            overnight_armed=overnight_armed,
            resolution="realtime",
            resolution_policy="",
            meta={"last": px},
        )
        by_minute[m] = snap
        if should:
            exits.append(
                {
                    "ts": t.ts,
                    "fill_px": float(stop),
                    "kind": "last",
                    "stop_kind": kind,
                    "peak_high": peak,
                }
            )
            exited = True
            break

    snaps = [by_minute[k] for k in sorted(by_minute)]
    return snaps, exits


def run_bt_1m(
    bars: list[dict[str, Any]],
    *,
    cost: float,
    shares: int = 400,
    peak_seed: float | None = None,
    overnight_armed: bool = False,
    day_open: float | None = None,
    vol20: float | None = 0.05,
    can_sell: bool = True,
    tp_stage: int = 0,
) -> tuple[list[EngineSnapshot], list[dict[str, Any]]]:
    """1m PRIORITY_ENVELOPE path via eval_multi_tp_bar."""
    peak = float(peak_seed if peak_seed is not None else cost)
    session_peak = float(day_open or cost)
    day_o = float(day_open or (bars[0]["open"] if bars else cost))
    stage = int(tp_stage)
    sh = int(shares)
    snaps: list[EngineSnapshot] = []
    exits: list[dict[str, Any]] = []

    for bar in bars:
        ev = eval_multi_tp_bar(
            bar_open=float(bar["open"]),
            bar_high=float(bar["high"]),
            bar_low=float(bar["low"]),
            cost_px=cost,
            peak_before=peak,
            shares=sh,
            tp_stage=stage,
            can_sell=can_sell,
            overnight_armed=overnight_armed,
            day_open=day_o,
            vol20_daily=vol20,
            session_peak_before=session_peak,
        )
        peak = float(ev.get("peak_after") or peak)
        session_peak = float(ev.get("session_peak_after") or session_peak)
        act = ev.get("action") or {}
        should = bool(act.get("kind") in ("full", "half"))
        kind, stop = _stop_state(
            cost=cost,
            peak=peak,
            session_peak=session_peak,
            day_open=day_o,
            overnight_armed=overnight_armed,
            vol20=vol20,
        )
        if should:
            kind = str(act.get("reason") or kind)
            stop = float(act.get("fill_px") or stop)
        snap = EngineSnapshot(
            bar_minute=bar["ts"],
            peak_high=peak,
            stop_kind=kind,
            stop_px=float(stop),
            should_exit=should,
            exit_kind=str(act.get("reason") or "") if should else "",
            decision_at=None,  # honest: no fake tick time
            peak_high_at=None,
            tp_stage=stage,
            overnight_armed=overnight_armed,
            intrabar_ambiguous=bool(ev.get("intrabar_ambiguous")),
            resolution="1m",
            resolution_policy=str(ev.get("resolution_policy") or CURRENT_INTRABAR_POLICY),
            meta={"flags": ev.get("intrabar_flags"), "action": act},
        )
        snaps.append(snap)
        if should:
            exits.append(
                {
                    "ts": bar["ts"],
                    "fill_px": float(act.get("fill_px") or 0),
                    "kind": str(act.get("kind") or ""),
                    "stop_kind": str(act.get("reason") or ""),
                    "peak_high": peak,
                    "intrabar_ambiguous": bool(ev.get("intrabar_ambiguous")),
                }
            )
            if str(act.get("kind")) == "half":
                sh = max(0, sh - int(act.get("shares") or 0))
                stage = max(stage, 1)
            else:
                break
    return snaps, exits


def _bar_has_order_ambiguity(ticks: list[SynthTick], cost: float, peak_before: float) -> bool:
    """Evidence: same minute both raised HWM and later/earlier pierced a trail from some peak."""
    if len(ticks) < 2:
        return False
    prices = [float(t.price) for t in ticks]
    hi = max(prices)
    lo = min(prices)
    # new high in minute vs pullback low
    ran_new_high = hi > float(peak_before) + 1e-12
    # crude: low materially below high (envelope span)
    span = hi - lo
    if ran_new_high and span > max(0.01, cost * 0.002):
        # check chronologically whether high precedes low or reverse
        i_hi = prices.index(hi)
        i_lo = prices.index(lo)
        return i_hi != i_lo
    return False


def classify_minute(
    rt: EngineSnapshot | None,
    bt: EngineSnapshot | None,
    *,
    ticks_in_bar: list[SynthTick],
    peak_before_bar: float,
    cost: float,
    monotonic_ok: bool,
) -> DiffRecord:
    bar_m = (rt or bt).bar_minute  # type: ignore[union-attr]

    def _rec(
        classification: DiffClass,
        reason: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> DiffRecord:
        ev = _divergence_evidence(
            reason=reason,
            rt=rt,
            bt=bt,
            ticks_in_bar=ticks_in_bar,
            peak_before_bar=peak_before_bar,
            extra={**(extra or {}), "cost": cost, "monotonic_ok": monotonic_ok},
        )
        # stamp cost into rt meta for evidence helpers
        if rt is not None and "cost" not in rt.meta:
            rt.meta["cost"] = cost
        return DiffRecord(
            bar_minute=bar_m,
            classification=classification,
            reason=reason,
            realtime=rt,
            bt=bt,
            evidence=ev,
            first_divergence_at=ev.get("first_divergence_at"),
        )

    if rt is None or bt is None:
        return _rec("STRATEGY_DIFFERENCE", "missing_side_snapshot")

    hwm_eq = abs(rt.peak_high - bt.peak_high) <= 1e-6
    stop_eq = abs(rt.stop_px - bt.stop_px) <= 1e-6 and rt.stop_kind == bt.stop_kind
    ambiguous = bool(bt.intrabar_ambiguous) or _bar_has_order_ambiguity(
        ticks_in_bar, cost, peak_before_bar
    )
    kinds_equal = (not rt.should_exit) or (rt.exit_kind == bt.exit_kind)
    # 无歧义时：RT 观测腿 path/last 与 BT Factor26 reason 可视为同一经济退出
    kinds_semantic = bool(
        rt.should_exit
        and bt.should_exit
        and (not ambiguous)
        and _exit_kinds_compatible(rt.exit_kind, bt.exit_kind)
    )
    exit_eq = (rt.should_exit == bt.should_exit) and (kinds_equal or kinds_semantic)

    if hwm_eq and stop_eq and exit_eq:
        return _rec("MATCH", "hwm_stop_exit_equal")

    if rt.should_exit != bt.should_exit and ambiguous:
        return _rec(
            "RESOLUTION_DIFFERENCE",
            "exit_or_path_lost_in_1m_envelope",
            extra={"policy": CURRENT_INTRABAR_POLICY},
        )

    if rt.should_exit and bt.should_exit and not (kinds_equal or kinds_semantic):
        if ambiguous:
            return _rec(
                "RESOLUTION_DIFFERENCE",
                "exit_kind_diff_under_envelope",
                extra={"rt_kind": rt.exit_kind, "bt_kind": bt.exit_kind},
            )
        return _rec(
            "STRATEGY_DIFFERENCE",
            "exit_kind_diff_no_ambiguity",
            extra={"rt_kind": rt.exit_kind, "bt_kind": bt.exit_kind},
        )

    if not hwm_eq:
        if monotonic_ok and not ambiguous and not (rt.should_exit or bt.should_exit):
            return _rec(
                "STRATEGY_DIFFERENCE",
                "hwm_boundary_mismatch_no_ambiguity",
                extra={"rt_hwm": rt.peak_high, "bt_hwm": bt.peak_high},
            )
        if ambiguous:
            return _rec("RESOLUTION_DIFFERENCE", "hwm_path_dependent_in_bar")

    if hwm_eq and not stop_eq and not (rt.should_exit or bt.should_exit):
        return _rec(
            "STRATEGY_DIFFERENCE",
            "stop_formula_mismatch_same_hwm",
            extra={
                "rt_stop": (rt.stop_kind, rt.stop_px),
                "bt_stop": (bt.stop_kind, bt.stop_px),
            },
        )

    if rt.should_exit != bt.should_exit and not ambiguous and monotonic_ok:
        return _rec("STRATEGY_DIFFERENCE", "exit_mismatch_monotonic_no_ambiguity")

    return _rec(
        "STRATEGY_DIFFERENCE",
        "unclassified_divergence",
        extra={"hwm_eq": hwm_eq, "stop_eq": stop_eq, "exit_eq": exit_eq},
    )


def _exit_kinds_compatible(rt_kind: str, bt_kind: str) -> bool:
    """path/last are observation legs; BT uses Factor26 reason codes."""
    rt_k = str(rt_kind or "")
    bt_k = str(bt_kind or "")
    if rt_k == bt_k:
        return True
    # RT observation vs BT strategy reason: same economic exit family
    if rt_k in ("path", "last") and bt_k in (
        "half_gain",
        "vol_giveback",
        "hard_from_cost",
        "t1_peak_trail",
        "peak_pullback_clear",
        "ladder_full_15",
        "ladder_half_10",
        "hard_open_dump",
    ):
        return True
    if rt_k == "open_protect" and bt_k in ("hard_from_cost", "hard_open_dump"):
        return True
    return False


def is_monotonic_ticks(ticks: list[SynthTick]) -> bool:
    if len(ticks) < 2:
        return True
    ups = all(ticks[i].price <= ticks[i + 1].price + 1e-12 for i in range(len(ticks) - 1))
    dns = all(ticks[i].price >= ticks[i + 1].price - 1e-12 for i in range(len(ticks) - 1))
    return ups or dns


def run_cross_harness(
    ticks: list[SynthTick],
    *,
    cost: float,
    shares: int = 400,
    peak_seed: float | None = None,
    overnight_armed: bool = False,
    day_open: float | None = None,
    vol20: float | None = 0.05,
    can_sell: bool = True,
    tp_stage: int = 0,
    use_full_exit: bool = False,
    prev_close: float | None = None,
    overnight_high_ok: bool = True,
) -> dict[str, Any]:
    bars = aggregate_1m_ohlc(ticks)
    if use_full_exit:
        rt_snaps, rt_exits = run_realtime_full_exit(
            ticks,
            cost=cost,
            shares=shares,
            peak_seed=peak_seed,
            overnight_armed=overnight_armed,
            day_open=day_open,
            vol20=vol20,
            can_sell=can_sell,
            tp_stage=tp_stage,
            prev_close=prev_close,
            overnight_high_ok=overnight_high_ok,
        )
    else:
        rt_snaps, rt_exits = run_realtime_ticks(
            ticks,
            cost=cost,
            shares=shares,
            peak_seed=peak_seed,
            overnight_armed=overnight_armed,
            day_open=day_open,
            vol20=vol20,
            can_sell=can_sell,
            tp_stage=tp_stage,
        )
    bt_snaps, bt_exits = run_bt_1m(
        bars,
        cost=cost,
        shares=shares,
        peak_seed=peak_seed,
        overnight_armed=overnight_armed,
        day_open=day_open,
        vol20=vol20,
        can_sell=can_sell,
        tp_stage=tp_stage,
    )
    rt_map = {s.bar_minute: s for s in rt_snaps}
    bt_map = {s.bar_minute: s for s in bt_snaps}
    minutes = sorted(set(rt_map) | set(bt_map))
    diffs: list[DiffRecord] = []
    peak_before = float(peak_seed if peak_seed is not None else cost)
    for m in minutes:
        bar = next((b for b in bars if b["ts"] == m), None)
        ticks_m = list(bar["ticks"]) if bar else []
        mono = is_monotonic_ticks(ticks_m)
        diffs.append(
            classify_minute(
                rt_map.get(m),
                bt_map.get(m),
                ticks_in_bar=ticks_m,
                peak_before_bar=peak_before,
                cost=cost,
                monotonic_ok=mono,
            )
        )
        if bar:
            peak_before = max(peak_before, float(bar["high"]))

    counts: dict[str, int] = {}
    for d in diffs:
        counts[d.classification] = counts.get(d.classification, 0) + 1
        # Gate3: RESOLUTION must carry evidence
        if d.classification == "RESOLUTION_DIFFERENCE":
            if not d.evidence.get("classification_reason"):
                raise AssertionError("RESOLUTION without evidence")

    return {
        "bars": bars,
        "realtime_snapshots": rt_snaps,
        "bt_snapshots": bt_snaps,
        "realtime_exits": rt_exits,
        "bt_exits": bt_exits,
        "diffs": diffs,
        "counts": counts,
        "temporal_violations": counts.get("TEMPORAL_VIOLATION", 0),
        "strategy_differences": counts.get("STRATEGY_DIFFERENCE", 0),
        "resolution_differences": counts.get("RESOLUTION_DIFFERENCE", 0),
        "matches": counts.get("MATCH", 0),
        "use_full_exit": use_full_exit,
    }


def _import_paper_exit_decision():
    """Load production paper_exit_decision (no clone)."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hold = root / "holdingStocks"
    for p in (str(root), str(hold)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from index import paper_exit_decision, _open_protect_hit_ts  # type: ignore

    return paper_exit_decision, _open_protect_hit_ts


def call_paper_exit_decision(**kwargs: Any) -> dict[str, Any]:
    """Thin wrapper — always production function."""
    paper_exit_decision, _ = _import_paper_exit_decision()
    return paper_exit_decision(**kwargs)


def open_protect_triggered_at(*, session: str, open_bell: bool, exit_kind: str) -> str | None:
    _, _open_protect_hit_ts = _import_paper_exit_decision()
    return _open_protect_hit_ts(
        session=session,
        open_bell=open_bell,
        exit_kind=exit_kind,
        fill_px=999.0,  # must be ignored
        open_px=999.0,
    )


def orchestration_eligibility(decision_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Mirror legacy eligibility flags by calling production and reading outcomes.

    Also return theoretical open/path/last hits via a dry probe of inputs
    (does not reimplement priority — uses production for selected kind).
    """
    # Probe each leg in isolation to report eligible_* without cloning priority
    base = dict(decision_kwargs)
    selected = call_paper_exit_decision(**base)

    only_open = call_paper_exit_decision(
        **{
            **base,
            "path_hit": False,
            "path_fill_px": 0.0,
            "last": 0.0,  # disable last
            "working_stop": 0.0,
        }
    )
    # Restore working_stop for path-only: keep path, kill open by raising open
    only_path = call_paper_exit_decision(
        **{
            **base,
            "open_px": max(float(base.get("open_px") or 0), 1e9),  # won't hit protect
            "last": 0.0,
            "working_stop": 0.0,
        }
    )
    only_last = call_paper_exit_decision(
        **{
            **base,
            "open_px": max(float(base.get("open_px") or 0), 1e9),
            "path_hit": False,
            "path_fill_px": 0.0,
        }
    )
    return {
        "eligible_open": bool(only_open.get("hit") and only_open.get("kind") == "open_protect"),
        "eligible_path": bool(only_path.get("hit") and only_path.get("kind") == "path"),
        "eligible_last": bool(only_last.get("hit") and only_last.get("kind") == "last"),
        "selected_exit_kind": str(selected.get("kind") or ""),
        "hit": bool(selected.get("hit")),
        "reason": str(selected.get("reason") or ""),
        "decision": selected,
    }


def run_realtime_full_exit(
    ticks: list[SynthTick],
    *,
    cost: float,
    shares: int = 400,
    peak_seed: float | None = None,
    overnight_armed: bool = False,
    day_open: float | None = None,
    vol20: float | None = 0.05,
    can_sell: bool = True,
    tp_stage: int = 0,
    prev_close: float | None = None,
    overnight_high_ok: bool = True,
    session: str = "2026-03-10",
    t1_today: bool = False,
    signal_ok: bool = True,
) -> tuple[list[EngineSnapshot], list[dict[str, Any]]]:
    """Full production exit chain: HWM → path (1m) → paper_exit_decision.

    Mocks: no QuoteHub / JSON / notify / fill persistence.
    Does NOT mock paper_exit_decision.
    """
    paper_exit_decision, _open_protect_hit_ts = _import_paper_exit_decision()
    peak = float(peak_seed if peak_seed is not None else cost)
    peak_at: datetime | None = None
    session_peak = float(day_open or cost)
    day_o = float(day_open or (ticks[0].price if ticks else cost))
    prev_c = float(prev_close if prev_close is not None else cost)
    stage = int(tp_stage)
    sh = int(shares)
    exits: list[dict[str, Any]] = []
    by_minute: dict[datetime, EngineSnapshot] = {}
    exited = False

    # Accumulate ticks per minute for path eval at minute close
    buckets: dict[datetime, list[SynthTick]] = {}
    for t in ticks:
        buckets.setdefault(minute_floor(t.ts), []).append(t)

    path_hit = False
    path_fill = 0.0
    path_action = ""
    path_stop = ""
    path_touch_ts: datetime | None = None

    sorted_minutes = sorted(buckets)
    for mi, m in enumerate(sorted_minutes):
        if exited:
            break
        m_ticks = buckets[m]
        # Process ticks within minute (last leg can fire mid-minute)
        for t in m_ticks:
            if exited:
                break
            px = float(t.price)
            peak = raise_position_peak_high(
                persisted_peak=peak,
                entry_price=cost,
                quote_last=px,
                allow_quote_day_high=False,
            )
            if peak_at is None or px >= peak - 1e-12:
                # stamp at when peak equals current (raise or equal keep last raise)
                if abs(px - peak) <= 1e-12:
                    peak_at = t.ts
            session_peak = max(session_peak, px)
            stop_kind, stop_px = _stop_state(
                cost=cost,
                peak=peak,
                session_peak=session_peak,
                day_open=day_o,
                overnight_armed=overnight_armed,
                vol20=vol20,
            )
            # Open protect uses day open — evaluate from first tick of session
            dec = paper_exit_decision(
                qty=sh,
                sellable=sh if can_sell else 0,
                t1_today=t1_today,
                last=px,
                open_px=day_o,
                prev_close=prev_c,
                cost=cost,
                peak_high=peak if overnight_high_ok else peak,
                working_stop=float(stop_px),
                path_hit=path_hit,
                path_fill_px=path_fill,
                path_action_kind=path_action,
                path_stop_kind=path_stop,
                signal_ok=signal_ok,
                overnight_high_ok=overnight_high_ok,
                session=session,
            )
            should = bool(dec.get("hit"))
            kind = str(dec.get("kind") or "")
            decision_at = t.ts
            if kind == "open_protect":
                decision_at = datetime.strptime(
                    _open_protect_hit_ts(
                        session=session,
                        open_bell=True,
                        exit_kind="open_protect",
                    )
                    or f"{session} 09:30:00",
                    "%Y-%m-%d %H:%M:%S",
                )
            elif kind == "path" and path_touch_ts is not None:
                decision_at = path_touch_ts

            snap = EngineSnapshot(
                bar_minute=m,
                peak_high=peak,
                stop_kind=stop_kind,
                stop_px=float(stop_px),
                should_exit=should,
                exit_kind=kind if should else "",
                decision_at=decision_at if should else None,
                peak_high_at=peak_at,
                tp_stage=stage,
                overnight_armed=overnight_armed,
                resolution="realtime",
                resolution_policy="",
                meta={
                    "last": px,
                    "cost": cost,
                    "paper": dec,
                    "path_hit": path_hit,
                },
            )
            by_minute[m] = snap
            if should:
                exits.append(
                    {
                        "ts": decision_at,
                        "fill_px": float(dec.get("fill_px") or 0),
                        "kind": kind,
                        "stop_kind": str(dec.get("stop_kind") or stop_kind),
                        "peak_high": peak,
                        "paper": dec,
                    }
                )
                exited = True
                break

        if exited:
            break

        # Minute close: evaluate path via eval_multi_tp_bar (production Factor26)
        ohlc = m_ticks
        bar_o = float(ohlc[0].price)
        bar_h = max(float(x.price) for x in ohlc)
        bar_lo = min(float(x.price) for x in ohlc)
        peak_before_bar = float(peak_seed if peak_seed is not None else cost)
        # Use peak before this bar's raise for fair path — approximate: max of pre-minute
        # After processing ticks, peak already includes bar high; for path use eval's peak_before
        # Recompute path with peak prior to bar: max(seed, highs of earlier minutes)
        prior_peak = float(peak_seed if peak_seed is not None else cost)
        for earlier in sorted_minutes[:mi]:
            prior_peak = max(prior_peak, max(float(x.price) for x in buckets[earlier]))
        ev = eval_multi_tp_bar(
            bar_open=bar_o,
            bar_high=bar_h,
            bar_low=bar_lo,
            cost_px=cost,
            peak_before=prior_peak,
            shares=sh,
            tp_stage=stage,
            can_sell=can_sell and (not t1_today),
            overnight_armed=overnight_armed,
            day_open=day_o,
            vol20_daily=vol20,
            session_peak_before=session_peak,
        )
        act = ev.get("action") or {}
        if act.get("kind") in ("full", "half") and float(act.get("fill_px") or 0) > 0:
            path_hit = True
            path_fill = float(act["fill_px"])
            path_action = str(act.get("kind") or "")
            path_stop = str(act.get("reason") or "")
            # Honest: first tick in bar that would pierce — use first low-touch approx
            path_touch_ts = next(
                (x.ts for x in ohlc if float(x.price) <= path_fill + 1e-12),
                ohlc[-1].ts,
            )
            stop_kind, stop_px = _stop_state(
                cost=cost,
                peak=peak,
                session_peak=session_peak,
                day_open=day_o,
                overnight_armed=overnight_armed,
                vol20=vol20,
            )
            dec = paper_exit_decision(
                qty=sh,
                sellable=sh if can_sell else 0,
                t1_today=t1_today,
                last=float(ohlc[-1].price),
                open_px=day_o,
                prev_close=prev_c,
                cost=cost,
                peak_high=peak,
                working_stop=float(stop_px),
                path_hit=True,
                path_fill_px=path_fill,
                path_action_kind=path_action,
                path_stop_kind=path_stop,
                signal_ok=signal_ok,
                overnight_high_ok=overnight_high_ok,
                session=session,
            )
            if dec.get("hit"):
                kind = str(dec.get("kind") or "")
                decision_at = path_touch_ts if kind == "path" else ohlc[-1].ts
                if kind == "open_protect":
                    decision_at = datetime.strptime(
                        _open_protect_hit_ts(
                            session=session,
                            open_bell=True,
                            exit_kind="open_protect",
                        )
                        or f"{session} 09:30:00",
                        "%Y-%m-%d %H:%M:%S",
                    )
                snap = EngineSnapshot(
                    bar_minute=m,
                    peak_high=peak,
                    stop_kind=stop_kind,
                    stop_px=float(stop_px),
                    should_exit=True,
                    exit_kind=kind,
                    decision_at=decision_at,
                    peak_high_at=peak_at,
                    tp_stage=stage,
                    overnight_armed=overnight_armed,
                    intrabar_ambiguous=bool(ev.get("intrabar_ambiguous")),
                    resolution="realtime",
                    meta={"paper": dec, "path_ev": ev, "cost": cost},
                )
                by_minute[m] = snap
                exits.append(
                    {
                        "ts": decision_at,
                        "fill_px": float(dec.get("fill_px") or 0),
                        "kind": kind,
                        "stop_kind": path_stop,
                        "peak_high": peak,
                        "paper": dec,
                    }
                )
                exited = True

    snaps = [by_minute[k] for k in sorted(by_minute)]
    return snaps, exits


def make_ticks(
    pairs: list[tuple[str, float]],
    *,
    day: str = "2026-03-10",
) -> list[SynthTick]:
    """pairs: [('10:00:05', 18.50), ...]"""
    out: list[SynthTick] = []
    for hm, px in pairs:
        ts = datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M:%S")
        out.append(SynthTick(ts=ts, price=float(px)))
    return out
