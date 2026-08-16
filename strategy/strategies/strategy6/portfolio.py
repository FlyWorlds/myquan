"""旧对照组合：因子3截面选股 + 因子1开盘止损。

已不再注册为策略六（策略六现为因子6 ETF 组合动量）。
本模块保留给 `backtest/compare_f3_select_f1_stop.py` 与回归测试。

相对策略五（纯袖套持有 hold_days）：
  · 买入仍是：昨日收盘 TopK → 今日开盘
  · 额外：持仓非 T+1 日，若 low <= floor(open×(1-stop_pct)) → 按止损价全清
  · 未止损则仍在持满 hold_days 后开盘到期卖
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategy.open_break import DEFAULT_PCT, stop_trigger_price
from strategy.strategies.strategy5.portfolio import (
    PORTFOLIO_DEFAULTS,
    PortfolioResult,
    portfolio_config,
)

COMMISSION = 0.0000854
STAMP = 0.001
SLIP = 0.001
LOT = 100


def simulate_f3_select_f1_stop(
    *,
    factor: pd.DataFrame,
    opens: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    picks: dict[pd.Timestamp, list[str]],
    bt_start: pd.Timestamp,
    hold_days: int,
    top_k: int,
    stop_pct: float,
    initial_cash: float,
    factor_label: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """袖套轮动 + 因子1止损早退。"""
    del highs  # 选股/止损当前只用 open/low/close；保留参数便于扩展
    all_dates = [pd.Timestamp(d) for d in factor.index]
    date_to_i = {d: i for i, d in enumerate(all_dates)}
    sleeve_cash = [initial_cash / hold_days for _ in range(hold_days)]
    sleeve_pos: list[list[dict]] = [[] for _ in range(hold_days)]
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []
    pick_rows: list[dict] = []
    n_stop = 0
    n_time = 0

    for di, d in enumerate(all_dates):
        if d < bt_start:
            continue

        # 1) 先处理卖出：因子1止损（非买入日）或到期开盘卖
        for s_idx in range(hold_days):
            still: list[dict] = []
            for pos in sleeve_pos[s_idx]:
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

                # T+1：买入当日不卖
                if held >= 1:
                    stop_px = stop_trigger_price(o, stop_pct=stop_pct)
                    if low <= stop_px + 1e-12:
                        # 缺口低开穿过止损 → 按开盘价；否则按止损触发价
                        raw = o if o <= stop_px + 1e-12 else stop_px
                        px = raw * (1.0 - SLIP)
                        reason = "stop"
                        sold = True
                        n_stop += 1
                    elif held >= hold_days:
                        px = o * (1.0 - SLIP)
                        reason = "time"
                        sold = True
                        n_time += 1

                if sold:
                    proceeds = pos["shares"] * px
                    fee = proceeds * (COMMISSION + STAMP)
                    sleeve_cash[s_idx] += proceeds - fee
                    trade_rows.append(
                        {
                            "date": d,
                            "symbol": sym,
                            "side": "sell",
                            "shares": pos["shares"],
                            "price": px,
                            "sleeve": s_idx,
                            "reason": reason,
                        }
                    )
                else:
                    still.append(pos)
            sleeve_pos[s_idx] = still

        # 2) 昨日信号 → 今日开盘买入（空袖套才接）
        prev_i = date_to_i[d] - 1
        if prev_i >= 0:
            prev_d = all_dates[prev_i]
            top = picks.get(prev_d, [])
            if top:
                pick_rows.append(
                    {"signal_date": prev_d, "trade_date": d, "picks": ",".join(top)}
                )
                s_idx = di % hold_days
                if not sleeve_pos[s_idx] and sleeve_cash[s_idx] > 0:
                    budget_each = sleeve_cash[s_idx] / max(len(top), 1)
                    for sym in top:
                        if sym not in opens.columns or pd.isna(opens.at[d, sym]):
                            continue
                        px = float(opens.at[d, sym]) * (1.0 + SLIP)
                        if px <= 0:
                            continue
                        shares = int(budget_each // (px * LOT)) * LOT
                        if shares <= 0:
                            continue
                        cost = shares * px
                        fee = cost * COMMISSION
                        if cost + fee > sleeve_cash[s_idx]:
                            continue
                        sleeve_cash[s_idx] -= cost + fee
                        sleeve_pos[s_idx].append(
                            {"sym": sym, "shares": shares, "entry_i": di}
                        )
                        trade_rows.append(
                            {
                                "date": d,
                                "symbol": sym,
                                "side": "buy",
                                "shares": shares,
                                "price": px,
                                "sleeve": s_idx,
                                "reason": "f3_select",
                            }
                        )

        eq = sum(sleeve_cash)
        for s_idx in range(hold_days):
            for pos in sleeve_pos[s_idx]:
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
        "top_k": top_k,
        "hold_days": hold_days,
        "stop_pct": stop_pct,
        "factor": factor_label,
    }
    return eq_df, tr_df, {**stats, "picks": pk_df}


def run_f3_select_f1_stop_portfolio(
    *,
    kind: str | None = None,
    n: int | None = None,
    top_k: int | None = None,
    hold_days: int | None = None,
    min_score: float | None = None,
    ma_filter: int | None = None,
    stop_pct: float | None = None,
    start: str | None = None,
    end: str | None = None,
    warm_start: str | None = None,
    universe: str | None = None,
    refresh: bool = False,
    initial_cash: float | None = None,
    verbose: bool = True,
) -> PortfolioResult:
    """因子3选股 + 因子1止损组合回测。"""
    from backtest import zz1000_momentum_select as zz
    from strategy.dd_alert import max_drawdown_pct

    cfg = portfolio_config(
        kind=kind,
        n=n,
        top_k=top_k,
        hold_days=hold_days,
        ma_filter=ma_filter,
        start=start,
        warm_start=warm_start,
        universe=universe,
    )
    if min_score is not None or "min_score" in PORTFOLIO_DEFAULTS:
        cfg["min_score"] = (
            min_score if min_score is not None else PORTFOLIO_DEFAULTS.get("min_score")
        )
    stop = float(stop_pct if stop_pct is not None else DEFAULT_PCT)
    cfg["stop_pct"] = stop

    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    cash = float(initial_cash if initial_cash is not None else zz.INITIAL_CASH)
    univ_key = str(cfg.get("universe") or "zz500_1000_mainboard")

    if verbose:
        print(
            f"[因子3选股+因子1止损] pool={univ_key} mode={cfg.get('mode','plain')} "
            f"kind={cfg['kind']} n={cfg['n']} n2={cfg.get('n2')} "
            f"top_k={cfg['top_k']} hold_days={cfg['hold_days']} "
            f"stop={stop*100:.1f}%  {cfg['start']}→{end}"
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
            f"s6/{univ_key}/dual{{n={cfg['n']}+{cfg['n2']}*w{w:g},"
            f"top={cfg['top_k']},hold={cfg['hold_days']},stop={stop}}}"
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
            f"s6/{univ_key}/{cfg['kind']}{{n={cfg['n']},top={cfg['top_k']},"
            f"hold={cfg['hold_days']},stop={stop}}}"
        )

    picks = zz.daily_topk(factor, int(cfg["top_k"]))
    bt_start = pd.Timestamp(str(cfg["start"]))
    idx_tz = getattr(factor.index, "tz", None)
    if idx_tz is not None and bt_start.tzinfo is None:
        bt_start = bt_start.tz_localize(idx_tz)

    eq_df, tr_df, stats = simulate_f3_select_f1_stop(
        factor=factor,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=int(cfg["hold_days"]),
        top_k=int(cfg["top_k"]),
        stop_pct=stop,
        initial_cash=cash,
        factor_label=label,
    )
    if eq_df is None or eq_df.empty:
        raise RuntimeError("策略六：无权益曲线")

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

    return PortfolioResult(
        stats=stats,
        equity=eq_df,
        trades=tr_df if isinstance(tr_df, pd.DataFrame) else pd.DataFrame(),
        picks=pk,
        yearly=yearly,
        name_map=name_map,
        config=cfg,
    )


__all__ = [
    "simulate_f3_select_f1_stop",
    "run_f3_select_f1_stop_portfolio",
]
