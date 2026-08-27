"""因子3选股 + 因子1前置过滤 + 因子1买卖（研究组合）。

流程（无未来函数）：
  1) 收盘算因子3截面分数；
  2) 仅保留「次日可按因子1开仓」的票：前日阴/小阳，且非双阳跨日≥阈值；
  3) 在资格池内取 TopK；
  4) 次日按因子1：冲到 ceil(open×(1+entry)) 限价买；仅开盘−stop 止损卖。

相对旧对照 `_unreg_s6`（开盘直接买 + 止损/到期卖）：
  · 选股加了因子1前置；
  · 买入改为开盘突破触发，而非开盘市价；
  · 默认只止损卖出（可选 hold_days 到期卖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from strategy.costs import (
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    TICK_SIZE,
    entry_filters_ok,
    entry_trigger_price,
    stop_trigger_price,
)

LOT = 100

COMBO_DEFAULTS: dict[str, Any] = {
    "kind": "rev",
    "n": 90,
    "top_k": 3,
    "hold_days": None,  # None=只止损；设整数则额外到期开盘卖
    "min_score": None,
    "ma_filter": None,
    "mode": "dual",
    "n2": 40,
    "w": 1.0,
    "entry_pct": DEFAULT_PCT,
    "stop_pct": DEFAULT_PCT,
    "require_f1_precond": True,
    "ban_double_yang": DEFAULT_BAN_DOUBLE_YANG,
    "double_yang_combined_min_pct": DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    "double_yang_combined_mode": DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    "start": "20200101",
    "warm_start": "20180101",
    "universe": "zz500_1000_mainboard",
}


def combo_rules_text(
    *,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    double_yang_combined_min_pct: float = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    top_k: int = 3,
    hold_days: int | None = None,
) -> str:
    hold_txt = (
        f"持满 {hold_days} 日未止损则开盘到期卖"
        if hold_days is not None
        else "不设到期，仅止损卖出"
    )
    return f"""================================================================================
  因子3选股 × 因子1前置 × 因子1买卖（研究组合）
================================================================================
【选股 · 收盘】
  · 因子3截面打分（默认 dual 反转）；
  · 加因子1前置：当日作为「前日」须阴/小阳（收盘 < 开盘×(1+{entry_pct*100:.1f}%)），
    且非「前前日+前日双阳且跨日≥{double_yang_combined_min_pct*100:.0f}%」；
  · 资格池内取 Top{top_k} → 次日才允许尝试开仓。

【买入 · 次日】
  · 空仓且名单内：最高价 >= ceil(开盘×(1+{entry_pct*100:.1f}%)) 按触发价限价买；
  · 当日未触发则错过该信号（不递延），避免前置与交易日错位。

【卖出】
  · 止损：最低价 <= floor(开盘×(1-{stop_pct*100:.1f}%)) → 全清；
  · {hold_txt}
  · T+1：买入当日不卖。
================================================================================
"""


def build_factor1_entry_mask(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    entry_pct: float = DEFAULT_PCT,
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG,
    double_yang_combined_min_pct: float = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    tick: float = TICK_SIZE,
) -> pd.DataFrame:
    """日期 d 为 True：以 d 为「前日」、d-1 为「前前日」时，次日允许因子1开仓。"""
    if double_yang_combined_mode != "span":
        # 面板向量化目前只实现 span；其它模式回退逐格 entry_filters_ok
        return _build_factor1_entry_mask_slow(
            opens,
            closes,
            entry_pct=entry_pct,
            ban_double_yang=ban_double_yang,
            double_yang_combined_min_pct=double_yang_combined_min_pct,
            double_yang_combined_mode=double_yang_combined_mode,
            tick=tick,
        )

    o = opens.astype(float)
    c = closes.astype(float)
    o2 = o.shift(1)
    c2 = c.shift(1)

    yang = c >= (o + float(tick) - 1e-12)
    yang2 = c2 >= (o2 + float(tick) - 1e-12)
    small_yang_ok = c < (o * (1.0 + float(entry_pct)) - 1e-8)
    prev_ok = (~yang) | small_yang_ok

    if ban_double_yang:
        span = c / o2.replace(0, np.nan) - 1.0
        ban = yang2 & yang & (span + 1e-12 >= float(double_yang_combined_min_pct))
    else:
        ban = pd.DataFrame(False, index=o.index, columns=o.columns)

    allow = prev_ok & (~ban) & o.notna() & c.notna() & o2.notna() & c2.notna()
    return allow.fillna(False)


def _build_factor1_entry_mask_slow(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    entry_pct: float,
    ban_double_yang: bool,
    double_yang_combined_min_pct: float,
    double_yang_combined_mode: str,
    tick: float,
) -> pd.DataFrame:
    allow = pd.DataFrame(False, index=opens.index, columns=opens.columns)
    for i in range(1, len(opens.index)):
        d = opens.index[i]
        d2 = opens.index[i - 1]
        for sym in opens.columns:
            po, pc = opens.at[d, sym], closes.at[d, sym]
            p2o, p2c = opens.at[d2, sym], closes.at[d2, sym]
            if any(pd.isna(x) for x in (po, pc, p2o, p2c)):
                continue
            allow.at[d, sym] = entry_filters_ok(
                float(po),
                float(pc),
                float(p2o),
                float(p2c),
                entry_pct=entry_pct,
                ban_double_yang=ban_double_yang,
                double_yang_combined_min_pct=double_yang_combined_min_pct,
                double_yang_combined_mode=double_yang_combined_mode,
                tick=tick,
            )
    return allow


def apply_f1_precond_to_factor(
    factor: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    require_f1_precond: bool = True,
    entry_pct: float = DEFAULT_PCT,
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG,
    double_yang_combined_min_pct: float = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """资格不过的票置 NaN；返回 (masked_factor, mask_or_None)。"""
    if not require_f1_precond:
        return factor, None
    mask = build_factor1_entry_mask(
        opens,
        closes,
        entry_pct=entry_pct,
        ban_double_yang=ban_double_yang,
        double_yang_combined_min_pct=double_yang_combined_min_pct,
        double_yang_combined_mode=double_yang_combined_mode,
    )
    # 对齐列/索引（防面板子集错位）
    mask = mask.reindex(index=factor.index, columns=factor.columns).fillna(False)
    return factor.where(mask), mask


@dataclass
class ComboResult:
    stats: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    picks: pd.DataFrame
    yearly: pd.DataFrame
    name_map: dict[str, str]
    config: dict[str, Any]


def simulate_f3_f1_combo(
    *,
    factor: pd.DataFrame,
    opens: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    picks: dict[pd.Timestamp, list[str]],
    bt_start: pd.Timestamp,
    top_k: int,
    entry_pct: float,
    stop_pct: float,
    initial_cash: float,
    factor_label: str,
    hold_days: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """因子3名单 → 次日因子1突破买 / 止损卖（可选到期）。"""
    all_dates = [pd.Timestamp(d) for d in factor.index]
    date_to_i = {d: i for i, d in enumerate(all_dates)}
    cash = float(initial_cash)
    positions: list[dict[str, Any]] = []
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []
    pick_rows: list[dict] = []
    n_stop = 0
    n_time = 0
    n_miss = 0  # 有名单但未触发突破

    for di, d in enumerate(all_dates):
        if d < bt_start:
            continue

        # 1) 卖出：止损 / 可选到期
        still: list[dict[str, Any]] = []
        for pos in positions:
            sym = pos["sym"]
            held = di - int(pos["entry_i"])
            if (
                sym not in opens.columns
                or pd.isna(opens.at[d, sym])
                or float(opens.at[d, sym]) <= 0
            ):
                still.append(pos)
                continue
            o = float(opens.at[d, sym])
            low = (
                float(lows.at[d, sym])
                if sym in lows.columns and not pd.isna(lows.at[d, sym])
                else o
            )
            sold = False
            reason = ""
            px = 0.0
            if held >= 1:
                stop_px = stop_trigger_price(o, stop_pct=stop_pct)
                if low <= stop_px + 1e-12:
                    raw = o if o <= stop_px + 1e-12 else stop_px
                    px = raw * (1.0 - SLIP)
                    reason = "stop"
                    sold = True
                    n_stop += 1
                elif hold_days is not None and held >= int(hold_days):
                    px = o * (1.0 - SLIP)
                    reason = "time"
                    sold = True
                    n_time += 1
            if sold:
                proceeds = pos["shares"] * px
                fee = proceeds * (COMMISSION + STAMP)
                cash += proceeds - fee
                trade_rows.append(
                    {
                        "date": d,
                        "symbol": sym,
                        "side": "sell",
                        "shares": pos["shares"],
                        "price": px,
                        "reason": reason,
                    }
                )
            else:
                still.append(pos)
        positions = still

        # 2) 昨日名单 → 今日因子1突破买入（空槽才接；当日未触发即错过）
        prev_i = date_to_i[d] - 1
        if prev_i >= 0:
            prev_d = all_dates[prev_i]
            top = picks.get(prev_d, [])
            if top:
                pick_rows.append(
                    {"signal_date": prev_d, "trade_date": d, "picks": ",".join(top)}
                )
            held_syms = {p["sym"] for p in positions}
            slots_left = max(int(top_k) - len(positions), 0)
            if top and slots_left > 0 and cash > 0:
                for sym in top:
                    slots_left = max(int(top_k) - len(positions), 0)
                    if slots_left <= 0 or cash <= 0:
                        break
                    if sym in held_syms:
                        continue
                    if (
                        sym not in opens.columns
                        or pd.isna(opens.at[d, sym])
                        or float(opens.at[d, sym]) <= 0
                    ):
                        continue
                    o = float(opens.at[d, sym])
                    hi = (
                        float(highs.at[d, sym])
                        if sym in highs.columns and not pd.isna(highs.at[d, sym])
                        else o
                    )
                    buy_px_raw = entry_trigger_price(o, entry_pct=entry_pct)
                    if hi + 1e-12 < buy_px_raw:
                        n_miss += 1
                        continue
                    # 缺口高开已越过触发价 → 按开盘；否则按触发价
                    raw = o if o >= buy_px_raw - 1e-12 else buy_px_raw
                    px = raw * (1.0 + SLIP)
                    if px <= 0:
                        continue
                    budget_each = cash / max(slots_left, 1)
                    shares = int(budget_each // (px * LOT)) * LOT
                    if shares <= 0:
                        continue
                    cost = shares * px
                    fee = cost * COMMISSION
                    if cost + fee > cash + 1e-9:
                        continue
                    cash -= cost + fee
                    positions.append({"sym": sym, "shares": shares, "entry_i": di})
                    held_syms.add(sym)
                    trade_rows.append(
                        {
                            "date": d,
                            "symbol": sym,
                            "side": "buy",
                            "shares": shares,
                            "price": px,
                            "reason": "f1_breakout",
                        }
                    )

        eq = cash
        for pos in positions:
            sym = pos["sym"]
            if sym in closes.columns and not pd.isna(closes.at[d, sym]):
                eq += pos["shares"] * float(closes.at[d, sym])
        equity_rows.append({"date": d, "equity": eq})

    eq_df = pd.DataFrame(equity_rows)
    tr_df = pd.DataFrame(trade_rows)
    pk_df = pd.DataFrame(pick_rows)
    if eq_df.empty:
        return eq_df, tr_df, {"error": "no equity"}

    eq = eq_df["equity"].to_numpy(dtype=float)
    rets = np.diff(eq) / np.where(eq[:-1] == 0, np.nan, eq[:-1])
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets) * np.sqrt(252))
        if len(rets) and np.std(rets) > 1e-12
        else 0.0
    )
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.where(peak == 0, np.nan, peak)
    stats = {
        "start": str(eq_df["date"].iloc[0].date()),
        "end": str(eq_df["date"].iloc[-1].date()),
        "n_days": int(len(eq_df)),
        "total_return_pct": float(eq[-1] / initial_cash - 1.0) * 100,
        "max_drawdown_pct": float(np.nanmax(dd)) * 100 if len(dd) else 0.0,
        "sharpe": sharpe,
        "end_equity": float(eq[-1]),
        "n_trades": int(len(tr_df)),
        "n_buys": int((tr_df["side"] == "buy").sum()) if not tr_df.empty else 0,
        "n_stop_exits": int(n_stop),
        "n_time_exits": int(n_time),
        "n_breakout_miss": int(n_miss),
        "top_k": top_k,
        "hold_days": hold_days,
        "entry_pct": entry_pct,
        "stop_pct": stop_pct,
        "factor": factor_label,
    }
    return eq_df, tr_df, {**stats, "picks": pk_df}


def combo_config(**overrides: Any) -> dict[str, Any]:
    cfg = dict(COMBO_DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def run_f3_f1_combo(
    *,
    kind: str | None = None,
    n: int | None = None,
    top_k: int | None = None,
    hold_days: int | None = None,
    min_score: float | None = None,
    ma_filter: int | None = None,
    entry_pct: float | None = None,
    stop_pct: float | None = None,
    require_f1_precond: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    warm_start: str | None = None,
    universe: str | None = None,
    refresh: bool = False,
    initial_cash: float | None = None,
    verbose: bool = True,
    **extra: Any,
) -> ComboResult:
    """跑因子3选股 × 因子1前置 × 因子1买卖。"""
    from backtest import zz1000_momentum_select as zz
    from strategy.dd_alert import max_drawdown_pct

    cfg = combo_config(
        kind=kind,
        n=n,
        top_k=top_k,
        hold_days=hold_days,
        ma_filter=ma_filter,
        entry_pct=entry_pct,
        stop_pct=stop_pct,
        require_f1_precond=require_f1_precond,
        start=start,
        warm_start=warm_start,
        universe=universe,
        **{k: v for k, v in extra.items() if v is not None},
    )
    if min_score is not None or "min_score" in COMBO_DEFAULTS:
        cfg["min_score"] = (
            min_score if min_score is not None else COMBO_DEFAULTS.get("min_score")
        )

    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    cash = float(initial_cash if initial_cash is not None else zz.INITIAL_CASH)
    univ_key = str(cfg.get("universe") or "zz500_1000_mainboard")
    ep = float(cfg["entry_pct"])
    sp = float(cfg["stop_pct"])
    use_pre = bool(cfg.get("require_f1_precond", True))

    if verbose:
        print(
            f"[f3×f1] pool={univ_key} mode={cfg.get('mode')} kind={cfg['kind']} "
            f"n={cfg['n']} n2={cfg.get('n2')} top_k={cfg['top_k']} "
            f"entry={ep*100:.1f}% stop={sp*100:.1f}% "
            f"precond={'on' if use_pre else 'off'} hold={cfg.get('hold_days')} "
            f"{cfg['start']}→{end}"
        )

    if univ_key in ("zz500_1000_mainboard", "zz500_1000", "500+1000"):
        univ = zz.load_zz500_1000_mainboard()
        panel_path = zz.PANEL_PATH_ZZ500_1000
    elif univ_key in ("zz1000_mainboard", "zz1000"):
        univ = zz.load_zz1000_mainboard()
        panel_path = zz.PANEL_PATH
    elif univ_key in ("zz500_mainboard", "zz500"):
        univ = zz.load_zz500_mainboard()
        panel_path = zz.OUT_DIR / "panel_ohlc_zz500.parquet"
    else:
        raise ValueError(f"未知股票池: {univ_key}")

    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = zz.load_panel_matrices(
        univ["symbol"].tolist(),
        warm_start=str(cfg["warm_start"]),
        end=end,
        refresh=refresh,
        panel_path=panel_path,
    )
    if verbose:
        print(f"面板 close={closes.shape}")

    mode = str(cfg.get("mode") or "plain")
    if mode in ("dual", "dual_w") and cfg.get("n2"):
        from backtest.mine_zz1000_momentum import factor_matrix

        r1 = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n"]))
        r2 = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n2"]))

        def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
            mu = df.mean(axis=1)
            sd = df.std(axis=1).replace(0, np.nan)
            return df.sub(mu, axis=0).div(sd, axis=0)

        w = float(cfg.get("w") or 1.0)
        factor = _cs_z(r1) + w * _cs_z(r2)
        label = (
            f"f3f1/{univ_key}/dual{{n={cfg['n']}+{cfg['n2']}*w{w:g},"
            f"top={cfg['top_k']},entry={ep},stop={sp},pre={int(use_pre)}}}"
        )
    else:
        factor = zz.compute_factor(
            opens,
            highs,
            lows,
            closes,
            kind=str(cfg["kind"]),
            n=int(cfg["n"]),
            min_score=cfg["min_score"],
            ma_filter=cfg["ma_filter"],
        )
        label = (
            f"f3f1/{univ_key}/{cfg['kind']}{{n={cfg['n']},top={cfg['top_k']},"
            f"entry={ep},stop={sp},pre={int(use_pre)}}}"
        )

    factor, mask = apply_f1_precond_to_factor(
        factor,
        opens,
        closes,
        require_f1_precond=use_pre,
        entry_pct=ep,
        ban_double_yang=bool(cfg.get("ban_double_yang", True)),
        double_yang_combined_min_pct=float(
            cfg.get("double_yang_combined_min_pct", DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT)
        ),
        double_yang_combined_mode=str(
            cfg.get("double_yang_combined_mode", DEFAULT_DOUBLE_YANG_COMBINED_MODE)
        ),
    )
    if verbose and mask is not None:
        valid = float(mask.to_numpy().mean()) * 100
        print(f"因子1前置通过率(面板格点)≈{valid:.1f}%")

    picks = zz.daily_topk(factor, int(cfg["top_k"]))
    bt_start = pd.Timestamp(str(cfg["start"]))
    idx_tz = getattr(factor.index, "tz", None)
    if idx_tz is not None and bt_start.tzinfo is None:
        bt_start = bt_start.tz_localize(idx_tz)

    hd = cfg.get("hold_days")
    eq_df, tr_df, stats = simulate_f3_f1_combo(
        factor=factor,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        top_k=int(cfg["top_k"]),
        entry_pct=ep,
        stop_pct=sp,
        initial_cash=cash,
        factor_label=label,
        hold_days=int(hd) if hd is not None else None,
    )
    if eq_df is None or eq_df.empty:
        raise RuntimeError("f3×f1 组合：无权益曲线")

    eq = eq_df.set_index("date")["equity"].astype(float).sort_index()
    yearly_rows: list[dict[str, Any]] = []
    years = (
        eq.index.tz_convert("Asia/Shanghai").year
        if getattr(eq.index, "tz", None)
        else eq.index.year
    )
    for y, g in eq.groupby(years):
        prev = eq[eq.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else cash
        yearly_rows.append(
            {
                "year": int(y),
                "return_pct": float(g.iloc[-1] / base - 1.0) * 100,
                "max_dd_pct": max_drawdown_pct(g) * 100 if len(g) > 1 else 0.0,
            }
        )
    yearly = pd.DataFrame(yearly_rows)
    pk = stats.get("picks")
    if not isinstance(pk, pd.DataFrame):
        pk = pd.DataFrame()

    if verbose:
        print(
            f"收益{stats['total_return_pct']:.2f}% DD{stats['max_drawdown_pct']:.2f}% "
            f"夏普{stats['sharpe']:.3f} 买{stats['n_buys']} "
            f"止损{stats['n_stop_exits']} 到期{stats['n_time_exits']} "
            f"未触发{stats['n_breakout_miss']}"
        )

    return ComboResult(
        stats=stats,
        equity=eq_df,
        trades=tr_df if isinstance(tr_df, pd.DataFrame) else pd.DataFrame(),
        picks=pk,
        yearly=yearly,
        name_map=name_map,
        config=cfg,
    )


__all__ = [
    "COMBO_DEFAULTS",
    "ComboResult",
    "apply_f1_precond_to_factor",
    "build_factor1_entry_mask",
    "combo_config",
    "combo_rules_text",
    "run_f3_f1_combo",
    "simulate_f3_f1_combo",
]
