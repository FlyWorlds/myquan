"""Exit 引擎开关与 Shadow Compare（默认不切换生产路径）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from strategy.core.exit_decision import ExitDecision
from strategy.core.factor_result import DecisionContext
from strategy.exit_rules.engine import ExitDecisionEngine, exit_decision_to_paper_dict

# 生产默认：不切换；Shadow 默认关（测试可开）
USE_UNIFIED_EXIT_ENGINE = False
SHADOW_UNIFIED_EXIT_ENGINE = False

_SHADOW_BUFFER: list[dict[str, Any]] = []
_SHADOW_HOOK: Callable[[dict[str, Any]], None] | None = None
_ENGINE = ExitDecisionEngine()


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
    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    position_state: dict[str, Any] = field(default_factory=dict)
    mismatch_class: str = ""


def set_shadow_hook(hook: Callable[[dict[str, Any]], None] | None) -> None:
    global _SHADOW_HOOK
    _SHADOW_HOOK = hook


def clear_shadow_buffer() -> None:
    _SHADOW_BUFFER.clear()


def get_shadow_buffer() -> list[dict[str, Any]]:
    return list(_SHADOW_BUFFER)


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

    mm = ""
    if not (match_action and match_price and match_qty):
        mm = classify_mismatch(
            legacy_action=la,
            new_action=na,
            legacy_kind=str(legacy.get("kind") or ""),
            new_reason_code=str(dec.reason_code.value if dec.reason_code else ""),
            path_available=bool(ctx.path_hit),
        )

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
        decision_trace=list(dec.trace or ()),
        position_state={
            "qty": ctx.qty,
            "sellable": ctx.sellable,
            "t1_today": ctx.t1_today,
        },
        mismatch_class=mm,
    )


def run_unified_exit(ctx: DecisionContext) -> tuple[ExitDecision, dict[str, Any]]:
    dec = _ENGINE.evaluate(ctx)
    return dec, exit_decision_to_paper_dict(dec)


def maybe_shadow_and_select(
    legacy: dict[str, Any],
    *,
    paper_kwargs: dict[str, Any],
    use_unified: bool | None = None,
    shadow: bool | None = None,
) -> dict[str, Any]:
    """Shadow 只记录；默认仍返回 legacy。use_unified=True 才切换。"""
    use = USE_UNIFIED_EXIT_ENGINE if use_unified is None else bool(use_unified)
    sh = SHADOW_UNIFIED_EXIT_ENGINE if shadow is None else bool(shadow)
    if not use and not sh:
        return legacy
    ctx = build_exit_context_from_paper_kwargs(**paper_kwargs)
    dec, adapted = run_unified_exit(ctx)
    if sh:
        rec = compare_paper_vs_exit(legacy, dec, ctx)
        payload = asdict(rec)
        _SHADOW_BUFFER.append(payload)
        if len(_SHADOW_BUFFER) > 5000:
            del _SHADOW_BUFFER[: len(_SHADOW_BUFFER) - 5000]
        if _SHADOW_HOOK is not None:
            try:
                _SHADOW_HOOK(payload)
            except Exception:  # noqa: BLE001
                pass
    if use:
        return adapted
    return legacy
