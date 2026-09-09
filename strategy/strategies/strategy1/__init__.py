"""援军战法（strategy1，默认）：因子26（浮盈回落一半止盈）+ 因子2（回撤预警）+ 因子22（收盘动量再买）。

调参（开闭，勿改算法本体）：
  · 因子26 阈值/过滤 → pullback_wave_stop / bindings（买同 open_break；卖=浮盈回落一半）
  · 因子2 预警阈值 → dd_alert.DEFAULT_* / derive_thresholds(equity)
  · 因子22 再买阈值 → bindings bounce_pct / candle / mode；真源 close_momentum
  · 旧版权益注资叠加已默认关闭；若需可用 apply_factor2_overlay=True 临时启用 dd_topup
"""

from __future__ import annotations

from typing import Any, Sequence

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy1.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
    strategy1_factor_filter,
)
from strategy.strategies.strategy1.decision import Strategy1Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _factor2_binding():
    for b in FACTOR_BINDINGS:
        if b.enabled and b.factor_id == "factor2":
            return b
    return None


def _resolve_factor2_from_cfg(
    cfg: Any,
    *,
    apply_factor2_overlay: bool = False,
) -> tuple[bool, tuple[float, ...], tuple[float, ...], float] | None:
    """仅当显式要求权益叠加时解析 dd_topup 参数；默认预警模式不叠加。"""
    from strategy.dd_topup import resolve_topup_params

    binding = _factor2_binding()
    if binding is None:
        return None

    # 绑定声明 overlay=False → 默认不叠加
    binding_overlay = bool(binding.params.get("overlay", False))
    cfg_en = getattr(cfg, "factor2_enabled", None)
    if cfg_en is False:
        return None
    if not apply_factor2_overlay and not binding_overlay:
        return None
    if apply_factor2_overlay is False and cfg_en is not True and not binding_overlay:
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
        add_pcts=add_pcts if add_pcts is not None else None,
        levels=levels if levels is not None else None,
        max_inject_pct=float(max_inj) if max_inj is not None else None,
    )
    return True, pcts, lv, cap


def _apply_factor2_overlay(
    result: Any,
    *,
    initial_cash: float,
    add_pcts: Sequence[float],
    levels: Sequence[float],
    max_inject_pct: float,
    verbose: bool = True,
) -> dict[str, Any] | None:
    """可选：旧版权益注资叠加（默认不启用）。"""
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return None

    from strategy.dd_topup import add_pcts_label, levels_label
    from strategy.dd_topup import simulate_dd_topup, summarize_overlay

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
        "binding": _factor2_binding(),
        "nav": nav,
        "events": events,
        "summary": summary,
        "add_pcts": tuple(float(x) for x in add_pcts),
        "levels": tuple(levels),
        "max_inject_pct": float(max_inject_pct),
        "legacy_overlay": True,
    }
    try:
        result.factor2_overlay = overlay
    except Exception:
        pass

    if verbose and summary:
        print("\n========== 援军战法 · 因子2（旧版权益叠加，可选）==========")
        print(
            f"援军战法期末:  {summary.get('base_final', 0):,.2f}  "
            f"(+{summary.get('base_return_pct', 0):.2f}%)"
        )
        print(
            f"叠加因子2后: {summary.get('own_equity', 0):,.2f}  "
            f"(+{summary.get('own_return_pct', 0):.2f}%)"
        )
        print(
            f"档位 {levels_label(levels)}  "
            f"+总本金×{add_pcts_label(add_pcts)}%  "
            f"上限{float(max_inject_pct)*100:.0f}%  事件{len(events)}次"
        )
    return overlay


def _attach_factor2_alert_meta(result: Any, verbose: bool = True) -> None:
    """把预警阈值挂到回测结果，便于报告/盯盘读取；不改权益。"""
    binding = _factor2_binding()
    if binding is None:
        return
    from strategy.dd_alert import derive_thresholds, format_rules

    th = derive_thresholds(
        hist_max_dd=binding.params.get("hist_max_dd"),
        avg_yearly_max_dd=binding.params.get("avg_yearly_max_dd"),
    )
    # 若有权益曲线，可按本回测重标定
    eq = getattr(result, "equity_curve", None)
    if eq is not None and not getattr(eq, "empty", True):
        try:
            th = derive_thresholds(eq)
        except Exception:
            pass
    meta = {
        "mode": "alert_only",
        "thresholds": th.as_dict(),
        "label": th.label(),
        "rules": format_rules(th),
    }
    try:
        result.factor2_alert = meta
    except Exception:
        pass
    if verbose:
        print("\n========== 援军战法 · 因子2（回撤预警，不介入）==========")
        print(th.label())
        print(
            f"加仓预警 ≥{th.add_alert_dd*100:.0f}%  |  "
            f"减仓预警 ≤{th.reduce_alert_dd*100:.0f}%（须曾进加仓区）  |  "
            f"接近历史最大 {th.hist_max_dd*100:.1f}% 停止加仓"
        )


def run_strategy1(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
    apply_factor2_overlay: bool = False,
    factor2_add_pct: float | None = None,
    factor2_add_pcts: Sequence[float] | None = None,
    factor2_levels: Sequence[float] | None = None,
    factor2_max_inject_pct: float | None = None,
) -> tuple[Any, Any]:
    """援军战法回测：因子26 浮盈回落一半止盈；因子2 默认只挂预警阈值（不注资）。

    apply_factor2_overlay=True 时可启用旧版 dd_topup 权益叠加。
    """
    from dataclasses import replace

    from strategy.config import KAICHENG
    from strategy.runner import run_open_break

    if cfg is None:
        cfg = KAICHENG
    # 策略一默认：日线层用 day_high 锚 + 浮盈回落一半
    if str(getattr(cfg, "stop_anchor", "open") or "open") == "open":
        cfg = replace(cfg, stop_anchor="day_high")
    kw: dict[str, Any] = {}
    if factor2_add_pct is not None:
        kw["factor2_add_pct"] = factor2_add_pct
    if factor2_add_pcts is not None:
        kw["factor2_add_pcts"] = tuple(float(x) for x in factor2_add_pcts)
    if factor2_levels is not None:
        kw["factor2_levels"] = tuple(float(x) for x in factor2_levels)
    if factor2_max_inject_pct is not None:
        kw["factor2_max_inject_pct"] = float(factor2_max_inject_pct)
    if kw:
        cfg = replace(cfg, **kw)

    result, daily = run_open_break(
        cfg,
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
    )
    _attach_factor2_alert_meta(result, verbose=verbose)

    resolved = _resolve_factor2_from_cfg(
        cfg, apply_factor2_overlay=apply_factor2_overlay
    )
    if resolved is not None:
        _, pcts, lv, cap = resolved
        _apply_factor2_overlay(
            result,
            initial_cash=float(getattr(cfg, "initial_cash", 100_000.0)),
            add_pcts=pcts,
            levels=lv,
            max_inject_pct=cap,
            verbose=verbose,
        )
    return result, daily


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy
    from strategy.config import KAICHENG

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "援军战法：因子26 开盘阈值买/多层止盈"
            " + 因子2 回撤加减仓预警（回测不注资）"
            " + 因子22 收盘动量再买"
            " + 因子13A 质量带合格池 + 因子16 龙头排序（定盘池，研究）"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy1,
        default_config=KAICHENG,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("open_break3", "s1", "策略一", "援军战法"),
        implemented=True,
        meta={
            "default": False,
            "legacy_id": "open_break3",
            "factors": ("factor26", "factor2", "factor13a", "factor16", "factor22"),
            "pool_chain": "factor13a_quality_band → factor16_pl_ratio_rank",
            "pool_size": 10,
            "stop_anchor": "day_high",
            "factor2_overlay": False,
            "factor2_alert_only": True,
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "strategy1_factor_filter",
    "Strategy1Decision",
    "create_decision_engine",
    "run_strategy1",
    "_apply_factor2_overlay",
]
