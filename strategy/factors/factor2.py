"""因子2：回撤阶梯补仓（叠在策略权益曲线上的资金管理）。

真源：strategy.dd_topup
默认百分比见 dd_topup.DEFAULT_*；策略 bindings / BacktestConfig 可覆盖（开闭）。
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.dd_topup import (
    DEFAULT_ADD_PCT,
    DEFAULT_ADD_PCTS,
    DEFAULT_LEVELS,
    DEFAULT_MAX_INJECT_PCT,
    add_pcts_label,
    add_target,
    desired_layers,
    drawdown,
    filter_desc,
    format_rules,
    levels_label,
    resolve_topup_params,
    simulate_dd_topup,
    step_dd_topup,
    summarize_overlay,
)

FACTOR_ID = "factor2"
FACTOR_NAME = "因子2"


def factor2_rules(
    add_pct: float | None = None,
    levels: Sequence[float] = DEFAULT_LEVELS,
    *,
    add_pcts: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
) -> str:
    return format_rules(
        add_pct=add_pct,
        levels=levels,
        add_pcts=add_pcts,
        max_inject_pct=max_inject_pct,
    )


def factor2_signal(
    *,
    equity: float,
    year_peak: float,
    layers: int = 0,
    max_reached: int | None = None,
    stack: list[float] | None = None,
    add_pct: float | None = None,
    add_pcts: Sequence[float] | None = None,
    levels: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
    capital_base: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    """根据当前权益回撤给出建议档位（不下单，仅信号）。"""
    pcts, lv, cap = resolve_topup_params(
        add_pct=add_pct,
        add_pcts=add_pcts,
        levels=levels,
        max_inject_pct=max_inject_pct,
    )
    dd = drawdown(float(equity), float(year_peak))
    reached = int(max_reached if max_reached is not None else max(layers, 0))
    want_up = add_target(dd, lv)
    want_down = desired_layers(dd, max(reached, want_up), lv)
    cur = int(layers if stack is None else len(stack))
    if cur < want_up:
        action = "inject"
        note = f"建议加至{want_up}档（当前{cur}）"
    elif cur > want_down:
        action = "withdraw"
        note = f"建议减至{want_down}档（当前{cur}）"
    else:
        action = "hold"
        note = f"维持{cur}档"
    base = float(capital_base) if capital_base and capital_base > 0 else float(equity)
    inj = float(sum(stack)) if stack else 0.0
    room = max(0.0, cap * base - inj)
    next_pct = float(pcts[cur]) if cur < len(pcts) else 0.0
    add_amt = min(next_pct * base, room) if action == "inject" else 0.0
    return {
        "action": action,
        "dd": dd,
        "dd_pct": dd * 100.0,
        "layers": cur,
        "target_layers": want_up if action == "inject" else want_down,
        "suggest_add": add_amt,
        "alert": note,
        "add_pcts": pcts,
        "levels": lv,
        "max_inject_pct": cap,
    }


def run_factor2_on_equity(
    equity: pd.Series,
    *,
    initial_cash: float = 100_000.0,
    add_pct: float | None = None,
    add_pcts: Sequence[float] | None = None,
    levels: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, float]]:
    """对权益曲线跑因子2，返回净值表、事件、摘要。"""
    pcts, lv, cap = resolve_topup_params(
        add_pct=add_pct,
        add_pcts=add_pcts,
        levels=levels,
        max_inject_pct=max_inject_pct,
    )
    nav, events = simulate_dd_topup(
        equity,
        initial_cash=initial_cash,
        add_pcts=pcts,
        levels=lv,
        max_inject_pct=cap,
    )
    base_final = float(equity.sort_index().iloc[-1]) if len(equity) else None
    summary = summarize_overlay(nav, initial_cash=initial_cash, base_final=base_final)
    return nav, events, summary


def _default_description() -> str:
    pcts, lv, cap = resolve_topup_params()
    return (
        f"回撤阶梯补仓：权益回撤≥{levels_label(lv)}各加总本金×"
        f"{add_pcts_label(pcts)}%；上限{cap*100:.0f}%；回落减档，到0结清"
    )


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=_default_description(),
    rules_text=factor2_rules(),
    implemented=True,
    signal=factor2_signal,
    meta={
        "kind": "dd_topup",
        "add_pct": DEFAULT_ADD_PCT,
        "add_pcts": DEFAULT_ADD_PCTS,
        "levels": DEFAULT_LEVELS,
        "max_inject_pct": DEFAULT_MAX_INJECT_PCT,
        "simulate": simulate_dd_topup,
        "run_on_equity": run_factor2_on_equity,
        "step": step_dd_topup,
        "resolve_params": resolve_topup_params,
        "filter_desc": filter_desc,
        "overlay": True,
        "requires": "strategy_equity_curve",
        "adjust": "qfq",
        "tunable": ("add_pct", "add_pcts", "levels", "max_inject_pct"),
    },
)

register_factor(SPEC)
