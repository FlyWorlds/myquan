"""回撤阶梯补仓（因子2 真源）：在策略权益曲线上追加/提出资金。

默认五档（相对年内权益高点，每 5% 一档；前浅后深）：
  · 回撤 ≥10%/15%/20%/25%/30% → 追加总本金 × 5%/10%/15%/15%/15%
  · 累计追加上限 = 总本金 × 60%；回撤超过 30% 不再加档
  · 回撤收窄按档 LIFO 提出；回到 0 全部结清

「总本金」= 回测 initial_cash（盯盘用登记的资金基数）。
数据口径与策略一相同：前复权日线回测权益，本模块不改复权方式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

# --- 默认参数（开闭：改默认只动此处；策略侧用 bindings / BacktestConfig 覆盖）---
DEFAULT_LEVELS: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.30)
# 各档相对「总本金」追加比例（前浅后深：浅回撤少加，深回撤多加）
DEFAULT_ADD_PCTS: tuple[float, ...] = (0.05, 0.10, 0.15, 0.15, 0.15)
# 兼容旧接口：均匀每档比例；None 表示用 DEFAULT_ADD_PCTS
DEFAULT_ADD_PCT = 0.10
# 累计追加上限（相对总本金）；None=各档之和
DEFAULT_MAX_INJECT_PCT = 0.60


def normalize_levels(levels: Sequence[float] | None = None) -> tuple[float, ...]:
    raw = tuple(float(x) for x in (levels if levels is not None else DEFAULT_LEVELS))
    if not raw:
        return DEFAULT_LEVELS
    return tuple(sorted(raw))


def normalize_add_pcts(
    *,
    add_pct: float | None = None,
    add_pcts: Sequence[float] | None = None,
    levels: Sequence[float] | None = None,
) -> tuple[float, ...]:
    lv = normalize_levels(levels)
    if add_pcts is not None:
        pcts = tuple(float(x) for x in add_pcts)
        if len(pcts) == 1:
            pcts = pcts * len(lv)
        if len(pcts) != len(lv):
            raise ValueError(
                f"add_pcts 长度须与 levels 一致: {len(pcts)} vs {len(lv)}"
            )
        if any(p <= 0 for p in pcts):
            raise ValueError(f"add_pcts 各项须 >0: {pcts}")
        return pcts
    if add_pct is not None:
        pct = float(add_pct)
        if pct <= 0 or pct >= 1:
            raise ValueError(f"add_pct 应在 (0,1): {pct}")
        return tuple(pct for _ in lv)
    # 默认五档表；若 levels 被覆盖且长度不同，则均匀 DEFAULT_ADD_PCT
    if len(lv) == len(DEFAULT_ADD_PCTS) and lv == normalize_levels(DEFAULT_LEVELS):
        return DEFAULT_ADD_PCTS
    if len(lv) == len(DEFAULT_ADD_PCTS):
        return DEFAULT_ADD_PCTS
    return tuple(float(DEFAULT_ADD_PCT) for _ in lv)


def resolve_topup_params(
    *,
    add_pct: float | None = None,
    add_pcts: Sequence[float] | None = None,
    levels: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...], float]:
    """解析补仓参数 → (add_pcts, levels, max_inject_pct)。"""
    lv = normalize_levels(levels)
    pcts = normalize_add_pcts(add_pct=add_pct, add_pcts=add_pcts, levels=lv)
    if max_inject_pct is None:
        cap = float(DEFAULT_MAX_INJECT_PCT)
    else:
        cap = float(max_inject_pct)
    if cap <= 0:
        raise ValueError(f"max_inject_pct 须 >0: {cap}")
    return pcts, lv, cap


def levels_label(levels: Sequence[float] = DEFAULT_LEVELS) -> str:
    return "/".join(f"{float(x)*100:.0f}" for x in normalize_levels(levels))


def add_pcts_label(add_pcts: Sequence[float] = DEFAULT_ADD_PCTS) -> str:
    return "/".join(f"{float(x)*100:.0f}" for x in add_pcts)


def filter_desc(
    add_pct: float | None = None,
    levels: Sequence[float] = DEFAULT_LEVELS,
    *,
    add_pcts: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
) -> str:
    pcts, lv, cap = resolve_topup_params(
        add_pct=add_pct, add_pcts=add_pcts, levels=levels, max_inject_pct=max_inject_pct
    )
    return (
        f"叠在策略权益上：回撤{levels_label(lv)}各+总本金×"
        f"{add_pcts_label(pcts)}%；累计上限{cap*100:.0f}%；回落减档，到0结清"
    )


def format_rules(
    add_pct: float | None = None,
    levels: Sequence[float] = DEFAULT_LEVELS,
    *,
    add_pcts: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
) -> str:
    """按当前参数生成规则文案（避免百分比写死在多处）。"""
    pcts, lv, cap = resolve_topup_params(
        add_pct=add_pct, add_pcts=add_pcts, levels=levels, max_inject_pct=max_inject_pct
    )
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
    cum = 0.0
    for i, (level, pct) in enumerate(zip(lv, pcts), 1):
        cum += pct
        lines.append(
            f"  · 回撤 ≥{level*100:.0f}% → 追加总本金 ×{pct*100:.0f}%"
            f"（第{i}档，累计约{min(cum, cap)*100:.0f}%）"
        )
    lines.append(f"  · 累计追加上限 = 总本金 ×{cap*100:.0f}%；更深回撤不再加档")
    if len(lv) >= 2:
        lines.append("  · 回撤收窄 → 按当前回撤对应档位 LIFO 减档")
    lines.extend(
        [
            "  · 回撤到 0 → 剩余全部结清",
            "",
            "【说明】",
            "  · 「总本金」= 回测 initial_cash；追加后资金继续随策略权益波动",
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
    """回落目标档数：与当前回撤深度对齐（不超过已达档）；到 0 清零。"""
    if reached <= 0:
        return 0
    if dd <= 1e-12:
        return 0
    return min(int(reached), add_target(dd, levels))


@dataclass
class DdTopupState:
    working: float
    peak: float
    stack: list[float] = field(default_factory=list)
    max_reached: int = 0
    year: int | None = None
    # 总本金：各档追加金额的基数
    capital_base: float = 0.0

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
    add_pct: float | None = None,
    add_pcts: Sequence[float] | None = None,
    levels: Sequence[float] = DEFAULT_LEVELS,
    max_inject_pct: float | None = None,
    capital_base: float | None = None,
) -> list[dict[str, Any]]:
    """推进一日：先乘收益，再按档追加/提出。返回当日事件列表。"""
    pcts, lv, cap = resolve_topup_params(
        add_pct=add_pct,
        add_pcts=add_pcts,
        levels=levels,
        max_inject_pct=max_inject_pct,
    )
    base = float(
        capital_base
        if capital_base is not None and capital_base > 0
        else (state.capital_base if state.capital_base > 0 else state.working)
    )
    state.capital_base = base
    max_inject = cap * base

    events: list[dict[str, Any]] = []
    if state.year is None or date_year != state.year:
        state.year = date_year
        state.peak = state.working
        state.max_reached = max(state.max_reached, len(state.stack))

    state.working *= 1.0 + float(ret)
    if state.working > state.peak + 1e-9:
        state.peak = state.working

    # 用「追加前」回撤决定加减档，避免大额注资瞬间把 DD 打到 0 误触发结清
    dd_signal = drawdown(state.working, state.peak)
    at = add_target(dd_signal, lv)
    if at > state.max_reached:
        state.max_reached = at

    while len(state.stack) < at:
        idx = len(state.stack)
        room = max_inject - state.injected
        if room <= 1e-6:
            break
        raw = float(pcts[idx]) * base
        amt = min(raw, room)
        if amt <= 1e-6:
            break
        state.working += amt
        state.stack.append(amt)
        # 注资抬升权益时同步抬高点，避免出现负回撤口径
        if state.working > state.peak + 1e-9:
            state.peak = state.working
        level = lv[idx] if idx < len(lv) else lv[-1]
        events.append(
            {
                "event": "inject",
                "label": (
                    f"回撤≥{float(level)*100:.0f}%追加总本金×{float(pcts[idx])*100:.0f}%"
                ),
                "amount": amt,
                "dd": dd_signal,
                "equity": state.working,
                "injected": state.injected,
                "layers": state.layers,
            }
        )

    want = desired_layers(dd_signal, state.max_reached, lv)
    while len(state.stack) > want:
        if want == 0 and len(state.stack) > 1 and dd_signal <= 1e-12:
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
        if dd_signal <= 1e-12:
            label = "回撤归0结清一档"
            ev = "withdraw_all" if not state.stack else "withdraw"
        else:
            label = f"回撤收窄至{dd_signal*100:.1f}%减档→{len(state.stack)}"
            ev = "withdraw"
        events.append(
            {
                "event": ev,
                "label": label,
                "amount": -amt,
                "dd": dd_signal,
                "equity": state.working,
                "injected": state.injected,
                "layers": state.layers,
            }
        )
        if not state.stack:
            state.max_reached = 0
            if dd_signal <= 1e-12:
                state.peak = state.working

    return events


def simulate_dd_topup(
    equity: pd.Series,
    *,
    initial_cash: float = 100_000.0,
    add_pct: float | None = None,
    add_pcts: Sequence[float] | None = None,
    levels: Sequence[float] | None = None,
    max_inject_pct: float | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """对策略日权益序列做阶梯补仓仿真。

    equity: 策略账户权益（与 initial_cash 同量纲），index 为交易日。
    返回 (日净值表, 事件列表)。
    """
    pcts, lv, cap = resolve_topup_params(
        add_pct=add_pct,
        add_pcts=add_pcts,
        levels=levels,
        max_inject_pct=max_inject_pct,
    )
    eq = equity.copy().sort_index()
    if eq.empty:
        return pd.DataFrame(), []
    if getattr(eq.index, "tz", None) is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")

    rets = eq.pct_change()
    rets.iloc[0] = float(eq.iloc[0]) / float(initial_cash) - 1.0

    state = DdTopupState(
        working=float(initial_cash),
        peak=float(initial_cash),
        capital_base=float(initial_cash),
    )
    rows: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []

    for dt, ret in rets.items():
        y = int(pd.Timestamp(dt).year)
        day_events = step_dd_topup(
            state,
            ret=float(ret),
            date_year=y,
            add_pcts=pcts,
            levels=lv,
            max_inject_pct=cap,
            capital_base=float(initial_cash),
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
