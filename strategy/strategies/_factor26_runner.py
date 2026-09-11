"""因子26类策略的共享回测执行器。

本模块只接收显式策略绑定与标签，不导入任何具体 strategyN，避免策略间调用。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from strategy.core.protocols import FactorBinding


def factor_binding(
    bindings: Sequence[FactorBinding], factor_id: str
) -> FactorBinding | None:
    return next(
        (b for b in bindings if b.enabled and b.factor_id == factor_id),
        None,
    )


def resolve_factor2_from_cfg(
    cfg: Any,
    *,
    bindings: Sequence[FactorBinding],
    apply_factor2_overlay: bool = False,
) -> tuple[bool, tuple[float, ...], tuple[float, ...], float] | None:
    """仅显式要求时解析旧版权益注资参数。"""
    from strategy.dd_topup import resolve_topup_params

    binding = factor_binding(bindings, "factor2")
    if binding is None:
        return None
    binding_overlay = bool(binding.params.get("overlay", False))
    cfg_en = getattr(cfg, "factor2_enabled", None)
    if cfg_en is False:
        return None
    if not apply_factor2_overlay and not binding_overlay:
        return None
    if not apply_factor2_overlay and cfg_en is not True and not binding_overlay:
        return None

    add = getattr(cfg, "factor2_add_pct", None)
    if add is None:
        add = binding.params.get("add_pct")
    add_pcts = getattr(cfg, "factor2_add_pcts", None)
    if add_pcts is None:
        add_pcts = binding.params.get("add_pcts")
    levels = getattr(cfg, "factor2_levels", None)
    if levels is None:
        levels = binding.params.get("levels")
    max_inj = getattr(cfg, "factor2_max_inject_pct", None)
    if max_inj is None:
        max_inj = binding.params.get("max_inject_pct")
    pcts, lv, cap = resolve_topup_params(
        add_pct=float(add) if add is not None else None,
        add_pcts=add_pcts,
        levels=levels,
        max_inject_pct=float(max_inj) if max_inj is not None else None,
    )
    return True, pcts, lv, cap


def apply_factor2_overlay(
    result: Any,
    *,
    bindings: Sequence[FactorBinding],
    strategy_name: str,
    initial_cash: float,
    add_pcts: Sequence[float],
    levels: Sequence[float],
    max_inject_pct: float,
    verbose: bool = True,
) -> dict[str, Any] | None:
    """可选旧版权益注资叠加；默认不启用。"""
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return None

    from strategy.dd_topup import (
        add_pcts_label,
        levels_label,
        simulate_dd_topup,
        summarize_overlay,
    )

    nav, events = simulate_dd_topup(
        eq,
        initial_cash=float(initial_cash),
        add_pcts=add_pcts,
        levels=levels,
        max_inject_pct=max_inject_pct,
    )
    base_final = float(eq.sort_index().iloc[-1]) if len(eq) else None
    summary = summarize_overlay(nav, initial_cash=initial_cash, base_final=base_final)
    overlay = {
        "binding": factor_binding(bindings, "factor2"),
        "nav": nav,
        "events": events,
        "summary": summary,
        "add_pcts": tuple(float(x) for x in add_pcts),
        "levels": tuple(levels),
        "max_inject_pct": float(max_inject_pct),
        "legacy_overlay": True,
    }
    result.factor2_overlay = overlay
    if verbose and summary:
        print(f"\n========== {strategy_name} · 因子2（旧版权益叠加，可选）==========")
        print(
            f"基础期末: {summary.get('base_final', 0):,.2f}  "
            f"(+{summary.get('base_return_pct', 0):.2f}%)"
        )
        print(
            f"叠加后:   {summary.get('own_equity', 0):,.2f}  "
            f"(+{summary.get('own_return_pct', 0):.2f}%)"
        )
        print(
            f"档位 {levels_label(levels)}  +总本金×{add_pcts_label(add_pcts)}%  "
            f"上限{float(max_inject_pct)*100:.0f}%  事件{len(events)}次"
        )
    return overlay


def attach_factor2_alert_meta(
    result: Any,
    *,
    bindings: Sequence[FactorBinding],
    strategy_name: str,
    verbose: bool = True,
) -> None:
    """挂载本策略因子2预警元数据，不改权益。"""
    binding = factor_binding(bindings, "factor2")
    if binding is None:
        return
    from strategy.dd_alert import derive_thresholds, format_rules

    th = derive_thresholds(
        hist_max_dd=binding.params.get("hist_max_dd"),
        avg_yearly_max_dd=binding.params.get("avg_yearly_max_dd"),
    )
    eq = getattr(result, "equity_curve", None)
    if eq is not None and not getattr(eq, "empty", True):
        try:
            th = derive_thresholds(eq)
        except Exception:
            pass
    result.factor2_alert = {
        "mode": "alert_only",
        "thresholds": th.as_dict(),
        "label": th.label(),
        "rules": format_rules(th),
    }
    if verbose:
        print(f"\n========== {strategy_name} · 因子2（回撤预警，不介入）==========")
        print(th.label())


def run_factor26_strategy(
    cfg: Any = None,
    *,
    bindings: Sequence[FactorBinding],
    strategy_name: str,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
    apply_factor2_overlay: bool = False,
    factor2_add_pct: float | None = None,
    factor2_add_pcts: Sequence[float] | None = None,
    factor2_levels: Sequence[float] | None = None,
    factor2_max_inject_pct: float | None = None,
) -> tuple[Any, Any]:
    """执行共享的因子26交易内核；策略差异全部由 bindings/cfg 注入。"""
    from strategy.config import KAICHENG
    from strategy.runner import run_open_break

    if cfg is None:
        cfg = KAICHENG
    if str(getattr(cfg, "stop_anchor", "open") or "open") == "open":
        cfg = replace(cfg, stop_anchor="day_high")
    overrides: dict[str, Any] = {}
    if factor2_add_pct is not None:
        overrides["factor2_add_pct"] = factor2_add_pct
    if factor2_add_pcts is not None:
        overrides["factor2_add_pcts"] = tuple(float(x) for x in factor2_add_pcts)
    if factor2_levels is not None:
        overrides["factor2_levels"] = tuple(float(x) for x in factor2_levels)
    if factor2_max_inject_pct is not None:
        overrides["factor2_max_inject_pct"] = float(factor2_max_inject_pct)
    if overrides:
        cfg = replace(cfg, **overrides)

    result, daily = run_open_break(
        cfg,
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
    )
    attach_factor2_alert_meta(
        result,
        bindings=bindings,
        strategy_name=strategy_name,
        verbose=verbose,
    )
    resolved = resolve_factor2_from_cfg(
        cfg,
        bindings=bindings,
        apply_factor2_overlay=apply_factor2_overlay,
    )
    if resolved is not None:
        _, pcts, levels, cap = resolved
        apply_factor2_overlay(
            result,
            bindings=bindings,
            strategy_name=strategy_name,
            initial_cash=float(getattr(cfg, "initial_cash", 100_000.0)),
            add_pcts=pcts,
            levels=levels,
            max_inject_pct=cap,
            verbose=verbose,
        )
    return result, daily
