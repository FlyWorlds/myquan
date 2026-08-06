"""回撤阶梯补仓（因子2 真源）：在策略权益曲线上追加/提出资金。

默认三档（相对年内权益高点）：
  · 回撤 ≥10%/20%/30% → 各追加「当前权益 × add_pct」（默认 10%）
  · 回落到 ≤20% → LIFO 减去 1 次追加
  · 再落到 ≤10% → 再减 1 次
  · 回撤到 0 → 剩余全部结清

数据口径与策略一相同：前复权日线回测权益，本模块不改复权方式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

# --- 默认参数（开闭：改默认只动此处；策略侧用 bindings / BacktestConfig 覆盖）---
DEFAULT_LEVELS: tuple[float, ...] = (0.10, 0.20, 0.30)
DEFAULT_ADD_PCT = 0.10


def normalize_levels(levels: Sequence[float] | None = None) -> tuple[float, ...]:
    raw = tuple(float(x) for x in (levels if levels is not None else DEFAULT_LEVELS))
    if not raw:
        return DEFAULT_LEVELS
    return tuple(sorted(raw))


def resolve_topup_params(
    *,
    add_pct: float | None = None,
    levels: Sequence[float] | None = None,
) -> tuple[float, tuple[float, ...]]:
    """解析补仓参数；None → 模块默认。后续调参不必改算法。"""
    pct = float(DEFAULT_ADD_PCT if add_pct is None else add_pct)
    if pct <= 0 or pct >= 1:
        raise ValueError(f"add_pct 应在 (0,1): {pct}")
    lv = normalize_levels(levels)
    return pct, lv


def levels_label(levels: Sequence[float] = DEFAULT_LEVELS) -> str:
    return "/".join(f"{float(x)*100:.0f}" for x in normalize_levels(levels))


def filter_desc(
    add_pct: float = DEFAULT_ADD_PCT,
    levels: Sequence[float] = DEFAULT_LEVELS,
) -> str:
    pct, lv = resolve_topup_params(add_pct=add_pct, levels=levels)
    return (
        f"叠在策略权益上：回撤{levels_label(lv)}各+当前×{pct*100:.0f}%；"
        f"回落减档，到0结清"
    )


def format_rules(
    add_pct: float = DEFAULT_ADD_PCT,
    levels: Sequence[float] = DEFAULT_LEVELS,
) -> str:
    """按当前参数生成规则文案（避免百分比写死在多处）。"""
    pct, lv = resolve_topup_params(add_pct=add_pct, levels=levels)
    lines = [
        "================================================================================",
        "  因子2 — 回撤阶梯补仓（权益曲线资金管理）",
        "================================================================================",
        "",
        "【作用】",
        "  叠在策略权益曲线之上：按年内回撤分档追加本金，回撤收窄时按档提出；",
        "  不改变买卖点；日线复权口径与策略一相同（前复权 qfq）。",
        "",
        "【分档（参数可配，以下为当前值）】",
    ]
    for i, level in enumerate(lv, 1):
        lines.append(
            f"  · 回撤 ≥{level*100:.0f}% → 追加当前权益 ×{pct*100:.0f}%（第{i}档）"
        )
    if len(lv) >= 2:
        lines.append(
            f"  · 回落到 ≤{lv[-2]*100:.0f}% → LIFO 减去 1 次追加"
        )
    lines.append(
        f"  · 再落到 ≤{lv[0]*100:.0f}% → 再减 1 次"
    )
    lines.extend(
        [
            "  · 回撤到 0 → 剩余全部结清",
            "",
            "【说明】",
            "  · 「当前权益」= 仿真账户总权益（含在途追加）",
            "  · 调参：改 dd_topup.DEFAULT_*，或策略 bindings / BacktestConfig 覆盖",
            "  · 年内高点按日历年重置；在途追加可跨年",
            "================================================================================",
        ]
    )
    return "\n".join(lines)


RULES_TEXT = format_rules()


def drawdown(equity: float, peak: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, 1.0 - float(equity) / float(peak))


def add_target(dd: float, levels: Sequence[float] = DEFAULT_LEVELS) -> int:
    n = 0
    for lv in levels:
        if dd + 1e-12 >= float(lv):
            n += 1
    return n


def desired_layers(
    dd: float,
    reached: int,
    levels: Sequence[float] = DEFAULT_LEVELS,
) -> int:
    """回落目标档数：深档保持；穿过次高档减 1；再到更低档再减；到 0 清零。"""
    if reached <= 0:
        return 0
    if dd <= 1e-12:
        return 0
    lv = sorted(float(x) for x in levels)
    if len(lv) < 2:
        return min(1, reached) if dd > 1e-12 else 0
    # 默认 10/20/30：>20 满档；>10 最多2；否则最多1
    hi, mid = lv[-1], lv[-2] if len(lv) >= 2 else lv[-1]
    lo = lv[-3] if len(lv) >= 3 else mid
    # 用 20/10 两道回落线（对应 levels 的中、低档）
    down_hi = mid  # ≤20% → 目标 ≤2
    down_lo = lo if len(lv) >= 3 else lv[0]  # ≤10% → 目标 ≤1
    if dd > down_hi + 1e-12:
        return min(len(lv), reached)
    if dd > down_lo + 1e-12:
        return min(max(len(lv) - 1, 1), reached)
    return min(1, reached)


@dataclass
class DdTopupState:
    working: float
    peak: float
    stack: list[float] = field(default_factory=list)
    max_reached: int = 0
    year: int | None = None

    @property
    def injected(self) -> float:
        return float(sum(self.stack))

    @property
    def layers(self) -> int:
        return len(self.stack)


def step_dd_topup(
    state: DdTopupState,
    *,
    ret: float,
    date_year: int,
    add_pct: float = DEFAULT_ADD_PCT,
    levels: Sequence[float] = DEFAULT_LEVELS,
) -> list[dict[str, Any]]:
    """推进一日：先乘收益，再按档追加/提出。返回当日事件列表。"""
    events: list[dict[str, Any]] = []
    if state.year is None or date_year != state.year:
        state.year = date_year
        state.peak = state.working
        state.max_reached = max(state.max_reached, len(state.stack))

    state.working *= 1.0 + float(ret)
    if state.working > state.peak + 1e-9:
        state.peak = state.working

    dd = drawdown(state.working, state.peak)
    at = add_target(dd, levels)
    if at > state.max_reached:
        state.max_reached = at

    while len(state.stack) < at:
        amt = float(add_pct) * state.working
        state.working += amt
        state.stack.append(amt)
        lv = levels[len(state.stack) - 1] if len(state.stack) <= len(levels) else levels[-1]
        events.append(
            {
                "event": "inject",
                "label": f"回撤≥{float(lv)*100:.0f}%追加当前×{float(add_pct)*100:.0f}%",
                "amount": amt,
                "dd": dd,
                "equity": state.working,
                "injected": state.injected,
                "layers": state.layers,
            }
        )
        dd = drawdown(state.working, state.peak)

    want = desired_layers(dd, state.max_reached, levels)
    while len(state.stack) > want:
        if want == 0 and len(state.stack) > 1 and dd <= 1e-12:
            amt = state.injected
            state.working -= amt
            state.stack.clear()
            events.append(
                {
                    "event": "withdraw_all",
                    "label": "回撤归0全部结清",
                    "amount": -amt,
                    "dd": 0.0,
                    "equity": state.working,
                    "injected": 0.0,
                    "layers": 0,
                }
            )
            state.max_reached = 0
            state.peak = state.working
            break

        amt = state.stack.pop()
        state.working -= amt
        if dd <= 1e-12:
            label = "回撤归0结清一档"
            ev = "withdraw_all" if not state.stack else "withdraw"
        elif len(levels) >= 2 and dd <= float(sorted(levels)[-2]) + 1e-12 and dd > float(sorted(levels)[0]) + 1e-12:
            label = f"回撤≤{sorted(levels)[-2]*100:.0f}%减1档"
            ev = "withdraw"
        else:
            label = f"回撤≤{sorted(levels)[0]*100:.0f}%减1档"
            ev = "withdraw"
        events.append(
            {
                "event": ev,
                "label": label,
                "amount": -amt,
                "dd": dd,
                "equity": state.working,
                "injected": state.injected,
                "layers": state.layers,
            }
        )
        dd = drawdown(state.working, state.peak)
        if not state.stack:
            state.max_reached = 0
            if dd <= 1e-12:
                state.peak = state.working

    return events


def simulate_dd_topup(
    equity: pd.Series,
    *,
    initial_cash: float = 100_000.0,
    add_pct: float | None = None,
    levels: Sequence[float] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """对策略日权益序列做阶梯补仓仿真。

    equity: 策略账户权益（与 initial_cash 同量纲），index 为交易日。
    返回 (日净值表, 事件列表)。
    """
    pct, lv = resolve_topup_params(add_pct=add_pct, levels=levels)
    eq = equity.copy().sort_index()
    if eq.empty:
        return pd.DataFrame(), []
    if getattr(eq.index, "tz", None) is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")

    rets = eq.pct_change()
    rets.iloc[0] = float(eq.iloc[0]) / float(initial_cash) - 1.0

    state = DdTopupState(working=float(initial_cash), peak=float(initial_cash))
    rows: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []

    for dt, ret in rets.items():
        y = int(pd.Timestamp(dt).year)
        day_events = step_dd_topup(
            state,
            ret=float(ret),
            date_year=y,
            add_pct=pct,
            levels=lv,
        )
        for e in day_events:
            all_events.append({"date": pd.Timestamp(dt).strftime("%Y-%m-%d"), **e})
        rows.append(
            {
                "date": dt,
                "base_equity": float(eq.loc[dt]),
                "equity": state.working,
                "injected": state.injected,
                "own_equity": state.working - state.injected,
                "peak": state.peak,
                "dd": drawdown(state.working, state.peak),
                "layers": state.layers,
            }
        )

    nav = pd.DataFrame(rows).set_index("date")
    return nav, all_events


def summarize_overlay(
    nav: pd.DataFrame,
    *,
    initial_cash: float,
    base_final: float | None = None,
) -> dict[str, float]:
    if nav.empty:
        return {}
    final = float(nav["equity"].iloc[-1])
    end_inj = float(nav["injected"].iloc[-1])
    own = final - end_inj
    hw = nav["equity"].cummax()
    max_dd = float(((1.0 - nav["equity"] / hw) * 100.0).max())
    out = {
        "final_equity": final,
        "end_injected": end_inj,
        "own_equity": own,
        "own_return_pct": (own / initial_cash - 1.0) * 100.0,
        "max_drawdown_pct": max_dd,
    }
    if base_final is not None:
        out["base_final"] = float(base_final)
        out["base_return_pct"] = (float(base_final) / initial_cash - 1.0) * 100.0
        out["extra_vs_base"] = own - float(base_final)
    return out
