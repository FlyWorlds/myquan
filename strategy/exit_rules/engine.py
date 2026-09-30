"""ExitDecisionEngine：按 paper_exit_decision 真实顺序编排 exit 规则。

不改 Factor26 数学；不写账本；不读 holdingStocks 全局。
顺序真源：docs/EXIT_RULE_ORDER.md
"""

from __future__ import annotations

from typing import Any

from strategy.core.exit_decision import ExitAction, ExitDecision, ReasonCode
from strategy.core.factor_result import DecisionContext
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.exit_rules.working_stop import evaluate_working_stop
from strategy.pullback_wave_stop import cost_hard_stop_px, is_half_stop_kind, session_high_never_printed_stop


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x if x is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _trace_step(rule: str, result: str, **extra: Any) -> dict[str, Any]:
    row = {"rule": rule, "result": result}
    row.update(extra)
    return row


def _annotate_candidates(
    trace: list[dict[str, Any]],
    *,
    cand_open: bool,
    cand_last: bool,
    cand_path: bool,
    winner: str,
) -> None:
    """Record pre-priority candidates vs the actual winner. Does not change order."""
    for rule_id, candidate in (
        ("OPEN_PROTECT", cand_open),
        ("PATH", cand_path),
        ("WORKING_STOP", cand_last),
    ):
        if not candidate:
            continue
        win = rule_id == winner
        trace.append(
            {
                "rule": rule_id,
                "candidate": True,
                "winner": win,
                "superseded_by": None if win else winner,
            }
        )


class ExitDecisionEngine:
    """统一卖出编排（与 paper_exit_decision 对齐）。"""

    def evaluate(self, ctx: DecisionContext) -> ExitDecision:
        trace: list[dict[str, Any]] = []
        qty = int(ctx.qty or ctx.shares or 0)
        if qty <= 0:
            trace.append(_trace_step("qty", "empty"))
            return ExitDecision.hold(reason="", trace=trace)

        cost = _f(ctx.entry_price)
        open_f = _f(ctx.open_px if ctx.open_px is not None else ctx.day_open)
        last_px = _f(ctx.current_price)
        stop_f = _f(ctx.working_stop)
        path_px = _f(ctx.path_fill_px)
        path_hit = bool(ctx.path_hit)
        t1 = bool(ctx.t1_today)

        # --- 信号：开盘保护 ---
        open_rule = evaluate_overnight_open_protect(ctx)
        open_hit = bool(open_rule.triggered)
        protect = _f((open_rule.metadata or {}).get("protect_px"))
        trace.append(
            _trace_step(
                "open_protect",
                "triggered" if open_hit else "not_triggered",
                price=open_rule.price,
                protect_px=protect,
            )
        )

        # --- 信号：working stop / path ---
        last_rule = evaluate_working_stop(ctx)
        last_hit = bool(last_rule.triggered)
        path_ok = bool(path_hit and path_px > 0)
        cand_open = bool(open_hit)
        cand_last = bool(last_hit)
        cand_path = bool(path_ok)
        trace.append(
            _trace_step(
                "working_stop",
                "triggered" if last_hit else "not_triggered",
                price=last_rule.price,
            )
        )
        trace.append(
            _trace_step(
                "path",
                "ok" if path_ok else "idle",
                path_fill_px=path_px,
                path_hit=path_hit,
            )
        )

        # --- T+1 收窄触达信号（与 paper 一致）---
        if t1 and cost > 0:
            hard = float(cost_hard_stop_px(cost) or 0)
            open_hit = False
            last_hit = bool(hard > 0 and last_px > 0 and last_px <= hard + 1e-12)
            path_ok = bool(
                path_hit
                and path_px > 0
                and hard > 0
                and path_px <= hard + 1e-6
                and last_px > 0
                and last_px <= hard * 1.003 + 1e-12
            )
            trace.append(
                _trace_step(
                    "t1_narrow",
                    "applied",
                    hard=hard,
                    open_hit=False,
                    last_hit=last_hit,
                    path_ok=path_ok,
                )
            )

        # 今开已破工作卖价且当日最高从未印到该价 → 升为开盘保护
        if (not t1) and (not open_hit) and last_hit:
            dh = _f(getattr(ctx, "day_high", 0))
            if session_high_never_printed_stop(
                open_px=open_f,
                last_px=last_px,
                working_stop=stop_f,
                day_high=dh,
            ):
                open_hit = True
                cand_open = True
                trace.append(
                    _trace_step("gap_through_stop", "open_protect", price=open_f)
                )

        hit_show = bool(open_hit or last_hit or path_ok)
        if not hit_show:
            trace.append(_trace_step("hit_show", "false"))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.NONE.value,
            )
            return ExitDecision.hold(reason="", trace=trace)

        # --- show-only 拦截 ---
        if t1:
            trace.append(_trace_step("t1", "block_fill"))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.T1_BLOCK.value,
            )
            return ExitDecision.hold(
                reason="t1",
                reason_code=ReasonCode.T1_BLOCK,
                show_only=True,
                trace=trace,
                hit_show=True,
            )
        if ctx.hold_locked:
            trace.append(_trace_step("hold_lock", "block_fill"))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.HOLD_LOCK.value,
            )
            return ExitDecision.hold(
                reason="hold_lock",
                reason_code=ReasonCode.HOLD_LOCK,
                show_only=True,
                trace=trace,
                hit_show=True,
            )
        if ctx.stop_locked:
            trace.append(_trace_step("limit_down", "block_fill"))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.LIMIT_DOWN.value,
            )
            return ExitDecision.hold(
                reason="limit_down",
                reason_code=ReasonCode.LIMIT_DOWN,
                show_only=True,
                trace=trace,
                hit_show=True,
            )
        sell_i = int(ctx.sellable if ctx.sellable is not None else 0)
        if sell_i <= 0:
            trace.append(_trace_step("not_sellable", "block_fill"))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.NOT_SELLABLE.value,
            )
            return ExitDecision.hold(
                reason="not_sellable",
                reason_code=ReasonCode.NOT_SELLABLE,
                show_only=True,
                trace=trace,
                hit_show=True,
            )
        if not bool(ctx.signal_ok):
            trace.append(_trace_step("wait_auction", "block_fill"))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.WAIT_AUCTION.value,
            )
            return ExitDecision.hold(
                reason="wait_auction",
                reason_code=ReasonCode.WAIT_AUCTION,
                show_only=True,
                trace=trace,
                hit_show=True,
            )

        # --- 成交优先级：open → path → last ---
        if open_hit:
            trace.append(_trace_step("fill", "open_protect", price=open_f))
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.OPEN_PROTECT.value,
            )
            return ExitDecision.sell(
                price=open_f,
                reason="open_protect",
                reason_code=ReasonCode.OPEN_PROTECT,
                quantity_ratio=1.0,
                factor_id=None,
                trace=trace,
                kind="open_protect",
                action_kind="full",
                open_bell=True,
            )

        if path_ok:
            half = is_half_stop_kind(ctx.path_stop_kind, ctx.path_action_kind)
            ratio = 0.5 if half else 1.0
            action_kind = "half" if half else (ctx.path_action_kind or "full")
            if action_kind == "half":
                ratio = 0.5
            elif action_kind == "full":
                ratio = 1.0
            trace.append(
                _trace_step(
                    "fill",
                    "path",
                    price=path_px,
                    quantity_ratio=ratio,
                    stop_kind=ctx.path_stop_kind,
                )
            )
            _annotate_candidates(
                trace,
                cand_open=cand_open,
                cand_last=cand_last,
                cand_path=cand_path,
                winner=ReasonCode.PATH.value,
            )
            return ExitDecision.sell(
                price=path_px,
                reason="path",
                reason_code=ReasonCode.PATH,
                quantity_ratio=ratio,
                factor_id="factor26",
                trace=trace,
                kind="path",
                action_kind=action_kind,
                stop_kind=str(ctx.path_stop_kind or ""),
            )

        # 走到这里时 hit_show 已保证 last_hit（或 T+1 硬保护 last）
        fill = stop_f if stop_f > 0 else last_px
        if t1 and cost > 0:
            hard = float(cost_hard_stop_px(cost) or 0)
            if hard > 0:
                fill = hard
        trace.append(_trace_step("fill", "working_stop", price=fill))
        _annotate_candidates(
            trace,
            cand_open=cand_open,
            cand_last=cand_last,
            cand_path=cand_path,
            winner=ReasonCode.WORKING_STOP.value,
        )
        return ExitDecision.sell(
            price=fill,
            reason="last",
            reason_code=ReasonCode.WORKING_STOP,
            quantity_ratio=1.0,
            factor_id=None,
            trace=trace,
            kind="last",
            action_kind="full",
        )


def exit_decision_to_paper_dict(dec: ExitDecision) -> dict[str, Any]:
    """将 ExitDecision 适配为 legacy paper_exit_decision 返回形状。"""
    empty = {
        "hit": False,
        "hit_show": False,
        "fill_px": 0.0,
        "kind": "",
        "action_kind": "",
        "stop_kind": "",
        "reason": "",
        "open_bell": False,
    }
    meta = dict(dec.metadata or {})
    if dec.action == ExitAction.HOLD:
        out = dict(empty)
        if dec.show_only or meta.get("hit_show"):
            out["hit_show"] = True
            out["reason"] = str(dec.reason or "")
        return out
    return {
        "hit": True,
        "hit_show": True,
        "fill_px": float(dec.price or 0),
        "kind": str(meta.get("kind") or ""),
        "action_kind": str(meta.get("action_kind") or ("half" if dec.quantity_ratio < 1.0 - 1e-12 else "full")),
        "stop_kind": str(meta.get("stop_kind") or ""),
        "reason": str(dec.reason or ""),
        "open_bell": bool(meta.get("open_bell")),
    }
