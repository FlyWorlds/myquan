"""因子26 · 浮盈回落一半止盈：买=开盘突破或攻击波，卖=持仓最高浮盈回落一半。

买入：
  1) 开盘突破：最高 ≥ ceil(open×(1+entry_pct))
  2) 攻击波：最高 ≥ ceil(当日最低×(1+entry_pct))（自最低点向上攻击阈值）
  过滤同因子1。
卖出（止盈/保护）：
  · 已浮盈：floor(成本 + (1−giveback)×(持仓最高−成本))，默认 giveback=0.5（回落一半）
  · 未浮盈：floor(成本×(1−hard_pct)) 成本回撤保护，默认 hard_pct=2.5%
触达判定：按 **1 分钟 K 时间顺序**——先用此前最高算卖价，再抬升 peak。
默认 entry ±2.5%。

日线回放用全日 high/low（同 bar 有次序偏差）。
盯盘触达：必须按 1 分钟顺序；禁止用「全日最低 vs 抬高后卖价」。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

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
    prev_day_allows_entry,
    should_block_entry_by_yang,
)

DEFAULT_ENTRY_PCT = DEFAULT_PCT
DEFAULT_PULLBACK_PCT = DEFAULT_PCT  # 未浮盈时的成本硬保护
DEFAULT_GIVEBACK_RATIO = 0.5  # 浮盈回落一半

STRATEGY_RULES = """
================================================================================
  因子26 · 浮盈回落一半止盈（买=开盘突破或攻击波）
================================================================================

【空仓 · 买入】两条任一触发（过滤同因子1：前日阴/小阳；禁双阳；T+1）
  A) 开盘突破：当日最高 >= ceil(开盘 × (1+阈值))，按该触发价限价买
  B) 攻击波：  当日最高 >= ceil(当日最低 × (1+阈值))，自最低点向上攻击阈值

【有仓 · 卖出】
  卖价 = 浮盈回落一半（持仓以来最高相对成本）：
    · 已浮盈：floor(成本 + 0.5×(持仓最高 − 成本))
    · 未浮盈：floor(成本 × (1 − 硬保护阈值))，默认硬保护 2.5%
  · 触达判定：按 1 分钟 K 顺序 —— 先用「此前最高」算卖价，再看该分钟最低是否跌破；
    然后才用本分钟最高抬升 peak（禁止全日 low 对抬高后卖价）
  · 买入当日不可卖（除非 t0）

【默认】entry 2.5%；giveback 50%；未浮盈硬保护 2.5%。
【说明】选股/过滤用日线；成交触达用 1 分钟 path-dependent（定盘池短窗约 7 日）。
  长窗日线回测仍有同 bar 次序偏差。
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


def half_gain_stop_price(
    peak_high: float,
    cost_px: float,
    *,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
    hard_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """浮盈回落一半卖价；未浮盈时用成本硬保护。

    giveback_ratio=0.5 → 卖价 = 成本 + 0.5×(最高−成本)（峰值浮盈回吐一半出场）。
    """
    cost = float(cost_px)
    peak = float(peak_high)
    if cost <= 0:
        return 0.0
    if peak <= cost + 1e-12:
        return floor_to_tick(cost * (1.0 - float(hard_pct)), tick)
    gb = min(max(float(giveback_ratio), 0.0), 1.0)
    return floor_to_tick(cost + (1.0 - gb) * (peak - cost), tick)


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
) -> dict[str, Any]:
    """按分钟 K 时间顺序判定浮盈回落一半（或硬保护）是否曾触达。

    每根 bar：
      1) 用 *此前* running_high 算卖价，若 bar.low ≤ 卖价 → 触达
      2) 再 running_high = max(running_high, bar.high)

    since_ts：只统计该时刻之后的触达（实仓用买入时间）。
    seed_high：持仓峰值初值（成本或已记录 peak）。
    cost_px：成本；默认用 seed_high。
    """
    pb = float(pullback_pct)
    gb = float(giveback_ratio)
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
            out_rows.append({"high": h, "low": lo, "ts": ts})
        return out_rows

    def _stop(peak: float) -> float:
        return exit_stop_price(
            peak,
            cost_px=cost if cost > 0 else None,
            giveback_ratio=gb,
            hard_pct=pb,
            tick=tick,
        )

    for row in _iter_rows():
        if running_high > 0 or cost > 0:
            peak = max(running_high, cost) if cost > 0 else running_high
            if peak > 0:
                stop = _stop(peak)
                if row["low"] <= stop + 1e-12:
                    return {
                        "hit_stop": True,
                        "running_high": peak,
                        "stop_px": stop,
                        "touch_ts": row.get("ts"),
                        "touch_stop": stop,
                        "source": "1m",
                        "stop_kind": "half_gain",
                        "cost_px": cost,
                    }
        running_high = max(running_high, float(row["high"]))

    if live_low is not None and float(live_low) > 0:
        peak = max(running_high, cost) if cost > 0 else running_high
        if peak > 0:
            stop = _stop(peak)
            if float(live_low) <= stop + 1e-12:
                return {
                    "hit_stop": True,
                    "running_high": peak,
                    "stop_px": stop,
                    "touch_ts": touch_ts,
                    "touch_stop": stop,
                    "source": "1m+live",
                    "stop_kind": "half_gain",
                    "cost_px": cost,
                }
    if live_high is not None and float(live_high) > 0:
        running_high = max(running_high, float(live_high))

    peak_now = max(running_high, cost) if cost > 0 else running_high
    stop_now = _stop(peak_now) if peak_now > 0 else 0.0
    return {
        "hit_stop": False,
        "running_high": peak_now,
        "stop_px": stop_now,
        "touch_ts": None,
        "touch_stop": touch_stop,
        "source": "1m" if peak_now > 0 else "empty",
        "stop_kind": "half_gain",
        "cost_px": cost,
    }


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
    **_extra: Any,
) -> dict[str, float]:
    """buy：开盘突破与攻击波取更易触发者；stop=浮盈回落一半（相对成本/峰值）。"""
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
    if attack_buy > 0 and (buy <= 0 or attack_buy < buy):
        buy = attack_buy
    cost = float(cost_px) if cost_px is not None and float(cost_px) > 0 else float(open_px)
    peak = float(peak_high) if peak_high is not None and float(peak_high) > 0 else anchor
    peak = max(peak, cost, anchor)
    stop = half_gain_stop_price(
        peak,
        cost,
        giveback_ratio=giveback_ratio,
        hard_pct=pb,
        tick=tick,
    )
    return {
        "buy_trigger": buy,
        "buy": buy,
        "open_buy": open_buy,
        "attack_buy": attack_buy,
        "stop": stop,
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
        f"因子26-浮盈回落一半止盈\n"
        f"  · 买A：开盘+{entry_pct*100:.1f}%\n"
        f"  · 买B：攻击波=当日最低+{entry_pct*100:.1f}%\n"
        f"  · 卖：浮盈回落 {giveback_ratio*100:.0f}%（未浮盈成本保护 {pullback_pct*100:.1f}%）\n"
        f"  · 默认绑策略一"
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
    cost_px: float | None = None,
    peak_high: float | None = None,
    giveback_ratio: float = DEFAULT_GIVEBACK_RATIO,
) -> dict[str, Any]:
    """盯盘信号：开盘突破或攻击波买入；卖出=浮盈回落一半。

    hit_stop：若传入则尊重调用方（应用 1 分钟 path-dependent 结果）；
    否则退回 low≤stop（日线/无分钟时有次序偏差）。
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
    )
    open_buy = float(lv["open_buy"])
    attack_buy = float(lv["attack_buy"])
    stop_px = float(stop_px if stop_px is not None else lv["stop"])

    hit_open = high_px + 1e-12 >= open_buy
    hit_attack = attack_buy > 0 and (high_px + 1e-12 >= attack_buy)
    hit_buy = bool(allow_entry) and (hit_open or hit_attack)

    if hit_attack and (not hit_open or attack_buy <= open_buy + 1e-12):
        eff_buy = attack_buy
        buy_kind = "attack"
    elif hit_open:
        eff_buy = open_buy
        buy_kind = "open"
    elif buy_trigger is not None and float(buy_trigger) > 0:
        eff_buy = float(buy_trigger)
        buy_kind = (
            "open" if abs(eff_buy - open_buy) <= abs(eff_buy - attack_buy) else "attack"
        )
    elif attack_buy > 0 and attack_buy < open_buy:
        eff_buy = attack_buy
        buy_kind = "attack"
    else:
        eff_buy = open_buy
        buy_kind = "open"

    buy_trigger = float(eff_buy)

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
        "stop_kind": "half_gain",
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
                    "挂单说明": (
                        f"回落波止损@{pf.format(stop_px)}"
                        f"（高{pf.format(float(high_px))}回落{pb*100:.1f}%）"
                    ),
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
                    "挂单说明": (
                        f"距回落波止损在{near_points:g}%内"
                        f"（高{pf.format(float(high_px))}→止{pf.format(stop_px)}）"
                    ),
                }
            )
            return _finish(base)
        base.update(
            {
                "alert": "持有",
                "bg_class": "status-hold",
                "建议挂单": stop_px,
                "挂单说明": (
                    f"回落波止损=分时最高×(1-{pb*100:.1f}%)"
                    f"@{pf.format(stop_px)}"
                ),
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
    """日线简化重放（止损用全日 high；买入含攻击波；同 bar 有次序偏差）。"""
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
        attack_buy = attack_buy_trigger_price(l, entry_pct=entry_pct, tick=tick)
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
        hit_attack = attack_buy > 0 and (h + 1e-12 >= attack_buy)
        if allows and (not blocked) and (hit_open or hit_attack):
            if hit_attack and (not hit_open or attack_buy <= open_buy + 1e-12):
                buy_px = attack_buy
            else:
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
) -> dict[str, Any]:
    """按 1 分钟顺序判定开盘突破 / 攻击波买入（running_low 抬升攻击阈值）。"""
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
        running_low = min(running_low, lo)
        attack = attack_buy_trigger_price(running_low, entry_pct=entry_pct, tick=tick)
        hit_open = h + 1e-12 >= open_buy
        hit_attack = attack > 0 and (h + 1e-12 >= attack)
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
) -> dict[str, Any]:
    """单日 1 分钟路径：买入（开盘突破/攻击波）+ 浮盈回落一半卖出。

    · holding_in：昨收仍持仓
    · can_sell：非 T+1（买入当日 False）
    · cost_px / peak_high_in：隔夜持仓成本与持仓以来最高
    · 同分钟先按「此前最高」判卖，再抬高；空仓才判买入
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
    cost = float(cost_px) if cost_px is not None and float(cost_px) > 0 else 0.0
    if holding and cost <= 0:
        cost = float(o)  # 隔夜未传成本时退回开盘价作保护锚
    running_high = (
        float(peak_high_in)
        if peak_high_in is not None and float(peak_high_in) > 0
        else (cost if holding and cost > 0 else 0.0)
    )
    running_low = float("inf")
    open_buy = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
    bought_today = False

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
            rows.append(
                {
                    "high": h,
                    "low": lo,
                    "ts": row["ts"] if "ts" in df.columns else None,
                }
            )

    for row in rows:
        h, lo = float(row["high"]), float(row["low"])
        running_low = min(running_low, lo)

        if holding and can_sell and (not bought_today) and (running_high > 0 or cost > 0):
            peak = max(running_high, cost) if cost > 0 else running_high
            if peak > 0 and cost > 0:
                stop = half_gain_stop_price(
                    peak, cost, giveback_ratio=gb, hard_pct=pb, tick=tick
                )
                if lo <= stop + 1e-12:
                    sell_px = stop
                    sell_ts = row.get("ts")
                    holding = False
                    running_high = max(running_high, h)
                    break

        if (not holding) and allow_entry and (not bought_today):
            attack = attack_buy_trigger_price(
                running_low, entry_pct=entry_pct, tick=tick
            )
            hit_open = h + 1e-12 >= open_buy
            hit_attack = attack > 0 and (h + 1e-12 >= attack)
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
                # T+1：买入当日不再卖
                continue

        running_high = max(running_high, h)

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
        "running_high": running_high,
        "peak_high_out": peak_out if holding else 0.0,
        "cost_px": cost if holding else None,
        "stop_px": stop_now,
        "open_buy": open_buy,
        "day_low": running_low if running_low < float("inf") else None,
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
) -> dict[str, Any]:
    """定盘池短窗回测：日线过滤选买卖日，近 last_n_days 用 1 分钟路径成交。

    日线：前日阴/小阳、双阳禁买；回撤预警仍在组合层（本函数只做个股路径）。
    分钟：触买/触止损按时间顺序，避免全日 OHLC 假触。
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
                }
            )
            holding = False
            buy_day = None
            cost_px = None
            peak_high = None

        if sim.get("buy_px") is not None:
            out["last_buy_date"] = day
            out["last_buy_px"] = float(sim["buy_px"])
            out["last_trigger_date"] = day
            out["last_trigger_px"] = float(sim["buy_px"])
            out["last_trigger_side"] = "buy"
            trades.append(
                {
                    "date": sess,
                    "side": "buy",
                    "px": float(sim["buy_px"]),
                    "kind": sim.get("buy_kind"),
                    "ts": str(sim.get("buy_ts") or ""),
                }
            )
            holding = True
            buy_day = day
            cost_px = float(sim["buy_px"])
            peak_high = float(sim.get("peak_high_out") or sim["buy_px"])
        else:
            holding = bool(sim.get("holding_out"))
            if holding:
                if sim.get("cost_px") is not None:
                    cost_px = float(sim["cost_px"])
                peak_high = float(sim.get("peak_high_out") or peak_high or 0) or peak_high

    out["holding"] = holding
    out["trades"] = trades
    return out


__all__ = [
    "DEFAULT_ENTRY_PCT",
    "DEFAULT_PULLBACK_PCT",
    "DEFAULT_GIVEBACK_RATIO",
    "STRATEGY_RULES",
    "pullback_stop_price",
    "half_gain_stop_price",
    "exit_stop_price",
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
]
