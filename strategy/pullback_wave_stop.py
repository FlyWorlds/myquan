"""因子26 · 多层止盈：买=开盘阈值突破；卖按浮盈分三段。

买入：当日最高 ≥ ceil(open×(1+entry_pct))（过滤同因子1）。
攻击波（研究对照 `--buy-mode open_or_attack`）：先用此前分钟最低算买点，再更新本分钟最低。
卖出（止盈/保护）：
  · 盈利 >10%：分段止盈（10% 半仓 / 15% 全清；过 10% 后峰值回落 2% 清）
  · 盈利 3%～10%：回落一半 与 动态高点回落「0.5×近20日日频σ」并行，谁先碰到走谁
  · 买入日收盘盈利 <3%：次日按当日动态峰值回落 2.5% 立即止损；
    盘中浮盈到 3% 改走中段，到 10% 改走分段
  · 任何时候亏到 2.5%：成本硬保护
触达判定：按 **1 分钟 K 时间顺序**——先用此前最高算卖价，再抬升 peak。
默认 entry ±2.5%。

日线回放用全日 high/low（同 bar 有次序偏差）。
盯盘触达：必须按 1 分钟顺序；禁止用「全日最低 vs 抬高后卖价」。
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from strategy.akq_math import log_return_sample_std, simple_return
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    NEAR_FACTOR_PCT,
    TICK_SIZE,
    bar_shape,
    ceil_to_tick,
    entry_filters_ok,
    entry_trigger_price,
    floor_to_tick,
    is_t1_buy_day,
    limit_up_price,
    prev_day_allows_entry,
    should_block_entry_by_yang,
)

DEFAULT_ENTRY_PCT = DEFAULT_PCT
DEFAULT_PULLBACK_PCT = DEFAULT_PCT  # 未浮盈时的成本硬保护
DEFAULT_GIVEBACK_RATIO = 0.5  # 兼容旧公式（中段已改波动回落）
DEFAULT_LADDER_HALF_PCT = 0.10  # 大赚：浮盈 10% 卖一半
DEFAULT_LADDER_FULL_PCT = 0.15  # 大赚：浮盈 15% 全清
DEFAULT_PEAK_PULLBACK_X = 0.02  # 大赚后：峰值回落 2% 清仓
DEFAULT_NOTED_DUMP_PCT = 0.01  # 研究对照：开盘下杀（生产已不用）
DEFAULT_T1_NOTE_PROFIT_LT_PCT = 0.03  # 买入日收盘盈利 ≥3% 不记；其余走次日峰值回落
DEFAULT_ALLOW_ATTACK = False  # 生产默认：只买开盘阈值；攻击波仅研究对照
DEFAULT_GIVEBACK_ARM_PCT = 0.03  # 浮盈 >3% 才启用波动回落止盈
DEFAULT_T1_PEAK_TRAIL_PCT = 0.025  # 未到 3%：次日动态峰值回落 2.5%
DEFAULT_VOL_GIVEBACK_RATIO = 0.5  # 中段：回落距离 = 近 20 日日频波动 × 该比例
DEFAULT_VOL20_WINDOW = 20
DEFAULT_VOL_GIVEBACK_CAP = 0.15  # 回落距离上限，避免极端波动把卖价打到 0
HARD_GAP_IMMEDIATE = "immediate"  # 低开已破硬保护 → 开盘价立刻卖（生产）
HARD_GAP_OPEN_DUMP = "open_dump"  # 低开已破硬保护 → 再等开盘下杀 dump% 才卖（研究）
HARD_GAP_MODES = (HARD_GAP_IMMEDIATE, HARD_GAP_OPEN_DUMP)
DEFAULT_HARD_GAP_DUMP_PCT = 0.01  # open_dump：从开盘再下杀 1%

STRATEGY_RULES = """
================================================================================
  因子26 · 多层止盈（买=开盘阈值）
================================================================================

【空仓 · 买入】开盘阈值（过滤同因子1：前日阴/小阳；禁双阳；T+1）
  当日最高 >= ceil(开盘 × (1+阈值))，按该触发价限价买
  （攻击波仅研究对照，默认关闭）

【有仓 · 卖出】同分钟优先级（与 eval_multi_tp_bar 一致；全清优先于半仓）：
  0) 低开已破买点硬保护 → 开盘立刻卖（先于 T1）
  1) 买入日收盘盈利 <3%（已记）且当日尚未 >3% → 次日动态峰值回落 2.5% 全清
  2) 阶梯：浮盈 ≥15% → 可卖全清
  3) 中赚（浮盈 >3% 且 <10%）：回落一半 与 峰值回落 0.5×20日日频σ 并行，
     从动态高点往下谁先碰到走谁（同分钟价高者先触）
  4) 硬保护：盘中亏损达 2.5%（未进中赚/大赚档时）
  5) 大赚：阶梯 10% 半仓；≥10% 后峰值回落 2% 清仓
     （已半仓后再触 10% / 回落 → 剩余全清）
  · 未触达时的「工作卖价」走 working_stop_price：过 10% 展示峰值回落 2%，
    禁止用 dummy OHLC 去撞 10%/15% 阶梯目标（否则盯盘会把阶梯价当止损）
  · 买入当日不可卖；次日未过 3% 走峰值回落 2.5%；过 3% 走中段（一半/波动先到先卖）；过 10% 走分段
  · 峰值只从买入之后算，未卖出前创新高则抬升；T1 回落峰值=max(隔夜持仓高点, 当日高点)，不得低于买点硬保护；低开已破硬保护按开盘卖
  · 半仓不足 200 股则改为全清

【默认】entry 2.5%；中段门槛 3%；阶梯 10%/15%；大赚回落 2%；回落一半 50%；波动回落 50%×20日日频σ；
       T1 峰值回落 2.5%；硬保护 2.5%。
【说明】选股/过滤用日线；成交触达用 1 分钟 path-dependent（定盘池短窗约 7 日）。
================================================================================
"""


def pullback_stop_price(
    day_high: float,
    *,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """兼容旧名：峰值×(1−pct)。因子26 默认已改用 half_gain_stop_price。"""
    h = float(day_high)
    if h <= 0:
        return 0.0
    return floor_to_tick(h * (1.0 - float(pullback_pct)), tick)


def cost_hard_stop_px(
    cost_px: float,
    *,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """买点硬保护：floor(成本×(1−2.5%))。"""
    c = float(cost_px or 0)
    if c <= 0:
        return 0.0
    return floor_to_tick(c * (1.0 - float(hard_pct)), tick)


def t1_trail_stop_px(
    session_peak: float,
    *,
    cost_px: float,
    t1_trail_pct: float = DEFAULT_T1_PEAK_TRAIL_PCT,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """隔夜未到 3%：峰值回落 2.5%，且不得低于买点硬保护。"""
    trail = pullback_stop_price(session_peak, pullback_pct=t1_trail_pct, tick=tick)
    hard = cost_hard_stop_px(cost_px, hard_pct=hard_pct, tick=tick)
    if trail <= 0:
        return hard
    if hard <= 0:
        return trail
    return max(trail, hard)


def overnight_open_protect_px(
    cost_px: float,
    prev_close: float | None,
    *,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    giveback_arm_pct: float = DEFAULT_GIVEBACK_ARM_PCT,
    t1_trail_pct: float = DEFAULT_T1_PEAK_TRAIL_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """开盘时刻保护价（策略统一）：硬保护 / T1 昨高回落 / 隔夜中段回落一半。

    不含盘中抬高后的展示止损，避免用收盘后卖价去撞今开。
    """
    cost = float(cost_px or 0)
    if cost <= 0:
        return 0.0
    hard = cost_hard_stop_px(cost, hard_pct=hard_pct, tick=tick)
    prev = float(prev_close or 0)
    peak = max(x for x in (cost, prev) if x > 0)
    if prev > 0 and pnl_exceeds(prev, cost, giveback_arm_pct):
        half = half_gain_stop_price(peak, cost, hard_pct=hard_pct, tick=tick)
        return max(x for x in (hard, half) if x and x > 0)
    trail = t1_trail_stop_px(
        peak, cost_px=cost, t1_trail_pct=t1_trail_pct, hard_pct=hard_pct, tick=tick
    )
    return max(x for x in (hard, trail) if x and x > 0)


def pnl_exceeds(px: float, cost_px: float, thresh: float) -> bool:
    """现价相对成本是否严格超过 thresh（默认用来判断浮盈 >3%）。"""
    r = simple_return(px, cost_px)
    if r is None:
        return False
    return r > float(thresh) + 1e-12


def realized_vol_daily(
    closes: Any,
    *,
    window: int = DEFAULT_VOL20_WINDOW,
) -> float | None:
    """近 window 根日对数收益样本标准差（日频，不年化）。akquant ``vec_log_returns`` + ``vec_rolling_std``。"""
    return log_return_sample_std(closes, window=window)


def vol_giveback_distance(
    vol20_daily: float | None,
    *,
    ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    cap: float = DEFAULT_VOL_GIVEBACK_CAP,
) -> float:
    """中段回落距离：ratio × 近20日日频波动，截到 [0, cap]。"""
    try:
        v = float(vol20_daily or 0)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    dist = float(ratio) * v
    return min(max(dist, 0.0), float(cap))


def vol_giveback_stop_price(
    peak_high: float,
    vol20_daily: float | None,
    *,
    ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
) -> float:
    """动态高点回落「日频波动 × ratio」的卖价。"""
    peak = float(peak_high or 0)
    dist = vol_giveback_distance(vol20_daily, ratio=ratio)
    if peak <= 0 or dist <= 0:
        return 0.0
    return floor_to_tick(peak * (1.0 - dist), tick)


def mid_gain_tp_candidates(
    peak_high: float,
    cost_px: float,
    vol20_daily: float | None,
    *,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    vol_giveback_ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
) -> list[tuple[str, float]]:
    """中赚两条止盈线：(reason, 卖价)。价高者从峰值回落时先碰到。"""
    cost = float(cost_px or 0)
    peak = float(peak_high or 0)
    out: list[tuple[str, float]] = []
    if cost > 0 and peak > cost + 1e-12:
        half_px = half_gain_stop_price(
            peak,
            cost,
            giveback_ratio=giveback_ratio,
            tick=tick,
        )
        if half_px > 0:
            out.append(("half_gain", float(half_px)))
    vol_px = vol_giveback_stop_price(
        peak, vol20_daily, ratio=vol_giveback_ratio, tick=tick
    )
    if vol_px > 0:
        out.append(("vol_giveback", float(vol_px)))
    return out


def mid_gain_first_stop(
    peak_high: float,
    cost_px: float,
    vol20_daily: float | None,
    *,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    vol_giveback_ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
) -> tuple[str, float]:
    """尚未触达时的工作止盈价：两条线里更高的那条（会先触发）。"""
    cands = mid_gain_tp_candidates(
        peak_high,
        cost_px,
        vol20_daily,
        giveback_ratio=giveback_ratio,
        vol_giveback_ratio=vol_giveback_ratio,
        tick=tick,
    )
    if not cands:
        return "", 0.0
    reason, px = max(cands, key=lambda x: x[1])
    return reason, float(px)


def working_stop_price(
    *,
    cost_px: float,
    peak_high: float,
    session_peak: float = 0.0,
    day_open: float = 0.0,
    overnight_armed: bool = False,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    giveback_arm_pct: float = DEFAULT_GIVEBACK_ARM_PCT,
    t1_trail_pct: float = DEFAULT_T1_PEAK_TRAIL_PCT,
    vol20_daily: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    vol_giveback_ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
) -> tuple[str, float]:
    """未触达时的工作卖价。

    过 10% 后工作线是峰值回落 2%，不是 10%/15% 阶梯目标。
    禁止用「open=high=low=peak」去跑 eval_multi_tp_bar：那会假触发阶梯，
    把目标价写进盯盘 stop，现价回落到目标价就会误报「已触止损」。
    """
    cost = float(cost_px or 0)
    peak = max(float(peak_high or 0), cost) if cost > 0 else float(peak_high or 0)
    if cost <= 0 or peak <= 0:
        return "", 0.0
    live_ok = pnl_exceeds(peak, cost, giveback_arm_pct)
    peak_gain = peak / cost - 1.0
    hard = cost_hard_stop_px(cost, hard_pct=hard_pct, tick=tick)
    if overnight_armed and (not live_ok):
        sess = max(float(session_peak or 0), float(day_open or 0), peak)
        return "t1_peak_trail", t1_trail_stop_px(
            sess,
            cost_px=cost,
            t1_trail_pct=t1_trail_pct,
            hard_pct=hard_pct,
            tick=tick,
        )
    if live_ok and peak_gain < DEFAULT_LADDER_HALF_PCT - 1e-12:
        kind, px = mid_gain_first_stop(
            peak,
            cost,
            vol20_daily,
            giveback_ratio=giveback_ratio,
            vol_giveback_ratio=vol_giveback_ratio,
            tick=tick,
        )
        if px > 0:
            return (kind or "half_gain"), float(px)
        return "hard_from_cost", hard
    if live_ok and peak_gain + 1e-12 >= DEFAULT_LADDER_HALF_PCT:
        return "peak_pullback", peak_pullback_half_price(peak, tick=tick)
    return "hard_from_cost", hard


def mid_gain_first_hit(
    bar_low: float,
    peak_high: float,
    cost_px: float,
    vol20_daily: float | None,
    *,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    vol_giveback_ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
) -> tuple[str, float] | None:
    """本 bar 最低价碰到的止盈里，从峰值往下先碰到的那条（卖价更高者）。"""
    lo = float(bar_low or 0)
    if lo <= 0:
        return None
    hit = [
        (reason, px)
        for reason, px in mid_gain_tp_candidates(
            peak_high,
            cost_px,
            vol20_daily,
            giveback_ratio=giveback_ratio,
            vol_giveback_ratio=vol_giveback_ratio,
            tick=tick,
        )
        if px > 0 and lo <= px + 1e-12
    ]
    if not hit:
        return None
    reason, px = max(hit, key=lambda x: x[1])
    return reason, float(px)


def half_gain_stop_price(
    peak_high: float,
    cost_px: float,
    *,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """浮盈回落一半卖价；未浮盈时用成本硬保护。

    giveback_ratio=0.5 → 卖价 = 成本 + 0.5×(买入后最高−成本)。
    峰值从买入价之后起算，未卖出前创新高则抬升。
    """
    cost = float(cost_px)
    peak = float(peak_high)
    if cost <= 0:
        return 0.0
    if peak <= cost + 1e-12:
        return floor_to_tick(cost * (1.0 - float(hard_pct)), tick)
    gb = min(max(float(giveback_ratio), 0.0), 1.0)
    return floor_to_tick(cost + (1.0 - gb) * (peak - cost), tick)


def resolve_t1_overnight_note(
    *,
    cost_px: float,
    peak_high: float,
    close_px: float,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    note_profit_lt: float = DEFAULT_T1_NOTE_PROFIT_LT_PCT,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
    bar_low: float | None = None,
) -> dict[str, Any]:
    """买入当日日末：是否把已记带到次日。

    · 收盘盈利 ≥ 3%：不记（次日走中段一半/波动赛跑 / 分段）
    · 收盘盈利 < 3%（含小亏）：记 T1 峰值回落，次日按当日动态峰值回落 2.5%
    · 收盘/最低亏损 ≥ hard_pct（默认 2.5%）：记硬保护
    """
    cost = float(cost_px or 0)
    close = float(close_px or 0)
    empty = {"noted_px": None, "reason": ""}
    if cost <= 0 or close <= 0:
        return empty
    lo = float(bar_low) if bar_low is not None and float(bar_low) > 0 else close
    hard_px = floor_to_tick(cost * (1.0 - float(hard_pct)), tick)
    if lo <= hard_px + 1e-12 or close <= hard_px + 1e-12:
        return {"noted_px": float(hard_px), "reason": "hard_from_cost"}
    pnl = close / cost - 1.0
    if pnl >= float(note_profit_lt) - 1e-12:
        return {"noted_px": None, "reason": "profit_ge_3pct"}
    # 哨兵价=成本：只作「已记」开关，次日不按该价成交，改走峰值回落 2.5%
    arm_px = floor_to_tick(cost, tick)
    return {
        "noted_px": float(arm_px) if arm_px > 0 else float(cost),
        "reason": "t1_trail",
    }


def stop_note_invalidated_by_recovery(
    *,
    last_px: float,
    noted_px: float | None,
    prev_close: float | None = None,
    recover_mult: float = 1.005,
    limit_up_pct: float = 0.10,
    tick: float = TICK_SIZE,
) -> bool:
    """T+1 已记后若现价已远离卖价（含收盘涨停），作废已记。

    盯盘注释「现价已明显高于止损则不当止损」应对落库已记同样生效。
    """
    last = float(last_px or 0)
    if last <= 0:
        return False
    noted = float(noted_px or 0)
    if noted > 0 and last > noted * float(recover_mult) + 1e-12:
        return True
    pc = float(prev_close or 0)
    if pc > 0:
        lim = limit_up_price(pc, limit_up_pct=float(limit_up_pct), tick=tick)
        if lim is not None and last + 1e-12 >= float(lim):
            return True
    return False


def exit_stop_price(
    peak_high: float,
    *,
    cost_px: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """因子26 卖价入口：有成本走浮盈回落一半，否则退回峰值硬比例（兼容）。"""
    peak = float(peak_high)
    if peak <= 0:
        return 0.0
    if cost_px is not None and float(cost_px) > 0:
        return half_gain_stop_price(
            peak,
            float(cost_px),
            giveback_ratio=giveback_ratio,
            hard_pct=hard_pct,
            tick=tick,
        )
    return pullback_stop_price(peak, pullback_pct=hard_pct, tick=tick)


def lot_half_shares(shares: int) -> int:
    """半仓股数：向下取整到 100；不足 200 股则全额（无法半仓）。"""
    sh = max(0, int(shares))
    if sh < 200:
        return sh
    return (sh // 2 // 100) * 100


def ladder_target_price(
    cost_px: float,
    *,
    gain_pct: float,
    tick: float = TICK_SIZE,
) -> float:
    """阶梯止盈目标价：成本 × (1+gain_pct)。"""
    c = float(cost_px)
    if c <= 0:
        return 0.0
    return floor_to_tick(c * (1.0 + float(gain_pct)), tick)


def peak_pullback_half_price(
    peak_high: float,
    *,
    pullback_x: float = DEFAULT_PEAK_PULLBACK_X,
    tick: float = TICK_SIZE,
) -> float:
    """大赚后：峰值回落 X 的清仓线。"""
    return pullback_stop_price(peak_high, pullback_pct=pullback_x, tick=tick)


def overnight_open_dump_fill(
    *,
    day_open: float,
    bar_low: float,
    dump_pct: float = DEFAULT_NOTED_DUMP_PCT,
    tick: float = TICK_SIZE,
) -> dict[str, Any]:
    """规则4：基于开盘价下杀 dump_pct 全清（不依赖已记价）。"""
    out = {"hit": False, "fill_px": 0.0, "reason": ""}
    o = float(day_open or 0)
    lo = float(bar_low or 0)
    if o <= 0 or lo <= 0:
        return out
    dump_stop = open_dump_stop_price(o, dump_pct=dump_pct, tick=tick)
    if dump_stop > 0 and lo <= dump_stop + 1e-12:
        fill = o if o <= dump_stop + 1e-12 else dump_stop
        return {"hit": True, "fill_px": float(fill), "reason": "overnight_open_dump"}
    return out


def eval_multi_tp_bar(
    *,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    cost_px: float,
    peak_before: float,
    shares: int,
    tp_stage: int = 0,
    can_sell: bool = True,
    overnight_armed: bool = False,
    day_open: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    ladder_half_pct: float = DEFAULT_LADDER_HALF_PCT,
    ladder_full_pct: float = DEFAULT_LADDER_FULL_PCT,
    peak_pullback_x: float = DEFAULT_PEAK_PULLBACK_X,
    dump_pct: float = DEFAULT_NOTED_DUMP_PCT,
    giveback_arm_pct: float = DEFAULT_GIVEBACK_ARM_PCT,
    t1_trail_pct: float = DEFAULT_T1_PEAK_TRAIL_PCT,
    vol20_daily: float | None = None,
    vol_giveback_ratio: float = DEFAULT_VOL_GIVEBACK_RATIO,
    session_peak_before: float = 0.0,
    hard_gap_mode: str = HARD_GAP_IMMEDIATE,
    hard_gap_dump_pct: float = DEFAULT_HARD_GAP_DUMP_PCT,
    tick: float = TICK_SIZE,
) -> dict[str, Any]:
    """单根 1m：多层止盈判定。

    hard_gap_mode：
      · immediate：开盘已 ≤ 硬保护价 → 按开盘价立刻 hard_from_cost（生产）
      · open_dump：开盘已破硬保护 → 再等开盘下杀 hard_gap_dump_pct 才卖（研究对照）

    返回：
      action: None | {kind: full|half, reason, fill_px, shares}
      tp_marked: 当日应触止盈但因 T+1 未卖
      noted_px: 建议记入的止损/止盈价（T+1）
      peak_after: 本 bar 结束后持仓峰值
      session_peak_after: 本 bar 结束后的当日峰值
    """
    cost = float(cost_px)
    h = float(bar_high)
    lo = float(bar_low)
    bar_o = float(bar_open or 0)
    day_o = float(day_open) if day_open is not None and float(day_open) > 0 else bar_o
    peak = max(float(peak_before or 0), cost) if cost > 0 else float(peak_before or 0)
    sess = float(session_peak_before or 0)
    if sess <= 0 and day_o > 0:
        sess = day_o
    stage = max(0, int(tp_stage))
    sh = max(0, int(shares))
    sess_after = max(sess, h) if h > 0 else sess
    empty = {
        "action": None,
        "tp_marked": False,
        "noted_px": None,
        "peak_after": max(peak, h) if h > 0 else peak,
        "session_peak_after": sess_after,
    }
    if cost <= 0 or sh <= 0 or h <= 0 or lo <= 0:
        return empty

    def _full(reason: str, px: float, *, downside: bool = True) -> dict[str, Any]:
        fill = float(px)
        if downside and bar_o > 0 and bar_o <= fill + 1e-12:
            fill = float(bar_o)
        return {
            "action": {
                "kind": "full",
                "reason": reason,
                "fill_px": fill,
                "shares": sh,
            },
            "tp_marked": True,
            "noted_px": float(px),
            "peak_after": max(peak, h),
            "session_peak_after": sess_after,
        }

    def _half(reason: str, px: float, *, downside: bool = True) -> dict[str, Any]:
        sell_n = lot_half_shares(sh)
        if sell_n >= sh:
            return _full(reason, px, downside=downside)
        fill = float(px)
        if downside and bar_o > 0 and bar_o <= fill + 1e-12:
            fill = float(bar_o)
        return {
            "action": {
                "kind": "half",
                "reason": reason,
                "fill_px": fill,
                "shares": sell_n,
            },
            "tp_marked": True,
            "noted_px": float(px),
            "peak_after": max(peak, h),
            "session_peak_after": sess_after,
        }

    def _mark(px: float) -> dict[str, Any]:
        return {
            "action": None,
            "tp_marked": True,
            "noted_px": float(px),
            "peak_after": max(peak, h),
            "session_peak_after": sess_after,
        }

    live_hi = max(h, day_o, bar_o)
    live_ok = pnl_exceeds(live_hi, cost, giveback_arm_pct)
    peak_incl = max(peak, h)
    peak_gain = (peak_incl / cost - 1.0) if cost > 0 and peak_incl > 0 else 0.0
    hard_px = cost_hard_stop_px(cost, hard_pct=hard_pct, tick=tick)
    gap_mode = str(hard_gap_mode or HARD_GAP_IMMEDIATE).strip().lower()
    if gap_mode not in HARD_GAP_MODES:
        gap_mode = HARD_GAP_IMMEDIATE
    open_broke_hard = hard_px > 0 and day_o > 0 and day_o <= hard_px + 1e-12

    # 0) 买点硬保护：低开已破 → 生产按开盘立刻卖（先于 T1 峰值回落）
    if open_broke_hard and gap_mode == HARD_GAP_OPEN_DUMP and can_sell:
        dump = overnight_open_dump_fill(
            day_open=day_o,
            bar_low=lo,
            dump_pct=float(hard_gap_dump_pct),
            tick=tick,
        )
        if dump.get("hit") and float(dump.get("fill_px") or 0) > 0:
            return _full(
                "hard_open_dump",
                float(dump["fill_px"]),
                downside=True,
            )
    elif open_broke_hard:
        if can_sell:
            return _full("hard_from_cost", hard_px, downside=True)
        return _mark(hard_px)

    # 1) 未到 3%：次日按隔夜高点/当日高点回落 2.5%（不得低于买点硬保护）
    if overnight_armed and (not live_ok):
        sess_ref = max(sess, day_o, peak, bar_o)
        trail_px = t1_trail_stop_px(
            sess_ref,
            cost_px=cost,
            t1_trail_pct=t1_trail_pct,
            hard_pct=hard_pct,
            tick=tick,
        )
        if trail_px > 0 and lo <= trail_px + 1e-12:
            if can_sell:
                return _full("t1_peak_trail", trail_px, downside=True)
            return _mark(trail_px)

    ladder15 = ladder_target_price(cost, gain_pct=ladder_full_pct, tick=tick)
    ladder10 = ladder_target_price(cost, gain_pct=ladder_half_pct, tick=tick)

    # 2) 阶梯 15% 全清（上破）
    if ladder15 > 0 and h + 1e-12 >= ladder15:
        if can_sell:
            return _full("ladder_full_15", ladder15, downside=False)
        return {**empty, "peak_after": max(peak, h)}

    # 3) 中赚 3%～10%：回落一半 vs 波动回落，价高者先触
    mid_gain = (
        live_ok
        and peak_gain > float(giveback_arm_pct) + 1e-12
        and peak_gain < float(ladder_half_pct) - 1e-12
    )
    mid_hit = (
        mid_gain_first_hit(
            lo,
            peak,
            cost,
            vol20_daily,
            giveback_ratio=giveback_ratio,
            vol_giveback_ratio=vol_giveback_ratio,
            tick=tick,
        )
        if mid_gain
        else None
    )
    if mid_hit is not None:
        reason, px = mid_hit
        if can_sell:
            return _full(reason, px, downside=True)
        return {**empty, "peak_after": max(peak, h)}
    if hard_px > 0 and lo <= hard_px + 1e-12:
        if can_sell:
            return _full("hard_from_cost", hard_px, downside=True)
        return _mark(hard_px)

    # 4) 大赚：10% 半仓优先；≥10% 后峰值回落 X 清仓
    peak_line = peak_pullback_half_price(peak, pullback_x=peak_pullback_x, tick=tick)
    hit_ladder10 = ladder10 > 0 and h + 1e-12 >= ladder10
    hit_peak_trail = (
        live_ok
        and peak_gain + 1e-12 >= float(ladder_half_pct)
        and peak_incl > cost + 1e-12
        and peak_line > 0
        and lo <= peak_line + 1e-12
    )
    if hit_ladder10:
        if not can_sell:
            return {**empty, "peak_after": max(peak, h)}
        if stage >= 1:
            return _full("ladder_half_10_clear", ladder10, downside=False)
        return _half("ladder_half_10", ladder10, downside=False)
    if hit_peak_trail:
        if not can_sell:
            return {**empty, "peak_after": max(peak, h)}
        return _full("peak_pullback_clear", peak_line, downside=True)

    return empty


# open_dump_stop_price 定义在文件后部；overnight 调用前需已定义。
# 若静态检查顺序问题，将在 DEFAULT_NOTED 段之后不依赖前向引用——
# 实际 Python 运行时 overnight_open_dump_fill 被调用时函数已存在。
def path_dependent_pullback_hit(
    bars: pd.DataFrame | None,
    *,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
    live_high: float | None = None,
    live_low: float | None = None,
    since_ts: Any = None,
    seed_high: float | None = None,
    cost_px: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    vol20_daily: float | None = None,
    overnight_armed: bool = False,
    day_open: float | None = None,
    giveback_arm_pct: float = DEFAULT_GIVEBACK_ARM_PCT,
    t1_trail_pct: float = DEFAULT_T1_PEAK_TRAIL_PCT,
) -> dict[str, Any]:
    """按分钟 K 时间顺序判定多层止盈是否曾触达。

    每根 bar：先用此前峰值算卖价，再抬升 peak。
    since_ts：只统计该时刻之后的触达（实仓用买入时间）。
    seed_high：持仓峰值初值（成本或已记录 peak）。
    overnight_armed：买入日收盘未到 3% → 次日峰值回落 2.5%。
    """
    pb = float(pullback_pct)
    running_high = float(seed_high) if seed_high is not None and float(seed_high) > 0 else 0.0
    cost = float(cost_px) if cost_px is not None and float(cost_px) > 0 else (
        float(seed_high) if seed_high is not None and float(seed_high) > 0 else 0.0
    )
    touch_ts: Any = None
    touch_stop = 0.0
    since = None
    if since_ts is not None and str(since_ts).strip():
        try:
            since = pd.Timestamp(since_ts)
            if getattr(since, "tzinfo", None) is not None:
                since = since.tz_convert("Asia/Shanghai").tz_localize(None)
        except Exception:  # noqa: BLE001
            since = None
    day_o = float(day_open) if day_open is not None and float(day_open) > 0 else 0.0
    session_peak = running_high if (overnight_armed and running_high > 0) else 0.0

    def _iter_rows() -> list[dict[str, Any]]:
        if bars is None or getattr(bars, "empty", True):
            return []
        df = bars
        need = ("high", "low")
        if not all(c in df.columns for c in need):
            return []
        out_rows: list[dict[str, Any]] = []
        ordered = df.sort_values("ts") if "ts" in df.columns else df
        for _, row in ordered.iterrows():
            try:
                h = float(row["high"])
                lo = float(row["low"])
            except (TypeError, ValueError):
                continue
            if h <= 0 or lo <= 0:
                continue
            ts = row["ts"] if "ts" in df.columns else None
            if since is not None and ts is not None:
                try:
                    ts_p = pd.Timestamp(ts)
                    if ts_p.tzinfo is not None:
                        ts_p = ts_p.tz_convert("Asia/Shanghai").tz_localize(None)
                    if ts_p < since:
                        continue
                except Exception:  # noqa: BLE001
                    pass
            try:
                o_bar = float(row["open"]) if "open" in df.columns else 0.0
            except (TypeError, ValueError):
                o_bar = 0.0
            out_rows.append({"high": h, "low": lo, "open": o_bar, "ts": ts})
        return out_rows

    def _eval(bar_o: float, bar_h: float, bar_lo: float) -> dict[str, Any]:
        peak = max(running_high, cost) if cost > 0 else running_high
        return eval_multi_tp_bar(
            bar_open=bar_o,
            bar_high=bar_h,
            bar_low=bar_lo,
            cost_px=cost if cost > 0 else peak,
            peak_before=peak,
            shares=1000,
            can_sell=True,
            overnight_armed=bool(overnight_armed),
            day_open=day_o if day_o > 0 else (bar_o if bar_o > 0 else None),
            hard_pct=pb,
            giveback_arm_pct=giveback_arm_pct,
            t1_trail_pct=t1_trail_pct,
            vol20_daily=vol20_daily,
            session_peak_before=session_peak,
            tick=tick,
        )

    def _hit(ev: dict[str, Any], ts: Any, source: str) -> dict[str, Any] | None:
        act = ev.get("action") or {}
        fill = float(act.get("fill_px") or 0)
        if str(act.get("kind") or "") not in ("full", "half") or fill <= 0:
            return None
        peak = float(ev.get("peak_after") or running_high)
        return {
            "hit_stop": True,
            "running_high": peak,
            "stop_px": fill,
            "touch_ts": ts,
            "touch_stop": fill,
            "source": source,
            "stop_kind": str(act.get("reason") or "vol_giveback"),
            "cost_px": cost,
        }

    for row in _iter_rows():
        ev = _eval(float(row.get("open") or 0), float(row["high"]), float(row["low"]))
        hit = _hit(ev, row.get("ts"), "1m")
        running_high = float(ev.get("peak_after") or running_high)
        session_peak = float(ev.get("session_peak_after") or session_peak)
        if hit:
            return hit

    if live_low is not None and float(live_low) > 0:
        live_h = (
            float(live_high)
            if live_high is not None and float(live_high) > 0
            else (running_high if running_high > 0 else cost)
        )
        if live_h > 0:
            ev = _eval(0.0, live_h, float(live_low))
            hit = _hit(ev, touch_ts, "1m+live")
            running_high = float(ev.get("peak_after") or running_high)
            session_peak = float(ev.get("session_peak_after") or session_peak)
            if hit:
                return hit
    if live_high is not None and float(live_high) > 0:
        running_high = max(running_high, float(live_high))

    peak_now = max(running_high, cost) if cost > 0 else running_high
    stop_now = 0.0
    kind_now = ""
    if peak_now > 0 and cost > 0:
        kind_now, stop_now = working_stop_price(
            cost_px=cost,
            peak_high=peak_now,
            session_peak=session_peak,
            day_open=day_o,
            overnight_armed=bool(overnight_armed),
            hard_pct=pb,
            giveback_arm_pct=giveback_arm_pct,
            t1_trail_pct=t1_trail_pct,
            vol20_daily=vol20_daily,
            tick=tick,
        )
    return {
        "hit_stop": False,
        "running_high": peak_now,
        "stop_px": stop_now,
        "touch_ts": None,
        "touch_stop": touch_stop,
        "source": "1m" if peak_now > 0 else "empty",
        "stop_kind": kind_now or "vol_giveback",
        "cost_px": cost,
    }


def first_session_exit_fill(
    bars: pd.DataFrame | None,
    *,
    cost_px: float,
    prev_close: float | None = None,
    day_open: float | None = None,
    vol20_daily: float | None = None,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
    giveback_arm_pct: float = DEFAULT_GIVEBACK_ARM_PCT,
    t1_trail_pct: float = DEFAULT_T1_PEAK_TRAIL_PCT,
    tick: float = TICK_SIZE,
) -> float | None:
    """隔夜仓当日第一次可执行卖出成交价（1 分钟顺序）。策略统一入口，无个股特例。"""
    cost = float(cost_px or 0)
    if cost <= 0 or bars is None or getattr(bars, "empty", True):
        return None
    prev = float(prev_close or 0)
    armed = bool(prev > 0) and not pnl_exceeds(prev, cost, giveback_arm_pct)
    seed = max(x for x in (cost, prev) if x > 0)
    hit = path_dependent_pullback_hit(
        bars,
        pullback_pct=pullback_pct,
        seed_high=seed,
        cost_px=cost,
        overnight_armed=armed,
        day_open=float(day_open) if day_open else None,
        vol20_daily=vol20_daily,
        giveback_arm_pct=giveback_arm_pct,
        t1_trail_pct=t1_trail_pct,
        tick=tick,
    )
    if not bool(hit.get("hit_stop")):
        return None
    touch = float(hit.get("touch_stop") or hit.get("stop_px") or 0)
    return touch if touch > 0 else None


def attack_buy_trigger_price(
    day_low: float,
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """自当日最低点向上攻击 entry_pct 的买入触发价。"""
    lo = float(day_low)
    if lo <= 0:
        return 0.0
    return ceil_to_tick(lo * (1.0 + float(entry_pct)), tick)


def strategy_levels(
    open_px: float,
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float | None = None,
    pullback_pct: float | None = None,
    high_px: float | None = None,
    low_px: float | None = None,
    cost_px: float | None = None,
    peak_high: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    tick: float = TICK_SIZE,
    allow_attack: bool = DEFAULT_ALLOW_ATTACK,
    **_extra: Any,
) -> dict[str, float]:
    """buy：默认开盘阈值；stop=浮盈回落一半（相对成本/峰值）。

    allow_attack=False（生产默认）时 buy_trigger 只等于开盘突破价，
    避免一字开板下砸后用「低点×(1+entry)」误触空仓「将买入」。
    """
    pb = float(
        pullback_pct
        if pullback_pct is not None
        else (stop_pct if stop_pct is not None else DEFAULT_PULLBACK_PCT)
    )
    anchor = float(high_px) if high_px is not None and float(high_px) > 0 else float(open_px)
    open_buy = entry_trigger_price(open_px, entry_pct=entry_pct, tick=tick)
    lo = float(low_px) if low_px is not None and float(low_px) > 0 else float(open_px)
    attack_buy = attack_buy_trigger_price(lo, entry_pct=entry_pct, tick=tick)
    buy = open_buy
    if bool(allow_attack) and attack_buy > 0 and (buy <= 0 or attack_buy < buy):
        buy = attack_buy
    cost = float(cost_px) if cost_px is not None and float(cost_px) > 0 else float(open_px)
    peak = float(peak_high) if peak_high is not None and float(peak_high) > 0 else anchor
    peak = max(peak, cost, anchor)
    vol20 = _extra.get("vol20_daily")
    t1_armed = bool(_extra.get("overnight_armed"))
    trail = float(_extra.get("t1_trail_pct") or DEFAULT_T1_PEAK_TRAIL_PCT)
    arm = float(_extra.get("giveback_arm_pct") or DEFAULT_GIVEBACK_ARM_PCT)
    _kind, stop = working_stop_price(
        cost_px=cost,
        peak_high=peak,
        session_peak=float(_extra.get("session_peak") or 0),
        day_open=float(open_px or 0),
        overnight_armed=t1_armed,
        hard_pct=pb,
        giveback_arm_pct=arm,
        t1_trail_pct=trail,
        vol20_daily=vol20,
        giveback_ratio=giveback_ratio,
        tick=tick,
    )
    if stop <= 0:
        stop = floor_to_tick(cost * (1.0 - pb), tick) if cost > 0 else 0.0
        _kind = "hard_from_cost"
    return {
        "buy_trigger": buy,
        "buy": buy,
        "open_buy": open_buy,
        "attack_buy": attack_buy,
        "stop": stop,
        "stop_kind": _kind,
        "day_high": anchor,
        "day_low": lo,
        "pullback_pct": pb,
        "giveback_ratio": float(giveback_ratio),
        "cost_px": cost,
        "peak_high": peak,
    }


def rules_text(
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
) -> str:
    return (
        f"因子26-多层止盈\n"
        f"  · 买：开盘+{entry_pct*100:.1f}%（默认关攻击波）\n"
        f"  · 卖：>10% 分段{DEFAULT_LADDER_HALF_PCT*100:.0f}%半/"
        f"{DEFAULT_LADDER_FULL_PCT*100:.0f}%全 + 回落{DEFAULT_PEAK_PULLBACK_X*100:.0f}%；"
        f"3–10% 回落一半与0.5×20日日频σ谁先到走谁；未到3% 次日峰值回落"
        f"{DEFAULT_T1_PEAK_TRAIL_PCT*100:.1f}%\n"
        f"  · 中段门槛 {DEFAULT_GIVEBACK_ARM_PCT*100:.0f}%；硬保护 {pullback_pct*100:.1f}%；默认绑策略一"
    )


def strategy_signal(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    last_px: float,
    session: str,
    buy_trigger: float | None = None,
    stop_px: float | None = None,
    qty: int,
    buy_time: str | None,
    vs_open_pts: float,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float = DEFAULT_PULLBACK_PCT,
    pullback_pct: float | None = None,
    px_digits: int = 2,
    t0: bool = False,
    near_points: float = NEAR_FACTOR_PCT,
    allow_entry: bool = True,
    tick: float = TICK_SIZE,
    hit_stop: bool | None = None,
    hit_buy: bool | None = None,
    cost_px: float | None = None,
    peak_high: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    allow_attack: bool = DEFAULT_ALLOW_ATTACK,
    stop_kind: str | None = None,
) -> dict[str, Any]:
    """盯盘信号：默认开盘阈值买入；卖出=因子26 多层止盈工作线。

    hit_stop：若传入则尊重调用方（应用 1 分钟 path-dependent 结果）；
    否则退回 low≤stop（日线/无分钟时有次序偏差）。
    hit_buy：若传入则尊重调用方（应用 1 分钟买入路径）；否则用全日 high/low。
    stop_kind：工作卖价种类（hard_from_cost / t1_peak_trail / half_gain /
    vol_giveback / peak_pullback）；不传则按成本/峰值推断。
    """
    pb = float(pullback_pct if pullback_pct is not None else stop_pct)
    lv = strategy_levels(
        open_px,
        entry_pct=entry_pct,
        pullback_pct=pb,
        high_px=high_px,
        low_px=low_px,
        cost_px=cost_px,
        peak_high=peak_high,
        giveback_ratio=giveback_ratio,
        tick=tick,
        allow_attack=allow_attack,
    )
    open_buy = float(lv["open_buy"])
    attack_buy = float(lv["attack_buy"])
    stop_px = float(stop_px if stop_px is not None else lv["stop"])

    hit_open = high_px + 1e-12 >= open_buy
    hit_attack = bool(allow_attack) and attack_buy > 0 and (high_px + 1e-12 >= attack_buy)
    if hit_buy is None:
        hit_buy = bool(allow_entry) and (hit_open or hit_attack)
    else:
        hit_buy = bool(allow_entry) and bool(hit_buy)

    if hit_attack and (not hit_open or attack_buy <= open_buy + 1e-12):
        eff_buy = attack_buy
        buy_kind = "attack"
    elif hit_open:
        eff_buy = open_buy
        buy_kind = "open"
    elif allow_attack and buy_trigger is not None and float(buy_trigger) > 0:
        # 研究：攻击波开启时，近买可锚传入价（常为较低的 attack）
        eff_buy = float(buy_trigger)
        buy_kind = (
            "attack"
            if attack_buy > 0 and abs(float(buy_trigger) - attack_buy) <= 1e-9
            else "open"
        )
    else:
        # 生产默认：未触达时近买/展示只认开盘突破，避免下砸低点派生价误报「将买入」
        eff_buy = open_buy
        buy_kind = "open"

    buy_trigger = float(eff_buy)

    kind_now = str(stop_kind or lv.get("stop_kind") or "").strip()
    if not kind_now and cost_px is not None and float(cost_px or 0) > 0:
        kind_now, _ = working_stop_price(
            cost_px=float(cost_px),
            peak_high=float(peak_high or high_px or 0),
            day_open=float(open_px or 0),
            hard_pct=pb,
            giveback_ratio=giveback_ratio,
            tick=tick,
        )
    if not kind_now:
        kind_now = "hard_from_cost"

    def _sell_note(*, near: bool = False, holding_idle: bool = False) -> str:
        labels = {
            "hard_from_cost": "买点硬保护",
            "t1_peak_trail": "未到3%峰值回落2.5%",
            "half_gain": "中赚回落一半",
            "vol_giveback": "中赚波动回落",
            "peak_pullback": "大赚后峰值回落2%",
            "peak_pullback_clear": "大赚后峰值回落2%",
            "ladder_half_10": "阶梯10%半仓",
            "ladder_full_15": "阶梯15%全清",
        }
        label = labels.get(kind_now, "多层止盈")
        if holding_idle:
            return f"{label}@{pf.format(stop_px)}"
        if near:
            return (
                f"距{label}在{near_points:g}%内"
                f"（止{pf.format(stop_px)}）"
            )
        return f"{label}@{pf.format(stop_px)}"

    holding = qty > 0
    if hit_stop is None:
        hit_stop = low_px <= stop_px + 1e-12
    else:
        hit_stop = bool(hit_stop)
    t1_lock = holding and (not t0) and is_t1_buy_day(buy_time, session)
    buy_lvl = entry_pct * 100.0
    stop_lvl = -pb * 100.0
    pf = f"{{:.{px_digits}f}}"

    def _dist(ref_px: float) -> tuple[float | None, float | None]:
        if float(ref_px) <= 0:
            return None, None
        dpx = round(float(last_px) - float(ref_px), px_digits)
        dpct = round((float(last_px) / float(ref_px) - 1.0) * 100.0, 2)
        return dpx, dpct

    dist_buy_px, dist_buy_pct = _dist(buy_trigger)
    dist_stop_px, dist_stop_pct = _dist(stop_px)
    near_buy_band = (
        dist_buy_pct is not None and abs(float(dist_buy_pct)) <= near_points + 1e-12
    )
    near_stop_band = (
        dist_stop_pct is not None and abs(float(dist_stop_pct)) <= near_points + 1e-12
    )

    base: dict[str, Any] = {
        "near_buy": False,
        "near_stop": False,
        "pending_buy": False,
        "pending_sell": False,
        "alert": "",
        "bg_class": "",
        "建议挂单": None,
        "挂单说明": "",
        "形态": bar_shape(open_px, last_px),
        "t1_lock": t1_lock,
        "dist_buy": round(vs_open_pts - buy_lvl, 2),
        "dist_stop": round(vs_open_pts - stop_lvl, 2),
        "距买点价差": dist_buy_px,
        "距买点%": dist_buy_pct,
        "距止损价差": dist_stop_px,
        "距止损%": dist_stop_pct,
        "side": "sell" if holding else "buy",
        "因子侧": "卖出" if holding else "买入",
        "因子价": None,
        "因子触发": "不可用",
        "持仓状态": "待买入",
        "hit_buy": hit_buy,
        "hit_stop": hit_stop,
        "hit_open_buy": hit_open,
        "hit_attack_buy": hit_attack,
        "buy_kind": buy_kind,
        "open_buy": round(open_buy, px_digits),
        "attack_buy": round(attack_buy, px_digits) if attack_buy > 0 else None,
        "actionable": False,
        "near_pct": near_points,
        "stop_kind": kind_now,
        "day_high": float(high_px),
        "day_low": float(low_px),
        "pullback_pct": pb,
        "giveback_ratio": float(giveback_ratio),
    }

    def _buy_note(kind: str, px: float) -> str:
        if kind == "attack":
            return (
                f"攻击波买@{pf.format(px)}"
                f"（低{pf.format(float(low_px))}+{entry_pct*100:.1f}%）"
            )
        return f"开盘突破买@{pf.format(px)}"

    def _finish(out: dict[str, Any]) -> dict[str, Any]:
        sell = out["side"] == "sell"
        if sell:
            out["因子价"] = round(float(stop_px), px_digits)
            out["距因子价差"] = dist_stop_px
            out["距因子%"] = dist_stop_pct
            if out.get("t1_lock"):
                out["因子触发"] = "不可用"
                out["建议挂单"] = None
                out["actionable"] = False
            else:
                out["actionable"] = True
                alert = str(out.get("alert") or "")
                if out.get("hit_stop") or "已触止损" in alert:
                    out["因子触发"] = "已触发"
                elif out.get("near_stop") or "将止损" in alert:
                    out["因子触发"] = "接近"
                else:
                    out["因子触发"] = "未触发"
                if out.get("建议挂单") is not None and out.get("因子价") is not None:
                    out["建议挂单"] = round(float(out["因子价"]), px_digits)
        else:
            out["因子价"] = round(float(buy_trigger), px_digits)
            out["距因子价差"] = dist_buy_px
            out["距因子%"] = dist_buy_pct
            out["actionable"] = True
            if out.get("hit_buy"):
                out["因子触发"] = "已触发"
            elif out.get("near_buy") or out.get("pending_buy"):
                out["因子触发"] = "接近"
            else:
                out["因子触发"] = "未触发"
            if out.get("建议挂单") is not None:
                out["建议挂单"] = round(float(buy_trigger), px_digits)
        if sell:
            if out.get("t1_lock"):
                out["持仓状态"] = "持有"
            elif bool(out.get("pending_sell")):
                out["持仓状态"] = "待卖出"
            else:
                out["持仓状态"] = "持有"
        else:
            out["持仓状态"] = "待买入" if bool(out.get("pending_buy")) else "空仓"
        pos_st = str(out.get("持仓状态") or "")
        if pos_st == "待卖出":
            out["因子侧"] = "卖出"
        elif pos_st == "待买入":
            out["因子侧"] = "买入"
        elif pos_st == "持有":
            out["因子侧"] = "持有"
        else:
            out["因子侧"] = "空仓"
        if holding:
            trig_side, trig_px = "买入", round(float(buy_trigger), px_digits)
            next_side, next_px = "卖出", round(float(stop_px), px_digits)
        else:
            trig_side, trig_px = "卖出", round(float(stop_px), px_digits)
            next_side, next_px = "买入", round(float(buy_trigger), px_digits)

        def _signed(px: float, side: str) -> tuple[float | None, float | None]:
            dpx, dpct = _dist(px)
            if dpx is None or dpct is None:
                return None, None
            if side == "卖出":
                return round(-dpx, px_digits), round(-dpct, 2)
            return dpx, dpct

        d_trig_px, d_trig_pct = _signed(trig_px, trig_side)
        d_next_px, d_next_pct = _signed(next_px, next_side)
        out["已触发因子侧"] = trig_side
        out["已触发因子价"] = trig_px
        out["未触发因子侧"] = next_side
        out["未触发因子价"] = next_px
        out["距已触发价差"] = d_trig_px
        out["距已触发%"] = d_trig_pct
        out["距未触发价差"] = d_next_px
        out["距未触发%"] = d_next_pct
        out["距因子价差"] = d_next_px
        out["距因子%"] = d_next_pct
        return out

    if holding:
        if t1_lock:
            base.update(
                {
                    "alert": "持有·T+1",
                    "bg_class": "status-hold",
                    "挂单说明": "",
                    "建议挂单": None,
                    "pending_sell": False,
                    "near_stop": False,
                    "actionable": False,
                }
            )
            return _finish(base)
        base["actionable"] = True
        if hit_stop:
            base.update(
                {
                    "pending_sell": True,
                    "alert": "已触止损",
                    "bg_class": "warn-sell",
                    "建议挂单": stop_px,
                    "挂单说明": _sell_note(),
                }
            )
            return _finish(base)
        if near_stop_band:
            base.update(
                {
                    "near_stop": True,
                    "pending_sell": True,
                    "alert": "将止损",
                    "bg_class": "warn-sell",
                    "建议挂单": stop_px,
                    "挂单说明": _sell_note(near=True),
                }
            )
            return _finish(base)
        base.update(
            {
                "alert": "持有",
                "bg_class": "status-hold",
                "建议挂单": stop_px,
                "挂单说明": _sell_note(holding_idle=True),
                "pending_sell": False,
            }
        )
        return _finish(base)

    if hit_buy:
        note = _buy_note(buy_kind, buy_trigger)
        if hit_open and hit_attack and buy_kind == "attack":
            note += f"；兼开盘突破@{pf.format(open_buy)}"
        elif hit_open and hit_attack and buy_kind == "open":
            note += f"；兼攻击波@{pf.format(attack_buy)}"
        base.update(
            {
                "pending_buy": True,
                "alert": "已触买",
                "bg_class": "warn-buy",
                "建议挂单": buy_trigger,
                "挂单说明": note,
            }
        )
        return _finish(base)
    if allow_entry and near_buy_band:
        base.update(
            {
                "near_buy": True,
                "pending_buy": True,
                "alert": "将买入",
                "bg_class": "warn-buy",
                "建议挂单": buy_trigger,
                "挂单说明": (
                    f"距{_buy_note(buy_kind, buy_trigger)}在{near_points:g}%内"
                    f"（现差{dist_buy_pct:+.2f}%），预埋限价买@{pf.format(buy_trigger)}"
                ),
            }
        )
        return _finish(base)
    base.update(
        {
            "alert": "空仓",
            "bg_class": "status-flat",
            "建议挂单": buy_trigger if allow_entry else None,
            "挂单说明": (
                ""
                if not allow_entry
                else (
                    f"开盘突破@{pf.format(open_buy)} · "
                    f"攻击波@{pf.format(attack_buy)}"
                    if attack_buy > 0
                    else f"开盘突破@{pf.format(open_buy)}"
                )
            ),
        }
    )
    return _finish(base)


def replay_last_factor_triggers(
    daily: pd.DataFrame,
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float = DEFAULT_PULLBACK_PCT,
    pullback_pct: float | None = None,
    tick: float = TICK_SIZE,
    prev_entry_mode: str = "yin_or_small_yang",
    limit_down_pct: float = 0.10,
) -> dict[str, Any]:
    """日线简化重放（止损用全日 high；买入只认开盘阈值；同 bar 有次序偏差）。"""
    del limit_down_pct  # 接口兼容
    pb = float(pullback_pct if pullback_pct is not None else stop_pct)
    out: dict[str, Any] = {
        "last_buy_date": None,
        "last_buy_px": None,
        "last_sell_date": None,
        "last_sell_px": None,
        "holding": False,
        "last_trigger_date": None,
        "last_trigger_px": None,
        "last_trigger_side": None,
    }
    if daily is None or daily.empty:
        return out
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    if len(df) < 2:
        return out

    holding = False
    buy_day: pd.Timestamp | None = None
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2] if i >= 2 else None
        day = pd.Timestamp(row["date"]).normalize()
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        if o <= 0:
            continue
        open_buy = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
        stop_px = pullback_stop_price(h, pullback_pct=pb, tick=tick)
        allows = prev_day_allows_entry(
            float(prev["open"]),
            float(prev["close"]),
            prev_small_yang_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
        )
        blocked = False
        if prev2 is not None:
            blocked = should_block_entry_by_yang(
                float(prev2["open"]),
                float(prev2["close"]),
                float(prev["open"]),
                float(prev["close"]),
                ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
            )
        if holding:
            sess = str(day.date())
            buy_time = str(buy_day.date()) if buy_day is not None else None
            if not is_t1_buy_day(buy_time, sess) and l <= stop_px + 1e-12:
                out["last_sell_date"] = day
                out["last_sell_px"] = stop_px
                out["last_trigger_date"] = day
                out["last_trigger_px"] = stop_px
                out["last_trigger_side"] = "sell"
                holding = False
                buy_day = None
            continue
        hit_open = h + 1e-12 >= open_buy
        if allows and (not blocked) and hit_open:
            buy_px = open_buy
            out["last_buy_date"] = day
            out["last_buy_px"] = buy_px
            out["last_trigger_date"] = day
            out["last_trigger_px"] = buy_px
            out["last_trigger_side"] = "buy"
            holding = True
            buy_day = day

    out["holding"] = holding
    return out


def path_dependent_buy_hit(
    bars: pd.DataFrame | None,
    *,
    open_px: float,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    tick: float = TICK_SIZE,
    allow_attack: bool = DEFAULT_ALLOW_ATTACK,
) -> dict[str, Any]:
    """按 1 分钟顺序判定买入。默认只认开盘阈值；allow_attack 才启用攻击波。"""
    o = float(open_px)
    open_buy = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
    running_low = float("inf")
    running_high = 0.0
    if bars is None or getattr(bars, "empty", True):
        return {
            "hit_buy": False,
            "buy_px": None,
            "buy_kind": None,
            "touch_ts": None,
            "open_buy": open_buy,
            "attack_buy": 0.0,
        }
    df = bars
    if "ts" in df.columns:
        df = df.sort_values("ts")
    for _, row in df.iterrows():
        try:
            h = float(row["high"])
            lo = float(row["low"])
        except (TypeError, ValueError):
            continue
        if h <= 0 or lo <= 0:
            continue
        # 先用 *此前* running_low 算攻击买点，再更新本分钟最低（防同根 K 先高后低假买）
        prior_low = running_low if running_low < float("inf") else 0.0
        attack = attack_buy_trigger_price(prior_low, entry_pct=entry_pct, tick=tick)
        hit_open = h + 1e-12 >= open_buy
        hit_attack = (
            bool(allow_attack) and attack > 0 and (h + 1e-12 >= attack)
        )
        if hit_open or hit_attack:
            if hit_attack and (not hit_open or attack <= open_buy + 1e-12):
                return {
                    "hit_buy": True,
                    "buy_px": attack,
                    "buy_kind": "attack",
                    "touch_ts": row["ts"] if "ts" in df.columns else None,
                    "open_buy": open_buy,
                    "attack_buy": attack,
                }
            return {
                "hit_buy": True,
                "buy_px": open_buy,
                "buy_kind": "open",
                "touch_ts": row["ts"] if "ts" in df.columns else None,
                "open_buy": open_buy,
                "attack_buy": attack,
            }
        running_low = min(running_low, lo)
        running_high = max(running_high, h)
    attack_now = (
        attack_buy_trigger_price(running_low, entry_pct=entry_pct, tick=tick)
        if running_low < float("inf")
        else 0.0
    )
    return {
        "hit_buy": False,
        "buy_px": None,
        "buy_kind": None,
        "touch_ts": None,
        "open_buy": open_buy,
        "attack_buy": attack_now,
    }


def is_one_word_bar(
    open_px: float,
    high: float,
    low: float,
    *,
    eps: float = 1e-9,
) -> bool:
    """开=高=低：一字板，该分钟通常无法主动成交。"""
    o = float(open_px or 0)
    h = float(high or 0)
    lo = float(low or 0)
    if o <= 0 or h <= 0 or lo <= 0:
        return False
    return abs(h - lo) <= eps and abs(o - h) <= eps


def delayed_t1_stop_fill_px(
    *,
    open_px: float,
    last_px: float | None = None,
    prefer_open: bool = True,
) -> float:
    """T 日止损已触发、T+1 才可卖：按市价离场，不以「已记价」成交。

    · prefer_open：开盘附近用竞价开盘价（低开下杀 = 开盘成交，不是昨日止损价）
    · 错过开盘（午后才看到）则用现价
    """
    o = float(open_px or 0)
    last = float(last_px or 0) if last_px is not None else 0.0
    if prefer_open and o > 0:
        return o
    if last > 0:
        return last
    return o


NOTED_MODE_SELL_OPEN = "sell_open"
NOTED_MODE_GAP_DUMP = "gap_dump"
NOTED_MODE_CONTINUE = "continue_f26"
NOTED_MODE_WAIT_NOTED = "wait_noted"


def open_dump_stop_price(
    open_px: float,
    *,
    dump_pct: float,
    tick: float = TICK_SIZE,
) -> float:
    """次日开盘后再给一段下杀：卖价 = floor(开盘 × (1 − dump_pct))。"""
    o = float(open_px or 0)
    if o <= 0:
        return 0.0
    return floor_to_tick(o * (1.0 - float(dump_pct)), tick)


def noted_next_day_fill(
    *,
    mode: str,
    noted_px: float,
    day_open: float,
    bar_low: float,
    dump_pct: float,
    tick: float = TICK_SIZE,
    first_executable: bool = True,
    cost_px: float | None = None,
    bar_high: float | None = None,
    giveback_arm_pct: float = DEFAULT_GIVEBACK_ARM_PCT,
) -> dict[str, Any]:
    """止损已记后的次日：本根 1m 是否离场。

    · sell_open：可卖后立刻开盘市价（低开吃开盘，高开也可能卖飞）
    · gap_dump：浮盈尚未 >2% 时，基于开盘价下杀 dump_pct 全清（不再因低开立刻卖）
      浮盈 >2% 则交给回吐/档位
    · continue_f26：仅缺口跌破已记价才开盘卖，否则交给浮盈回落一半
    · wait_noted：缺口跌破则开盘卖，否则等价格再碰到已记价
    """
    out = {"hit": False, "fill_px": 0.0, "reason": ""}
    noted = float(noted_px or 0)
    o = float(day_open or 0)
    lo = float(bar_low or 0)
    if noted <= 0 or o <= 0:
        return out
    m = str(mode or NOTED_MODE_SELL_OPEN)
    if m == NOTED_MODE_SELL_OPEN:
        if first_executable:
            return {"hit": True, "fill_px": o, "reason": "noted_open"}
        return out
    gapped = o <= noted + 1e-12
    if m == NOTED_MODE_CONTINUE:
        if gapped and first_executable:
            return {"hit": True, "fill_px": o, "reason": "noted_gap_open"}
        return out
    if m == NOTED_MODE_WAIT_NOTED:
        if gapped and first_executable:
            return {"hit": True, "fill_px": o, "reason": "noted_gap_open"}
        if lo > 0 and lo <= noted + 1e-12:
            return {"hit": True, "fill_px": noted, "reason": "noted_rehit"}
        return out
    # gap_dump：小亏小赚走开放盘−1%；浮盈>2% 不强制下杀
    hi = float(bar_high) if bar_high is not None and float(bar_high) > 0 else 0.0
    if pnl_exceeds(max(o, hi), float(cost_px or 0), giveback_arm_pct):
        return out
    dump_stop = open_dump_stop_price(o, dump_pct=dump_pct, tick=tick)
    if dump_stop > 0 and lo > 0 and lo <= dump_stop + 1e-12:
        fill = o if o <= dump_stop + 1e-12 else dump_stop
        return {"hit": True, "fill_px": fill, "reason": "noted_open_dump"}
    return out


def simulate_factor26_day_1m(
    bars: pd.DataFrame | None,
    *,
    open_px: float,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
    holding_in: bool = False,
    can_sell: bool = True,
    allow_entry: bool = True,
    cost_px: float | None = None,
    peak_high_in: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    stop_noted_px_in: float | None = None,
    prev_close: float | None = None,
    limit_down_pct: float = 0.1,
    noted_mode: str = NOTED_MODE_GAP_DUMP,
    noted_dump_pct: float | None = None,
    allow_attack: bool = DEFAULT_ALLOW_ATTACK,
    vol20_daily: float | None = None,
    hard_gap_mode: str = HARD_GAP_IMMEDIATE,
    hard_gap_dump_pct: float = DEFAULT_HARD_GAP_DUMP_PCT,
    tp_stage_in: int = 0,
    shares_in: int = 1000,
) -> dict[str, Any]:
    """单日 1 分钟路径：买入（默认开盘阈值）+ 多层止盈卖出。

    · holding_in：昨收仍持仓
    · can_sell：非 T+1（买入当日 False）
    · stop_noted_px_in：昨日 T+1 已记；默认次日走峰值回落 2.5%（gap_dump 生产口径）
    · noted_mode：sell_open / gap_dump / continue_f26 / wait_noted（后三者为研究对照）
    · vol20_daily：近 20 日日频实现波动（中段回落距离 = 其一半）
    """
    pb = float(pullback_pct)
    gb = float(giveback_ratio)
    o = float(open_px)
    holding = bool(holding_in)
    buy_px: float | None = None
    buy_kind: str | None = None
    buy_ts: Any = None
    sell_px: float | None = None
    sell_ts: Any = None
    sell_reason: str | None = None
    cost = float(cost_px) if cost_px is not None and float(cost_px) > 0 else 0.0
    if holding and cost <= 0:
        cost = float(o)  # 隔夜未传成本时退回开盘价作保护锚
    running_high = (
        float(peak_high_in)
        if peak_high_in is not None and float(peak_high_in) > 0
        else (cost if holding and cost > 0 else 0.0)
    )
    running_low = float("inf")
    held_low = float("inf")
    open_buy = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
    bought_today = False
    noted = (
        float(stop_noted_px_in)
        if stop_noted_px_in is not None and float(stop_noted_px_in) > 0
        else 0.0
    )
    stop_noted_out: float | None = None
    waited_one_word = False
    first_exec = True
    nmode = str(noted_mode or NOTED_MODE_GAP_DUMP)
    ndump = float(noted_dump_pct) if noted_dump_pct is not None else DEFAULT_NOTED_DUMP_PCT
    prev_c = float(prev_close) if prev_close is not None and float(prev_close) > 0 else 0.0
    ld_pct = float(limit_down_pct) if limit_down_pct is not None else 0.1
    use_legacy_noted = nmode != NOTED_MODE_GAP_DUMP
    t1_armed = bool(noted > 0 and (not use_legacy_noted))
    session_peak = 0.0
    tp_stage = max(0, int(tp_stage_in or 0))
    sh = max(100, int(shares_in or 1000))
    half_px: float | None = None
    half_ts: Any = None
    half_shares = 0

    rows: list[dict[str, Any]] = []
    if bars is not None and not getattr(bars, "empty", True):
        df = bars.sort_values("ts") if "ts" in bars.columns else bars
        for _, row in df.iterrows():
            try:
                h = float(row["high"])
                lo = float(row["low"])
            except (TypeError, ValueError):
                continue
            if h <= 0 or lo <= 0:
                continue
            try:
                o_bar = float(row["open"]) if "open" in getattr(df, "columns", []) else o
            except (TypeError, ValueError):
                o_bar = o
            try:
                c_bar = (
                    float(row["close"])
                    if "close" in getattr(df, "columns", [])
                    else h
                )
            except (TypeError, ValueError):
                c_bar = h
            rows.append(
                {
                    "high": h,
                    "low": lo,
                    "open": o_bar if o_bar > 0 else o,
                    "close": c_bar if c_bar > 0 else h,
                    "ts": row["ts"] if "ts" in df.columns else None,
                }
            )

    for row in rows:
        h, lo = float(row["high"]), float(row["low"])

        if holding and can_sell and (not bought_today) and (running_high > 0 or cost > 0 or noted > 0):
            bar_o = float(row.get("open") or o or h)
            # 止损已记：T+1 推迟市价离场。一字封死等开板；否则按开盘价（低开不是已记价）
            if noted > 0 and use_legacy_noted:
                locked = False
                if prev_c > 0:
                    limit_px = floor_to_tick(prev_c * (1.0 - ld_pct), tick)
                    locked = is_one_word_bar(bar_o, h, lo) and (
                        abs(bar_o - limit_px) <= tick + 1e-9
                    )
                if locked:
                    waited_one_word = True
                    running_low = min(running_low, lo)
                    running_high = max(running_high, h)
                    continue
                day_o = bar_o if waited_one_word else (o if o > 0 else bar_o)
                nxt = noted_next_day_fill(
                    mode=nmode,
                    noted_px=noted,
                    day_open=day_o,
                    bar_low=lo,
                    dump_pct=ndump,
                    tick=tick,
                    first_executable=first_exec,
                    cost_px=cost,
                    bar_high=h,
                )
                first_exec = False
                if nxt.get("hit") and float(nxt.get("fill_px") or 0) > 0:
                    sell_px = float(nxt["fill_px"])
                    sell_ts = row.get("ts")
                    sell_reason = str(nxt.get("reason") or "stop_noted")
                    holding = False
                    running_high = max(running_high, h)
                    noted = 0.0
                    break
            peak = max(running_high, cost) if cost > 0 else running_high
            if peak > 0 and cost > 0:
                ev = eval_multi_tp_bar(
                    bar_open=bar_o,
                    bar_high=h,
                    bar_low=lo,
                    cost_px=cost,
                    peak_before=peak,
                    shares=sh,
                    tp_stage=tp_stage,
                    can_sell=True,
                    overnight_armed=bool(t1_armed),
                    day_open=o if o > 0 else bar_o,
                    giveback_ratio=gb,
                    hard_pct=pb,
                    dump_pct=ndump,
                    vol20_daily=vol20_daily,
                    session_peak_before=session_peak,
                    hard_gap_mode=hard_gap_mode,
                    hard_gap_dump_pct=hard_gap_dump_pct,
                    tick=tick,
                )
                session_peak = float(ev.get("session_peak_after") or session_peak)
                if t1_armed and pnl_exceeds(max(h, o, bar_o), cost, DEFAULT_GIVEBACK_ARM_PCT):
                    t1_armed = False
                    noted = 0.0
                act = ev.get("action") or {}
                fill = float(act.get("fill_px") or 0)
                kind = str(act.get("kind") or "")
                if kind == "half" and fill > 0:
                    sell_n = max(0, min(int(act.get("shares") or 0), sh))
                    sh = max(0, sh - sell_n)
                    tp_stage = 1
                    if half_px is None:
                        half_px = fill
                        half_ts = row.get("ts")
                        half_shares = sell_n
                    running_high = max(running_high, h)
                    if sh <= 0:
                        sell_px = fill
                        sell_ts = row.get("ts")
                        sell_reason = str(act.get("reason") or "ladder_half_10")
                        holding = False
                        break
                    continue
                if kind == "full" and fill > 0:
                    sell_px = fill
                    sell_ts = row.get("ts")
                    sell_reason = str(act.get("reason") or "half_gain")
                    holding = False
                    running_high = max(running_high, h)
                    break

        if (not holding) and allow_entry and (not bought_today):
            prior_low = running_low if running_low < float("inf") else 0.0
            attack = attack_buy_trigger_price(
                prior_low, entry_pct=entry_pct, tick=tick
            )
            hit_open = h + 1e-12 >= open_buy
            hit_attack = (
                bool(allow_attack) and attack > 0 and (h + 1e-12 >= attack)
            )
            if hit_open or hit_attack:
                if hit_attack and (not hit_open or attack <= open_buy + 1e-12):
                    buy_px, buy_kind = attack, "attack"
                else:
                    buy_px, buy_kind = open_buy, "open"
                buy_ts = row.get("ts")
                holding = True
                bought_today = True
                cost = float(buy_px)
                running_high = max(running_high, float(buy_px), h)
                running_low = min(running_low, lo)
                held_low = float(buy_px)
                # T+1：买入当日不可卖；若随后触止损则「止损已记」
                continue

        # T+1 当日：持仓且不可卖时，仍累计最高；盘中只记硬亏损
        if holding and (not can_sell) and bought_today and cost > 0:
            hard = floor_to_tick(cost * (1.0 - pb), tick)
            if hard > 0 and lo <= hard + 1e-12:
                if stop_noted_out is None or hard < stop_noted_out:
                    stop_noted_out = float(hard)

        running_low = min(running_low, lo)
        running_high = max(running_high, h)
        if holding and cost > 0:
            held_low = min(held_low, lo)

    if holding and (not can_sell) and bought_today and cost > 0 and rows:
        last_c = float(rows[-1].get("close") or rows[-1]["high"] or 0)
        day_lo = held_low if held_low < float("inf") else last_c
        dec = resolve_t1_overnight_note(
            cost_px=cost,
            peak_high=max(running_high, cost),
            close_px=last_c,
            hard_pct=pb,
            giveback_ratio=gb,
            tick=tick,
            bar_low=day_lo if day_lo > 0 else None,
        )
        stop_noted_out = dec.get("noted_px")

    peak_out = max(running_high, cost) if cost > 0 else running_high
    stop_now = (
        half_gain_stop_price(peak_out, cost, giveback_ratio=gb, hard_pct=pb, tick=tick)
        if holding and cost > 0 and peak_out > 0
        else (
            exit_stop_price(peak_out, cost_px=None, hard_pct=pb, tick=tick)
            if peak_out > 0
            else 0.0
        )
    )
    return {
        "holding_out": holding,
        "bought_today": bought_today,
        "buy_px": buy_px,
        "buy_kind": buy_kind,
        "buy_ts": buy_ts,
        "sell_px": sell_px,
        "sell_ts": sell_ts,
        "sell_reason": sell_reason,
        "running_high": running_high,
        "peak_high_out": peak_out if holding else 0.0,
        "cost_px": cost if holding else None,
        "stop_px": stop_now,
        "open_buy": open_buy,
        "day_low": running_low if running_low < float("inf") else None,
        "stop_noted_out": stop_noted_out,
        "shares_out": sh if holding else 0,
        "tp_stage_out": tp_stage if holding else 0,
        "half_px": half_px,
        "half_ts": half_ts,
        "half_shares": half_shares,
    }


def replay_factor26_1m(
    daily: pd.DataFrame,
    minutes: pd.DataFrame,
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float = DEFAULT_PULLBACK_PCT,
    pullback_pct: float | None = None,
    tick: float = TICK_SIZE,
    prev_entry_mode: str = "yin_or_small_yang",
    last_n_days: int = 7,
    allow_attack: bool = DEFAULT_ALLOW_ATTACK,
) -> dict[str, Any]:
    """定盘池短窗回测：日线过滤选买卖日，近 last_n_days 用 1 分钟路径成交。

    日线：前日阴/小阳、双阳禁买；回撤预警仍在组合层（本函数只做个股路径）。
    分钟：触买/触止损按时间顺序，避免全日 OHLC 假触。
    allow_attack：默认 False（只买开盘阈值）；True 才开攻击波。
    """
    pb = float(pullback_pct if pullback_pct is not None else stop_pct)
    out: dict[str, Any] = {
        "last_buy_date": None,
        "last_buy_px": None,
        "last_sell_date": None,
        "last_sell_px": None,
        "holding": False,
        "last_trigger_date": None,
        "last_trigger_px": None,
        "last_trigger_side": None,
        "trades": [],
        "days_used": 0,
        "source": "1m",
        "last_n_days": int(last_n_days),
    }
    if daily is None or daily.empty or minutes is None or getattr(minutes, "empty", True):
        out["source"] = "empty"
        return out

    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    if len(df) < 2:
        return out

    m = minutes.copy()
    m["ts"] = pd.to_datetime(m["ts"])
    if getattr(m["ts"].dt, "tz", None) is not None:
        m["ts"] = m["ts"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    m["day"] = m["ts"].dt.strftime("%Y-%m-%d")
    m = m.dropna(subset=["open", "high", "low", "close"])
    m = m[(m["high"] > 0) & (m["low"] > 0)]

    # 有分钟覆盖的交易日，取最近 last_n_days
    m_days = sorted(m["day"].unique())
    if not m_days:
        out["source"] = "empty"
        return out
    use_days = set(m_days[-max(1, int(last_n_days)) :])
    out["days_used"] = len(use_days)

    holding = False
    buy_day: pd.Timestamp | None = None
    cost_px: float | None = None
    peak_high: float | None = None
    stop_noted_px: float | None = None
    tp_stage = 0
    shares_held = 1000
    trades: list[dict[str, Any]] = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2] if i >= 2 else None
        day = pd.Timestamp(row["date"]).normalize()
        sess = str(day.date())
        if sess not in use_days:
            continue
        o = float(row["open"])
        if o <= 0:
            continue
        day_bars = m[m["day"] == sess].sort_values("ts")
        if day_bars.empty:
            continue

        allows = prev_day_allows_entry(
            float(prev["open"]),
            float(prev["close"]),
            prev_small_yang_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
        )
        blocked = False
        if prev2 is not None:
            blocked = should_block_entry_by_yang(
                float(prev2["open"]),
                float(prev2["close"]),
                float(prev["open"]),
                float(prev["close"]),
                ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
            )

        buy_time = str(buy_day.date()) if buy_day is not None else None
        can_sell = holding and (not is_t1_buy_day(buy_time, sess))
        allow_entry = (not holding) and allows and (not blocked)

        # 开盘价优先用首根分钟开盘（更贴近分时）
        try:
            o1 = float(day_bars.iloc[0]["open"])
            if o1 > 0:
                o = o1
        except (TypeError, ValueError, IndexError):
            pass

        prior_closes = df.iloc[:i]["close"].tolist()
        vol20 = realized_vol_daily(prior_closes)

        sim = simulate_factor26_day_1m(
            day_bars,
            open_px=o,
            entry_pct=entry_pct,
            pullback_pct=pb,
            tick=tick,
            holding_in=holding,
            can_sell=can_sell,
            allow_entry=allow_entry,
            cost_px=cost_px if holding else None,
            peak_high_in=peak_high if holding else None,
            stop_noted_px_in=stop_noted_px if holding else None,
            allow_attack=allow_attack,
            vol20_daily=vol20,
            tp_stage_in=tp_stage if holding else 0,
            shares_in=shares_held if holding else 1000,
        )

        if sim.get("sell_px") is not None:
            out["last_sell_date"] = day
            out["last_sell_px"] = float(sim["sell_px"])
            out["last_trigger_date"] = day
            out["last_trigger_px"] = float(sim["sell_px"])
            out["last_trigger_side"] = "sell"
            trades.append(
                {
                    "date": sess,
                    "side": "sell",
                    "px": float(sim["sell_px"]),
                    "ts": str(sim.get("sell_ts") or ""),
                    "note": str(sim.get("sell_reason") or (
                        "stop_noted" if stop_noted_px else "path_stop"
                    )),
                }
            )
            holding = False
            buy_day = None
            cost_px = None
            peak_high = None
            stop_noted_px = None
            tp_stage = 0
            shares_held = 1000

        elif sim.get("half_px") is not None:
            trades.append(
                {
                    "date": sess,
                    "side": "sell",
                    "px": float(sim["half_px"]),
                    "ts": str(sim.get("half_ts") or ""),
                    "note": "ladder_half_10",
                    "shares": int(sim.get("half_shares") or 0),
                }
            )

        if sim.get("buy_px") is not None:
            holding = True
            buy_day = day
            cost_px = float(sim["buy_px"])
            peak_high = float(sim.get("peak_high_out") or cost_px)
            stop_noted_px = None
            out["last_buy_date"] = day
            out["last_buy_px"] = cost_px
            out["last_trigger_date"] = day
            out["last_trigger_px"] = cost_px
            out["last_trigger_side"] = "buy"
            trades.append(
                {
                    "date": sess,
                    "side": "buy",
                    "px": cost_px,
                    "ts": str(sim.get("buy_ts") or ""),
                    "kind": sim.get("buy_kind"),
                }
            )

        if holding:
            peak_high = float(sim.get("peak_high_out") or peak_high or 0)
            if sim.get("cost_px") is not None:
                cost_px = float(sim["cost_px"])
            tp_stage = int(sim.get("tp_stage_out") or 0)
            so = int(sim.get("shares_out") or 0)
            if so > 0:
                shares_held = so
            # T+1 当日触止损 → 止损已记
            noted = sim.get("stop_noted_out")
            if noted is not None and float(noted) > 0:
                stop_noted_px = float(noted)

        elif not sim.get("buy_px"):
            holding = bool(sim.get("holding_out"))

    out["holding"] = holding
    out["trades"] = trades
    return out


__all__ = [
    "DEFAULT_ENTRY_PCT",
    "DEFAULT_PULLBACK_PCT",
    "DEFAULT_ALLOW_ATTACK",
    "DEFAULT_GIVEBACK_RATIO",
    "DEFAULT_LADDER_HALF_PCT",
    "DEFAULT_LADDER_FULL_PCT",
    "DEFAULT_PEAK_PULLBACK_X",
    "DEFAULT_NOTED_DUMP_PCT",
    "DEFAULT_T1_NOTE_PROFIT_LT_PCT",
    "DEFAULT_GIVEBACK_ARM_PCT",
    "DEFAULT_T1_PEAK_TRAIL_PCT",
    "DEFAULT_VOL_GIVEBACK_RATIO",
    "DEFAULT_VOL20_WINDOW",
    "HARD_GAP_IMMEDIATE",
    "HARD_GAP_OPEN_DUMP",
    "HARD_GAP_MODES",
    "DEFAULT_HARD_GAP_DUMP_PCT",
    "STRATEGY_RULES",
    "pullback_stop_price",
    "cost_hard_stop_px",
    "t1_trail_stop_px",
    "overnight_open_protect_px",
    "first_session_exit_fill",
    "half_gain_stop_price",
    "pnl_exceeds",
    "realized_vol_daily",
    "vol_giveback_stop_price",
    "vol_giveback_distance",
    "mid_gain_first_hit",
    "mid_gain_first_stop",
    "mid_gain_tp_candidates",
    "resolve_t1_overnight_note",
    "stop_note_invalidated_by_recovery",
    "exit_stop_price",
    "lot_half_shares",
    "ladder_target_price",
    "peak_pullback_half_price",
    "working_stop_price",
    "overnight_open_dump_fill",
    "eval_multi_tp_bar",
    "path_dependent_pullback_hit",
    "path_dependent_buy_hit",
    "attack_buy_trigger_price",
    "strategy_levels",
    "strategy_signal",
    "replay_last_factor_triggers",
    "simulate_factor26_day_1m",
    "replay_factor26_1m",
    "rules_text",
    "entry_filters_ok",
    "delayed_t1_stop_fill_px",
    "is_one_word_bar",
    "noted_next_day_fill",
    "open_dump_stop_price",
    "NOTED_MODE_SELL_OPEN",
    "NOTED_MODE_GAP_DUMP",
    "NOTED_MODE_CONTINUE",
    "NOTED_MODE_WAIT_NOTED",
    "DEFAULT_NOTED_DUMP_PCT",
]
