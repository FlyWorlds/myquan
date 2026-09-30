"""Exit 引擎开关与 Shadow Compare（默认不切换生产路径）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from collections import Counter
from typing import Any, Callable

from strategy.core.exit_decision import ExitDecision, paper_reason_to_code
from strategy.core.factor_result import DecisionContext
from strategy.exit_rules.engine import ExitDecisionEngine, exit_decision_to_paper_dict

# 生产默认：不切换；Shadow 默认关（测试可开）。Cursor 不得自行打开。
USE_UNIFIED_EXIT_ENGINE = True
SHADOW_UNIFIED_EXIT_ENGINE = True
SHADOW_CONFIG_VERSION = "phase3c+"
SHADOW_HOLD_SAMPLE_EVERY = 50

_SHADOW_BUFFER: list[dict[str, Any]] = []
_SHADOW_ERRORS: list[dict[str, Any]] = []
_SHADOW_METRICS: Counter[str] = Counter()
_SHADOW_HOOK: Callable[[dict[str, Any]], None] | None = None
_ENGINE = ExitDecisionEngine()
_HOLD_SAMPLE_SEQ = 0


@dataclass
class ShadowCompareRecord:
    timestamp: str
    symbol: str
    legacy_action: str
    new_action: str
    legacy_price: float | None
    new_price: float | None
    legacy_factor: str | None
    new_factor: str | None
    legacy_reason: str | None
    new_reason: str | None
    reason_code: str | None
    quantity_ratio_new: float | None
    quantity_ratio_legacy: float | None
    working_stop: float | None
    overnight_open_protect_px: float | None
    path_available: bool
    match_action: bool
    match_price: bool
    match_qty: bool
    match_reason: bool = True
    legacy_rule: str | None = None
    unified_rule: str | None = None
    config_version: str = SHADOW_CONFIG_VERSION
    log_level: str = "full"
    sampled: bool = False
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    position_state: dict[str, Any] = field(default_factory=dict)
    mismatch_class: str = ""


def set_shadow_hook(hook: Callable[[dict[str, Any]], None] | None) -> None:
    global _SHADOW_HOOK
    _SHADOW_HOOK = hook


def clear_shadow_buffer() -> None:
    global _HOLD_SAMPLE_SEQ
    _SHADOW_BUFFER.clear()
    _SHADOW_ERRORS.clear()
    _SHADOW_METRICS.clear()
    _HOLD_SAMPLE_SEQ = 0


def get_shadow_buffer() -> list[dict[str, Any]]:
    return list(_SHADOW_BUFFER)


def get_shadow_errors() -> list[dict[str, Any]]:
    return list(_SHADOW_ERRORS)


def get_shadow_metrics() -> dict[str, int]:
    return dict(_SHADOW_METRICS)


def _bump(key: str, n: int = 1) -> None:
    _SHADOW_METRICS[key] += n


def _note_shadow_error(
    where: str,
    exc: BaseException,
    ctx: DecisionContext | None = None,
    *,
    count_eval: bool = True,
    primary_failover: bool = False,
) -> None:
    """Record a shadow failure without touching paper state.

    primary_failover: USE=True and Unified engine failed, so the returned
    decision is Legacy. Distinct from shadow_errors (observation failures).
    """
    row: dict[str, Any] = {
        "where": where,
        "error": f"{type(exc).__name__}: {exc}",
        "symbol": str(getattr(ctx, "symbol", "") or ""),
        "config_version": SHADOW_CONFIG_VERSION,
    }
    if primary_failover:
        row["primary"] = "unified"
        row["fallback"] = "legacy"
        _bump("primary_failover_to_legacy")
    _SHADOW_ERRORS.append(row)
    if len(_SHADOW_ERRORS) > 500:
        del _SHADOW_ERRORS[: len(_SHADOW_ERRORS) - 500]
    _bump("shadow_errors")
    if count_eval:
        _bump("shadow_evaluations")


def build_exit_context_from_paper_kwargs(**kw: Any) -> DecisionContext:
    return DecisionContext(
        symbol=str(kw.get("symbol") or kw.get("code") or ""),
        qty=int(kw.get("qty") or 0),
        sellable=int(kw.get("sellable") or 0),
        t1_today=bool(kw.get("t1_today")),
        hold_locked=bool(kw.get("hold_locked")),
        stop_locked=bool(kw.get("stop_locked")),
        current_price=float(kw.get("last") or 0),
        open_px=float(kw.get("open_px") or 0),
        day_high=float(kw.get("day_high") or 0),
        prev_close=kw.get("prev_close"),
        entry_price=kw.get("cost"),
        peak_high=kw.get("peak_high"),
        working_stop=float(kw.get("working_stop") or 0),
        path_hit=bool(kw.get("path_hit")),
        path_fill_px=float(kw.get("path_fill_px") or 0) or None,
        path_action_kind=str(kw.get("path_action_kind") or ""),
        path_stop_kind=str(kw.get("path_stop_kind") or ""),
        signal_ok=bool(kw.get("signal_ok", True)),
        overnight_high_ok=kw.get("overnight_high_ok"),
        buy_time=str(kw.get("buy_time")) if kw.get("buy_time") is not None else None,
        session=str(kw.get("session") or ""),
        overnight_open_protect_px=kw.get("overnight_open_protect_px"),
    )


def _legacy_action(paper: dict[str, Any]) -> str:
    if paper.get("hit"):
        return "SELL"
    if paper.get("hit_show"):
        return "HOLD_SHOW"
    return "HOLD"


def _legacy_qty_ratio(paper: dict[str, Any]) -> float | None:
    if not paper.get("hit"):
        return None
    if str(paper.get("action_kind") or "") == "half":
        return 0.5
    return 1.0


def classify_mismatch(
    *,
    legacy_action: str,
    new_action: str,
    legacy_kind: str,
    new_reason_code: str,
    path_available: bool,
) -> str:
    if legacy_action == new_action:
        return ""
    # 归一 HOLD_SHOW ≈ HOLD（不成交）
    la = "HOLD" if legacy_action in ("HOLD", "HOLD_SHOW") else legacy_action
    na = "HOLD" if new_action in ("HOLD", "HOLD_SHOW") else new_action
    if la == na:
        return "F"  # show semantics
    if legacy_kind == "open_protect" and na == "HOLD":
        return "C"
    if legacy_kind == "last" and not path_available and na == "HOLD":
        return "C"
    if la != na:
        return "G"
    return "G"


def compare_paper_vs_exit(
    legacy: dict[str, Any],
    dec: ExitDecision,
    ctx: DecisionContext,
) -> ShadowCompareRecord:
    adapted = exit_decision_to_paper_dict(dec)
    la = _legacy_action(legacy)
    if dec.action.value == "SELL":
        na = "SELL"
    elif dec.show_only:
        na = "HOLD_SHOW"
    else:
        na = "HOLD"
    lp = float(legacy.get("fill_px") or 0) or None
    np_ = float(dec.price) if dec.price is not None else None
    lq = _legacy_qty_ratio(legacy)
    nq = float(dec.quantity_ratio) if dec.action.value == "SELL" else None
    match_action = (
        ("HOLD" if la in ("HOLD", "HOLD_SHOW") else la)
        == ("HOLD" if na in ("HOLD", "HOLD_SHOW") else na)
    )
    match_price = True
    if la == "SELL" and na == "SELL" and lp is not None and np_ is not None:
        match_price = abs(lp - np_) <= 1e-6 or abs(lp - np_) / max(abs(lp), abs(np_), 1e-9) < 1e-4
    match_qty = True
    if lq is not None and nq is not None:
        match_qty = abs(lq - nq) < 1e-9
    legacy_rule = paper_reason_to_code(legacy.get("reason"), legacy.get("kind")).value
    unified_rule = dec.rule_id
    match_reason = legacy_rule == unified_rule

    mm = ""
    if not (match_action and match_price and match_qty and match_reason):
        if not match_action:
            mm = classify_mismatch(
                legacy_action=la,
                new_action=na,
                legacy_kind=str(legacy.get("kind") or ""),
                new_reason_code=str(dec.reason_code.value if dec.reason_code else ""),
                path_available=bool(ctx.path_hit),
            )
        elif not match_price:
            mm = "E"
        elif not match_qty:
            mm = "A"
        elif not match_reason:
            mm = "D"

    return ShadowCompareRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol=str(ctx.symbol or ""),
        legacy_action=la,
        new_action=na,
        legacy_price=lp if legacy.get("hit") else None,
        new_price=np_ if dec.action.value == "SELL" else None,
        legacy_factor="factor26" if str(legacy.get("kind") or "") == "path" else None,
        new_factor=dec.factor_id,
        legacy_reason=str(legacy.get("reason") or "") or None,
        new_reason=dec.reason,
        reason_code=dec.reason_code.value if dec.reason_code else None,
        quantity_ratio_new=nq,
        quantity_ratio_legacy=lq,
        working_stop=ctx.working_stop,
        overnight_open_protect_px=ctx.overnight_open_protect_px,
        path_available=bool(ctx.path_hit),
        match_action=match_action,
        match_price=match_price,
        match_qty=match_qty,
        match_reason=match_reason,
        legacy_rule=legacy_rule,
        unified_rule=unified_rule,
        config_version=SHADOW_CONFIG_VERSION,
        context_snapshot=_context_snapshot(ctx),
        decision_trace=list(dec.trace or ()),
        position_state={
            "qty": ctx.qty,
            "sellable": ctx.sellable,
            "t1_today": ctx.t1_today,
            "path": {
                "hit": ctx.path_hit,
                "fill_px": ctx.path_fill_px,
                "stop_kind": ctx.path_stop_kind,
                "action_kind": ctx.path_action_kind,
            },
            "working_stop": ctx.working_stop,
        },
        mismatch_class=mm,
    )


_REPLAY_KW_KEYS = (
    "symbol",
    "qty",
    "sellable",
    "t1_today",
    "hold_locked",
    "stop_locked",
    "last",
    "open_px",
    "prev_close",
    "cost",
    "peak_high",
    "working_stop",
    "path_hit",
    "path_fill_px",
    "path_action_kind",
    "path_stop_kind",
    "signal_ok",
    "overnight_high_ok",
    "buy_time",
    "session",
)


def _context_snapshot(ctx: DecisionContext) -> dict[str, Any]:
    return {
        "symbol": ctx.symbol,
        "timestamp": ctx.timestamp.isoformat() if ctx.timestamp else None,
        "session": ctx.session,
        "last": ctx.current_price,
        "open_px": ctx.open_px,
        "prev_close": ctx.prev_close,
        "working_stop": ctx.working_stop,
        "overnight_open_protect_px": ctx.overnight_open_protect_px,
        "overnight_high_ok": ctx.overnight_high_ok,
        "path_hit": ctx.path_hit,
        "path_fill_px": ctx.path_fill_px,
        "path_stop_kind": ctx.path_stop_kind,
        "path_action_kind": ctx.path_action_kind,
        "qty": ctx.qty,
        "sellable": ctx.sellable,
        "t1_today": ctx.t1_today,
        "hold_locked": ctx.hold_locked,
        "stop_locked": ctx.stop_locked,
        "signal_ok": ctx.signal_ok,
        "entry_price": ctx.entry_price,
        "peak_high": ctx.peak_high,
        "buy_time": ctx.buy_time,
    }


def _scalar_paper_kwargs(paper_kwargs: dict[str, Any] | None, rec: ShadowCompareRecord) -> dict[str, Any]:
    src = dict(paper_kwargs or {})
    snap = rec.context_snapshot or {}
    out: dict[str, Any] = {}
    fallback = {
        "symbol": rec.symbol or snap.get("symbol"),
        "qty": snap.get("qty"),
        "sellable": snap.get("sellable"),
        "t1_today": snap.get("t1_today"),
        "hold_locked": snap.get("hold_locked"),
        "stop_locked": snap.get("stop_locked"),
        "last": snap.get("last"),
        "open_px": snap.get("open_px"),
        "prev_close": snap.get("prev_close"),
        "cost": snap.get("entry_price"),
        "peak_high": snap.get("peak_high"),
        "working_stop": rec.working_stop if rec.working_stop is not None else snap.get("working_stop"),
        "path_hit": snap.get("path_hit"),
        "path_fill_px": snap.get("path_fill_px"),
        "path_action_kind": snap.get("path_action_kind"),
        "path_stop_kind": snap.get("path_stop_kind"),
        "signal_ok": snap.get("signal_ok"),
        "overnight_high_ok": snap.get("overnight_high_ok"),
        "buy_time": snap.get("buy_time"),
        "session": snap.get("session"),
    }
    for key in _REPLAY_KW_KEYS:
        if key in src and src[key] is not None:
            out[key] = src[key]
        elif fallback.get(key) is not None:
            out[key] = fallback[key]
    out.pop("bars", None)
    return out


def paper_kwargs_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Rebuild paper_exit_decision kwargs from a mismatch/shadow record. No bars."""
    if record.get("paper_kwargs"):
        src = dict(record["paper_kwargs"])
        src.pop("bars", None)
        return {k: src[k] for k in _REPLAY_KW_KEYS if k in src}
    snap = dict(record.get("context_snapshot") or {})
    fake = ShadowCompareRecord(
        timestamp=str(record.get("timestamp") or ""),
        symbol=str(record.get("symbol") or snap.get("symbol") or ""),
        legacy_action=str(record.get("legacy_action") or "HOLD"),
        new_action=str(record.get("unified_action") or record.get("new_action") or "HOLD"),
        legacy_price=record.get("legacy_price"),
        new_price=record.get("unified_price", record.get("new_price")),
        legacy_factor=None,
        new_factor=None,
        legacy_reason=None,
        new_reason=None,
        reason_code=record.get("unified_reason_code"),
        quantity_ratio_new=record.get("unified_quantity"),
        quantity_ratio_legacy=record.get("legacy_quantity"),
        working_stop=record.get("working_stop", snap.get("working_stop")),
        overnight_open_protect_px=record.get("open_protect"),
        path_available=bool(snap.get("path_hit")),
        match_action=True,
        match_price=True,
        match_qty=True,
        context_snapshot=snap,
        position_state=dict(record.get("position_snapshot") or record.get("position_state") or {}),
    )
    return _scalar_paper_kwargs(None, fake)


def build_replayable_record(
    rec: ShadowCompareRecord,
    *,
    paper_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full mismatch/SELL payload: enough to replay, no minute bars."""
    payload = _shadow_payload(rec, full=True)
    payload["paper_kwargs"] = _scalar_paper_kwargs(paper_kwargs, rec)
    payload["unified_action"] = rec.new_action
    payload["unified_price"] = rec.new_price
    payload["legacy_quantity"] = rec.quantity_ratio_legacy
    payload["unified_quantity"] = rec.quantity_ratio_new
    payload["legacy_reason_code"] = rec.legacy_rule
    payload["unified_reason_code"] = rec.unified_rule
    payload["open_protect"] = rec.overnight_open_protect_px
    payload["position_snapshot"] = rec.position_state
    payload["path"] = (rec.position_state or {}).get("path")
    payload["config_version"] = rec.config_version
    return payload


def _is_rule_candidate_ctx(legacy: dict[str, Any], rec: ShadowCompareRecord, ctx: DecisionContext) -> bool:
    if rec.legacy_action in ("SELL", "HOLD_SHOW") or rec.new_action in ("SELL", "HOLD_SHOW"):
        return True
    if ctx.path_hit:
        return True
    stop = float(ctx.working_stop or 0)
    last = float(ctx.current_price or 0)
    if stop > 0 and last > 0 and last <= stop + 1e-12:
        return True
    if legacy.get("hit") or legacy.get("hit_show"):
        return True
    return False


def _shadow_payload(rec: ShadowCompareRecord, *, full: bool, sampled: bool = False) -> dict[str, Any]:
    rec.log_level = "full" if full else "minimal"
    rec.sampled = bool(sampled)
    payload = asdict(rec)
    if full:
        return payload
    payload["decision_trace"] = []
    payload["context_snapshot"] = {
        "symbol": rec.symbol,
        "working_stop": rec.working_stop,
        "path_available": rec.path_available,
    }
    return payload


def _record_shadow_metrics(rec: ShadowCompareRecord, *, mismatch: bool, partial: bool) -> None:
    _bump("shadow_evaluations")
    if mismatch:
        _bump("shadow_mismatches")
    else:
        _bump("shadow_exact_matches")
    if rec.legacy_action == "SELL":
        _bump("legacy_sell")
    if rec.new_action == "SELL":
        _bump("unified_sell")
    if (
        rec.legacy_action == "SELL"
        and rec.match_action
        and rec.match_price
        and rec.match_qty
        and rec.match_reason
    ):
        _bump("sell_exact_match")
    if partial:
        _bump("partial_sell")
    for step in rec.decision_trace or ():
        if not isinstance(step, dict):
            continue
        rule = str(step.get("rule") or "")
        if not rule:
            continue
        if step.get("candidate") is True:
            _bump(f"candidate_by_reason.{rule}")
        if step.get("winner") is True:
            _bump(f"winner_by_reason.{rule}")


def emit_shadow_record(payload: dict[str, Any]) -> None:
    _SHADOW_BUFFER.append(payload)
    if len(_SHADOW_BUFFER) > 5000:
        del _SHADOW_BUFFER[: len(_SHADOW_BUFFER) - 5000]
    if _SHADOW_HOOK is not None:
        try:
            _SHADOW_HOOK(payload)
        except Exception:  # noqa: BLE001
            pass


def run_unified_exit(ctx: DecisionContext) -> tuple[ExitDecision, dict[str, Any]]:
    dec = _ENGINE.evaluate(ctx)
    return dec, exit_decision_to_paper_dict(dec)


def maybe_shadow_and_select(
    legacy: dict[str, Any],
    *,
    paper_kwargs: dict[str, Any],
    use_unified: bool | None = None,
    shadow: bool | None = None,
    ctx: DecisionContext | None = None,
) -> dict[str, Any]:
    """Shadow 只记录；默认仍返回 legacy。use_unified=True 才切换。

    任何 Unified / Compare / 日志异常都返回入参 legacy，不改决策。
    """
    try:
        use = USE_UNIFIED_EXIT_ENGINE if use_unified is None else bool(use_unified)
        sh = SHADOW_UNIFIED_EXIT_ENGINE if shadow is None else bool(shadow)
        if not use and not sh:
            return legacy
        if ctx is None:
            ctx = build_exit_context_from_paper_kwargs(**paper_kwargs)
        try:
            dec, adapted = run_unified_exit(ctx)
        except Exception as exc:  # noqa: BLE001
            _note_shadow_error("unified_engine", exc, ctx, primary_failover=bool(use))
            return legacy
        if sh:
            try:
                global _HOLD_SAMPLE_SEQ
                rec = compare_paper_vs_exit(legacy, dec, ctx)
                mismatch = bool(rec.mismatch_class) or not (
                    rec.match_action and rec.match_price and rec.match_qty and rec.match_reason
                )
                candidate = _is_rule_candidate_ctx(legacy, rec, ctx)
                sell = rec.legacy_action == "SELL" or rec.new_action == "SELL"
                partial = bool(
                    (rec.quantity_ratio_legacy is not None and rec.quantity_ratio_legacy < 1.0 - 1e-12)
                    or (rec.quantity_ratio_new is not None and rec.quantity_ratio_new < 1.0 - 1e-12)
                )
                _record_shadow_metrics(rec, mismatch=mismatch, partial=partial)
                if mismatch or sell or partial or candidate:
                    emit_shadow_record(
                        build_replayable_record(rec, paper_kwargs=paper_kwargs)
                    )
                else:
                    _HOLD_SAMPLE_SEQ += 1
                    if _HOLD_SAMPLE_SEQ % max(1, int(SHADOW_HOLD_SAMPLE_EVERY)) == 0:
                        emit_shadow_record(_shadow_payload(rec, full=False, sampled=True))
            except Exception as exc:  # noqa: BLE001
                _note_shadow_error("compare_or_log", exc, ctx, count_eval=True)
        if use:
            return adapted
        return legacy
    except Exception as exc:  # noqa: BLE001
        _note_shadow_error("maybe_shadow_and_select", exc)
        return legacy
