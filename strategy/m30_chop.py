"""因子25 · 30 分钟震荡减磨损：确认止损 + 动态半仓止盈 + 卖飞回补。

研究用途，非投资建议。叠在因子1 日线开仓/止损价之上：
  · 止损：连续 N 根 30m 收盘 ≤ 当日因子1 止损价（过滤影线假破）
  · 动态止盈：成本涨幅达 arm 后，非新高棒且自峰值回撤 ≥ giveback → 减半；trail 不回补
  · 卖飞回补：仅止损卖出后，在 horizon 内以「差不多价」接回；回补窗内禁新 F1
  · 当日已触日线止损价低点 → 禁新开 F1（避免刀口接飞刀）

天通 2026-08-14～09-03（±3%、含费滑点）样本内对照见
``backtest/strategy15_m30_chop/``。区间窄、同样本调参，扩样本前勿当生产默认。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

DEFAULT_STOP_CONFIRM_BARS = 2
DEFAULT_RECLAIM_BAND = 0.015
DEFAULT_RECLAIM_PREMIUM_MAX = 0.015
DEFAULT_RECLAIM_HORIZON = 8
DEFAULT_TRAIL_ARM_PCT = 0.12
DEFAULT_TRAIL_GIVEBACK_PCT = 0.05
DEFAULT_TRAIL_REDUCE_RATIO = 0.5


@dataclass(frozen=True)
class M30ChopParams:
    stop_confirm_bars: int = DEFAULT_STOP_CONFIRM_BARS
    reclaim_band: float = DEFAULT_RECLAIM_BAND
    reclaim_premium_max: float = DEFAULT_RECLAIM_PREMIUM_MAX
    reclaim_horizon: int = DEFAULT_RECLAIM_HORIZON
    reclaim_require_yang: bool = True
    reclaim_break_prior_high: bool = True
    reclaim_require_above_day_stop: bool = True
    reclaim_enabled: bool = True
    trail_arm_pct: float = DEFAULT_TRAIL_ARM_PCT
    trail_giveback_pct: float = DEFAULT_TRAIL_GIVEBACK_PCT
    trail_reduce_ratio: float = DEFAULT_TRAIL_REDUCE_RATIO
    suppress_f1_during_reclaim: bool = True
    no_f1_if_day_low_hit_stop: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class M30ChopState:
    """跨 30m 棒状态（单票）。"""

    below_stop_streak: int = 0
    peak_high: float = 0.0
    tp_half_done: bool = False
    sell_px: float | None = None
    sell_qty: float = 0.0
    reclaim_left: int = 0
    sell_reason: str | None = None  # "stop" | "trail"
    prior_bar_high: float | None = None
    day_low_hit_stop: bool = False

    def clear_reclaim(self) -> None:
        self.sell_px = None
        self.sell_qty = 0.0
        self.reclaim_left = 0
        self.sell_reason = None

    def reset_position_peak(self) -> None:
        self.peak_high = 0.0
        self.tp_half_done = False
        self.below_stop_streak = 0


def rules_text(params: M30ChopParams | None = None) -> str:
    p = params or M30ChopParams()
    return (
        "因子25-30分钟震荡减磨损\n"
        f"  · 止损确认：连续 {p.stop_confirm_bars} 根 30m 收盘 ≤ 当日因子1 止损价\n"
        f"  · 动态止盈：成本≥+{p.trail_arm_pct:.0%} 后，非新高棒且收盘≤峰值×"
        f"(1-{p.trail_giveback_pct:.0%}) → 减仓 {p.trail_reduce_ratio:.0%}；trail 不回补\n"
        f"  · 卖飞回补：止损后 {p.reclaim_horizon} 棒内，价在卖出价±{p.reclaim_band:.1%}，"
        f"且成交≤卖出价×(1+{p.reclaim_premium_max:.1%})；阳线+破前棒高+≥当日止损\n"
        f"  · 回补窗内{'禁止' if p.suppress_f1_during_reclaim else '允许'}新开因子1；"
        f"当日低点已触止损价则{'禁止' if p.no_f1_if_day_low_hit_stop else '允许'}新开\n"
        "研究默认，非投资建议"
    )


def update_day_stop_touch(
    state: M30ChopState, *, low: float, stop_px: float
) -> None:
    if float(low) <= float(stop_px) + 1e-12:
        state.day_low_hit_stop = True


def trail_signal(
    *,
    high: float,
    close: float,
    cost: float,
    state: M30ChopState,
    params: M30ChopParams,
    t_plus_one: bool = False,
) -> dict[str, Any]:
    """持仓中动态半仓止盈。"""
    if t_plus_one or state.tp_half_done or cost <= 0:
        return {"ok": False, "reason": "skip"}
    hi = float(high)
    cl = float(close)
    prev_peak = float(state.peak_high or 0.0)
    new_high = prev_peak > 0 and hi > prev_peak + 1e-12
    peak = max(prev_peak, hi)
    state.peak_high = peak
    armed = peak / float(cost) - 1.0 >= float(params.trail_arm_pct) - 1e-12
    giveback = cl <= peak * (1.0 - float(params.trail_giveback_pct)) + 1e-12
    if not armed:
        return {"ok": False, "reason": "not_armed", "peak": peak}
    if new_high:
        return {"ok": False, "reason": "new_high_bar", "peak": peak}
    if not giveback:
        return {"ok": False, "reason": "no_giveback", "peak": peak}
    return {
        "ok": True,
        "reason": (
            f"trail arm≥{params.trail_arm_pct:.0%} "
            f"giveback≥{params.trail_giveback_pct:.0%}"
        ),
        "fill_px": cl,
        "reduce_ratio": float(params.trail_reduce_ratio),
        "peak": peak,
    }


def stop_confirm_signal(
    *,
    close: float,
    stop_px: float,
    state: M30ChopState,
    params: M30ChopParams,
    t_plus_one: bool = False,
) -> dict[str, Any]:
    if t_plus_one:
        return {"ok": False, "reason": "t1", "streak": state.below_stop_streak}
    if float(close) <= float(stop_px) + 1e-12:
        state.below_stop_streak += 1
    else:
        state.below_stop_streak = 0
    need = max(1, int(params.stop_confirm_bars))
    if state.below_stop_streak < need:
        return {
            "ok": False,
            "reason": f"streak={state.below_stop_streak}/{need}",
            "streak": state.below_stop_streak,
        }
    return {
        "ok": True,
        "reason": f"m30_close×{need}≤stop",
        "fill_px": float(close),
        "streak": state.below_stop_streak,
    }


def reclaim_signal(
    *,
    open_px: float,
    high: float,
    low: float,
    close: float,
    day_stop_px: float,
    state: M30ChopState,
    params: M30ChopParams,
) -> dict[str, Any]:
    """止损卖飞后的差不多价回补（不回补 trail）。"""
    if not params.reclaim_enabled:
        return {"ok": False, "reason": "disabled"}
    if state.sell_reason != "stop" or state.sell_px is None or state.reclaim_left <= 0:
        return {"ok": False, "reason": "no_window"}

    state.reclaim_left -= 1
    sell = float(state.sell_px)
    band = float(params.reclaim_band)
    prem = float(params.reclaim_premium_max)
    cl = float(close)
    op = float(open_px)
    hi = float(high)
    lo = float(low)

    near = lo <= sell * (1.0 + band) + 1e-12 and hi >= sell * (1.0 - band) - 1e-12
    in_band_close = cl >= sell * (1.0 - band) - 1e-12
    cheap_enough = cl <= sell * (1.0 + prem) + 1e-12
    yang = (not params.reclaim_require_yang) or (cl >= op - 1e-12)
    broke = (not params.reclaim_break_prior_high) or (
        state.prior_bar_high is None or cl > float(state.prior_bar_high) + 1e-12
    )
    above_stop = (not params.reclaim_require_above_day_stop) or (
        cl >= float(day_stop_px) - 1e-12
    )

    if state.reclaim_left <= 0 and not (
        near and in_band_close and cheap_enough and yang and broke and above_stop
    ):
        # 窗口耗尽：由调用方 clear；此处仍返回 not ok
        pass

    if not (
        near and in_band_close and cheap_enough and yang and broke and above_stop
    ):
        if state.reclaim_left <= 0:
            return {"ok": False, "reason": "window_expired"}
        return {"ok": False, "reason": "filters"}

    return {
        "ok": True,
        "reason": f"reclaim near±{band:.1%} prem≤{prem:.1%}",
        "fill_px": cl,
        "qty_hint": float(state.sell_qty),
    }


def f1_entry_allowed(
    state: M30ChopState,
    params: M30ChopParams,
    *,
    has_position: bool,
) -> dict[str, Any]:
    if has_position:
        return {"ok": False, "reason": "has_pos"}
    if params.suppress_f1_during_reclaim and state.sell_px is not None and state.reclaim_left > 0:
        return {"ok": False, "reason": "reclaim_window"}
    if params.no_f1_if_day_low_hit_stop and state.day_low_hit_stop:
        return {"ok": False, "reason": "day_hit_stop"}
    return {"ok": True, "reason": "ok"}


def on_stop_sold(
    state: M30ChopState,
    *,
    fill_px: float,
    qty: float,
    params: M30ChopParams,
) -> None:
    state.reset_position_peak()
    if params.reclaim_enabled:
        state.sell_px = float(fill_px)
        state.sell_qty = float(qty)
        state.reclaim_left = int(params.reclaim_horizon)
        state.sell_reason = "stop"
    else:
        state.clear_reclaim()


def on_trail_sold(state: M30ChopState) -> None:
    """半仓 trail 后不设回补窗。"""
    state.tp_half_done = True
    # 不 clear 持仓峰值；剩余仓位继续跟踪 peak


def advisory_levels(
    *,
    cost: float | None,
    stop_px: float | None,
    sell_px: float | None,
    params: M30ChopParams | None = None,
) -> dict[str, Any]:
    """盯盘用：动态止盈触发带、回补带。"""
    p = params or M30ChopParams()
    out: dict[str, Any] = {
        "trail_arm_pct": p.trail_arm_pct,
        "trail_giveback_pct": p.trail_giveback_pct,
        "reclaim_band": p.reclaim_band,
        "reclaim_premium_max": p.reclaim_premium_max,
        "stop_confirm_bars": p.stop_confirm_bars,
    }
    if cost and cost > 0:
        out["trail_arm_px"] = round(float(cost) * (1.0 + p.trail_arm_pct), 3)
    if stop_px and stop_px > 0:
        out["day_stop_px"] = round(float(stop_px), 3)
    if sell_px and sell_px > 0:
        s = float(sell_px)
        out["reclaim_lo"] = round(s * (1.0 - p.reclaim_band), 3)
        out["reclaim_hi"] = round(s * (1.0 + min(p.reclaim_band, p.reclaim_premium_max)), 3)
        out["reclaim_anchor"] = round(s, 3)
    return out


@dataclass
class M30SimTrade:
    date: str
    time: str
    kind: str
    price: float
    qty: int
    reason: str = ""


@dataclass
class M30SimResult:
    return_pct: float
    buy_hold_pct: float
    excess_pct: float
    max_dd_pct: float
    end_equity: float
    trades: list[M30SimTrade] = field(default_factory=list)
    eod: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def simulate_factor1_m30_chop(
    *,
    bars_by_day: dict[str, Sequence[Any]],
    day_open: dict[str, float],
    day_can_enter: dict[str, bool],
    buy_px_fn,
    stop_px_fn,
    params: M30ChopParams | None = None,
    initial_cash: float = 100_000.0,
    fee: float = 0.0015,
    slip: float = 0.001,
    lot: int = 100,
    target_cash_frac: float = 0.95,
) -> M30SimResult:
    """因子1 开仓价 + 因子25 30m 出场/回补仿真。

    ``bars_by_day`` 每根棒需有属性/键：open, high, low, close；可选 ts。
    """
    p = params or M30ChopParams()
    cash = float(initial_cash)
    pos = 0
    avg = 0.0
    buy_day: str | None = None
    state = M30ChopState()
    trades: list[M30SimTrade] = []
    eod: list[dict[str, Any]] = []
    peak_eq = initial_cash
    max_dd = 0.0
    first_close: float | None = None
    last_close = 0.0

    def _bar_get(b: Any, key: str) -> float:
        if hasattr(b, key):
            return float(getattr(b, key))
        if isinstance(b, dict):
            return float(b[key])
        raise TypeError(f"bar missing {key}")

    def _bar_time(b: Any) -> str:
        ts = getattr(b, "ts", None) if not isinstance(b, dict) else b.get("ts")
        if ts is None:
            return ""
        s = str(ts)
        return s[11:16] if len(s) >= 16 else s

    for d, gs in bars_by_day.items():
        if not gs:
            continue
        o = float(day_open.get(d) or _bar_get(gs[0], "open"))
        buy_px = float(buy_px_fn(o))
        stop_px = float(stop_px_fn(o))
        state.day_low_hit_stop = False
        t1 = pos > 0 and buy_day == d

        for b in gs:
            hi = _bar_get(b, "high")
            lo = _bar_get(b, "low")
            cl = _bar_get(b, "close")
            op = _bar_get(b, "open")
            hm = _bar_time(b)
            update_day_stop_touch(state, low=lo, stop_px=stop_px)

            if pos > 0 and not t1:
                tr = trail_signal(
                    high=hi,
                    close=cl,
                    cost=avg,
                    state=state,
                    params=p,
                    t_plus_one=False,
                )
                if tr.get("ok"):
                    qty = int(pos * float(tr["reduce_ratio"])) // lot * lot
                    if qty >= lot:
                        cash += cl * qty * (1.0 - fee - slip)
                        pos -= qty
                        on_trail_sold(state)
                        trades.append(
                            M30SimTrade(d, hm, "trail半仓", round(cl, 3), qty, str(tr["reason"]))
                        )

            if pos > 0 and not t1:
                st = stop_confirm_signal(
                    close=cl,
                    stop_px=stop_px,
                    state=state,
                    params=p,
                    t_plus_one=False,
                )
                if st.get("ok"):
                    cash += cl * pos * (1.0 - fee - slip)
                    trades.append(
                        M30SimTrade(d, hm, "止损", round(cl, 3), pos, str(st["reason"]))
                    )
                    on_stop_sold(state, fill_px=cl, qty=float(pos), params=p)
                    pos = 0
                    avg = 0.0
                    buy_day = None
                    state.prior_bar_high = hi
                    continue

            if pos == 0 and state.sell_px is not None and state.reclaim_left > 0:
                rc = reclaim_signal(
                    open_px=op,
                    high=hi,
                    low=lo,
                    close=cl,
                    day_stop_px=stop_px,
                    state=state,
                    params=p,
                )
                if rc.get("ok"):
                    fill = float(rc["fill_px"])
                    want = int(state.sell_qty)
                    max_q = int(cash * target_cash_frac / fill / lot) * lot
                    qty = min(want, max_q) // lot * lot
                    if qty >= lot:
                        cash -= fill * qty * (1.0 + fee + slip)
                        pos, avg, buy_day, t1 = qty, fill, d, True
                        state.reset_position_peak()
                        state.peak_high = hi
                        state.clear_reclaim()
                        trades.append(
                            M30SimTrade(d, hm, "回补", round(fill, 3), qty, str(rc["reason"]))
                        )
                elif state.reclaim_left <= 0:
                    state.clear_reclaim()

            gate = f1_entry_allowed(state, p, has_position=pos > 0)
            if (
                gate.get("ok")
                and bool(day_can_enter.get(d, True))
                and hi + 1e-12 >= buy_px
            ):
                fill = buy_px
                qty = int(cash * target_cash_frac / fill / lot) * lot
                if qty >= lot:
                    cash -= fill * qty * (1.0 + fee + slip)
                    pos, avg, buy_day, t1 = qty, fill, d, True
                    state.reset_position_peak()
                    state.peak_high = hi
                    state.clear_reclaim()
                    trades.append(
                        M30SimTrade(d, hm, "F1买", round(fill, 3), qty, "open_break")
                    )

            state.prior_bar_high = hi

        last_close = float(_bar_get(gs[-1], "close"))
        if first_close is None:
            first_close = last_close
        eq = cash + pos * last_close
        peak_eq = max(peak_eq, eq)
        dd = (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0
        max_dd = max(max_dd, dd)
        eod.append({"date": d, "equity": round(eq, 2), "pos": pos, "close": last_close})

    end_eq = eod[-1]["equity"] if eod else initial_cash
    ret = (end_eq / initial_cash - 1.0) * 100.0
    bh = (
        ((last_close / first_close) - 1.0) * 100.0
        if first_close and first_close > 0
        else 0.0
    )
    return M30SimResult(
        return_pct=ret,
        buy_hold_pct=bh,
        excess_pct=ret - bh,
        max_dd_pct=max_dd * 100.0,
        end_equity=float(end_eq),
        trades=trades,
        eod=eod,
        params=p.as_dict(),
    )


def simulate_half_probe(
    *,
    fine_bars_by_day: dict[str, Sequence[Any]],
    m30_bars_by_day: dict[str, Sequence[Any]],
    day_open: dict[str, float],
    day_can_enter: dict[str, bool],
    buy_px_fn,
    stop_px_fn,
    params: M30ChopParams | None = None,
    initial_cash: float = 100_000.0,
    fee: float = 0.0015,
    slip: float = 0.001,
    lot: int = 100,
    target_cash_frac: float = 0.95,
    confirm_bars: int = 2,
    touch_fill: str = "stop",
) -> M30SimResult:
    """触止损先出一半；再用连续 confirm_bars 根 30m 收盘决定接回或清完。

    ``fine_bars_by_day``：1m/5m（触价与开仓更准）
    ``m30_bars_by_day``：30m（站稳/没站稳）
    ``touch_fill``：``stop`` 按止损价卖半仓；``close`` 按触价那根细周期收盘卖。
    """
    p = params or M30ChopParams()
    need = max(1, int(confirm_bars))
    cash = float(initial_cash)
    pos = 0
    avg = 0.0
    buy_day: str | None = None
    state = M30ChopState()
    trades: list[M30SimTrade] = []
    eod: list[dict[str, Any]] = []
    peak_eq = initial_cash
    max_dd = 0.0
    first_close: float | None = None
    last_close = 0.0

    # 半仓试探止损状态
    probe = False
    half_qty = 0
    half_px = 0.0
    above_n = 0
    below_n = 0

    def _get(b: Any, key: str) -> float:
        if isinstance(b, dict):
            return float(b[key])
        return float(getattr(b, key))

    def _ts(b: Any):
        import pandas as pd

        raw = b.get("ts") if isinstance(b, dict) else getattr(b, "ts", None)
        return pd.Timestamp(raw)

    def _hm(b: Any) -> str:
        s = str(_ts(b))
        return s[11:16] if len(s) >= 16 else s

    def _clear_probe() -> None:
        nonlocal probe, half_qty, half_px, above_n, below_n
        probe = False
        half_qty = 0
        half_px = 0.0
        above_n = 0
        below_n = 0

    days = sorted(set(fine_bars_by_day) | set(m30_bars_by_day))
    for d in days:
        fine = list(fine_bars_by_day.get(d) or [])
        m30 = list(m30_bars_by_day.get(d) or [])
        if not fine and not m30:
            continue
        o = float(day_open.get(d) or _get((fine or m30)[0], "open"))
        buy_px = float(buy_px_fn(o))
        stop_px = float(stop_px_fn(o))
        state.day_low_hit_stop = False
        t1 = pos > 0 and buy_day == d
        # 新交易日：试探计数按新止损重计，半仓状态保留
        above_n = 0
        below_n = 0

        m30_i = 0
        for b in fine:
            ts = _ts(b)
            hi, lo, cl = _get(b, "high"), _get(b, "low"), _get(b, "close")
            hm = _hm(b)
            update_day_stop_touch(state, low=lo, stop_px=stop_px)

            # 先处理已走完的 30m（ts <= 当前细周期）
            while m30_i < len(m30) and _ts(m30[m30_i]) <= ts:
                m = m30[m30_i]
                m30_i += 1
                m_cl = _get(m, "close")
                m_hm = _hm(m)
                if not probe or pos <= 0:
                    continue
                if m_cl > stop_px + 1e-12:
                    above_n += 1
                    below_n = 0
                else:
                    below_n += 1
                    above_n = 0
                if above_n >= need and half_qty >= lot:
                    # 假跌破：接回半仓
                    fill = float(m_cl)
                    max_q = int(cash * target_cash_frac / fill / lot) * lot
                    qty = min(half_qty, max_q) // lot * lot
                    if qty >= lot:
                        cash -= fill * qty * (1.0 + fee + slip)
                        # 加权成本
                        new_pos = pos + qty
                        avg = (avg * pos + fill * qty) / new_pos if new_pos else fill
                        pos = new_pos
                        trades.append(
                            M30SimTrade(
                                d, m_hm, "假破接回", round(fill, 3), qty, f"m30×{need}>stop"
                            )
                        )
                    _clear_probe()
                elif below_n >= need and pos >= lot:
                    # 没站稳：清完
                    cash += m_cl * pos * (1.0 - fee - slip)
                    trades.append(
                        M30SimTrade(
                            d, m_hm, "止损清完", round(m_cl, 3), pos, f"m30×{need}≤stop"
                        )
                    )
                    pos = 0
                    avg = 0.0
                    buy_day = None
                    state.reset_position_peak()
                    _clear_probe()

            if pos > 0 and not t1 and not probe:
                # 动态止盈（未在试探中）
                tr = trail_signal(
                    high=hi,
                    close=cl,
                    cost=avg,
                    state=state,
                    params=p,
                    t_plus_one=False,
                )
                if tr.get("ok"):
                    qty = int(pos * float(tr["reduce_ratio"])) // lot * lot
                    if qty >= lot:
                        cash += cl * qty * (1.0 - fee - slip)
                        pos -= qty
                        on_trail_sold(state)
                        trades.append(
                            M30SimTrade(d, hm, "trail半仓", round(cl, 3), qty, str(tr["reason"]))
                        )

            # 触止损 → 先出一半
            if (
                pos > 0
                and not t1
                and not probe
                and lo <= stop_px + 1e-12
            ):
                qty = (pos // 2 // lot) * lot
                if qty >= lot:
                    fill = stop_px if touch_fill == "stop" else cl
                    cash += fill * qty * (1.0 - fee - slip)
                    pos -= qty
                    probe = True
                    half_qty = qty
                    half_px = fill
                    above_n = 0
                    below_n = 0
                    trades.append(
                        M30SimTrade(
                            d, hm, "触损半仓", round(fill, 3), qty, "touch→half"
                        )
                    )

            # 开仓：试探中或当日已触止损则不开新 F1
            can_f1 = (
                pos == 0
                and not probe
                and not (p.no_f1_if_day_low_hit_stop and state.day_low_hit_stop)
                and bool(day_can_enter.get(d, True))
                and hi + 1e-12 >= buy_px
            )
            if can_f1:
                fill = buy_px
                qty = int(cash * target_cash_frac / fill / lot) * lot
                if qty >= lot:
                    cash -= fill * qty * (1.0 + fee + slip)
                    pos, avg, buy_day, t1 = qty, fill, d, True
                    state.reset_position_peak()
                    state.peak_high = hi
                    _clear_probe()
                    trades.append(
                        M30SimTrade(d, hm, "F1买", round(fill, 3), qty, "open_break")
                    )

        # 日末未处理完的 30m
        while m30_i < len(m30):
            m = m30[m30_i]
            m30_i += 1
            if not probe or pos <= 0:
                continue
            m_cl = _get(m, "close")
            m_hm = _hm(m)
            if m_cl > stop_px + 1e-12:
                above_n += 1
                below_n = 0
            else:
                below_n += 1
                above_n = 0
            if above_n >= need and half_qty >= lot:
                fill = float(m_cl)
                max_q = int(cash * target_cash_frac / fill / lot) * lot
                qty = min(half_qty, max_q) // lot * lot
                if qty >= lot:
                    cash -= fill * qty * (1.0 + fee + slip)
                    new_pos = pos + qty
                    avg = (avg * pos + fill * qty) / new_pos if new_pos else fill
                    pos = new_pos
                    trades.append(
                        M30SimTrade(
                            d, m_hm, "假破接回", round(fill, 3), qty, f"m30×{need}>stop"
                        )
                    )
                _clear_probe()
            elif below_n >= need and pos >= lot:
                cash += m_cl * pos * (1.0 - fee - slip)
                trades.append(
                    M30SimTrade(
                        d, m_hm, "止损清完", round(m_cl, 3), pos, f"m30×{need}≤stop"
                    )
                )
                pos = 0
                avg = 0.0
                buy_day = None
                state.reset_position_peak()
                _clear_probe()

        last_bar = fine[-1] if fine else m30[-1]
        last_close = float(_get(last_bar, "close"))
        if first_close is None:
            first_close = last_close
        eq = cash + pos * last_close
        peak_eq = max(peak_eq, eq)
        dd = (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0
        max_dd = max(max_dd, dd)
        eod.append({"date": d, "equity": round(eq, 2), "pos": pos, "close": last_close})

    end_eq = eod[-1]["equity"] if eod else initial_cash
    ret = (end_eq / initial_cash - 1.0) * 100.0
    bh = (
        ((last_close / first_close) - 1.0) * 100.0
        if first_close and first_close > 0
        else 0.0
    )
    return M30SimResult(
        return_pct=ret,
        buy_hold_pct=bh,
        excess_pct=ret - bh,
        max_dd_pct=max_dd * 100.0,
        end_equity=float(end_eq),
        trades=trades,
        eod=eod,
        params={
            **p.as_dict(),
            "stop_mode": "half_probe",
            "confirm_bars": need,
            "touch_fill": touch_fill,
        },
    )


def group_bars_by_day(
    df,
    *,
    ts_col: str = "ts",
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list]:
    """DataFrame → Ordered day map of row dicts。"""
    from collections import OrderedDict

    import pandas as pd

    m = df.copy()
    m[ts_col] = pd.to_datetime(m[ts_col])
    m = m.sort_values(ts_col)
    if getattr(m[ts_col].dt, "tz", None) is not None:
        local = m[ts_col].dt.tz_convert("Asia/Shanghai")
    else:
        local = m[ts_col].dt.tz_localize("Asia/Shanghai")
    m["d"] = local.dt.strftime("%Y-%m-%d")
    if start:
        m = m[m["d"] >= start]
    if end:
        m = m[m["d"] <= end]
    out: OrderedDict[str, list] = OrderedDict()
    for rec in m.to_dict(orient="records"):
        d = str(rec["d"])
        out.setdefault(d, []).append(rec)
    return out


__all__ = [
    "DEFAULT_RECLAIM_BAND",
    "DEFAULT_RECLAIM_HORIZON",
    "DEFAULT_RECLAIM_PREMIUM_MAX",
    "DEFAULT_STOP_CONFIRM_BARS",
    "DEFAULT_TRAIL_ARM_PCT",
    "DEFAULT_TRAIL_GIVEBACK_PCT",
    "DEFAULT_TRAIL_REDUCE_RATIO",
    "M30ChopParams",
    "M30ChopState",
    "M30SimResult",
    "M30SimTrade",
    "advisory_levels",
    "f1_entry_allowed",
    "group_bars_by_day",
    "on_stop_sold",
    "on_trail_sold",
    "reclaim_signal",
    "rules_text",
    "simulate_factor1_m30_chop",
    "simulate_half_probe",
    "stop_confirm_signal",
    "trail_signal",
    "update_day_stop_touch",
]
