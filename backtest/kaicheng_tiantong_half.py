"""天通 + 凯盛 半仓组合回测（与先前分析同口径）。

默认口径（独立半仓等权）
  · 两票各自用策略一跑 akquant（默认各 10 万）
  · 组合净值 = 0.5×凯盛归一权益 + 0.5×天通归一权益（名义本金=每票初始）
  · 组合回撤在合成净值上算；单票回撤用各自 akquant.metrics.max_drawdown_pct

推荐方案（2020-2023 选、2024+ 确认）：保持策略一默认仅止损，不要叠隔日跳买 / 止盈 / 因子4。
说明：共享账户「各票目标 47.5%」会得到另一套数字（约 +1212%），不是本脚本默认。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

import pandas as pd  # noqa: E402

from strategy import KAICHENG, TIANTONG, run_strategy1  # noqa: E402

def _ak_metric(result: Any, key: str) -> float:
    return float(result.metrics_df.iloc[:, 0][key])


def _portfolio_metrics(eq: pd.Series) -> dict[str, Any]:
    eq = eq.dropna().astype(float).sort_index()
    tot = float(eq.iloc[-1]) / float(eq.iloc[0]) - 1.0
    t0, t1 = eq.index[0], eq.index[-1]
    if getattr(eq.index, "tz", None) is not None:
        t0 = t0.tz_convert("Asia/Shanghai")
        t1 = t1.tz_convert("Asia/Shanghai")
    years = max((t1.normalize() - t0.normalize()).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    peak = eq.cummax()
    dd = 1.0 - eq / peak
    mdd = float(dd.max())
    mdd_i = dd.idxmax()
    rets = eq.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    return {
        "start": str(t0.date()),
        "end": str(t1.date()),
        "years": years,
        "total_return_pct": tot * 100.0,
        "annualized_return_pct": ann * 100.0,
        "max_drawdown_pct": mdd * 100.0,
        "max_drawdown_date": str(pd.Timestamp(mdd_i).date()),
        "max_drawdown_value": mdd * float(peak.loc[mdd_i]),
        "end_equity": float(eq.iloc[-1]),
        "volatility": vol,
        "sharpe_ratio": sharpe,
    }


def _yearly_table(port: pd.Series, bh: pd.Series) -> pd.DataFrame:
    def year_end(s: pd.Series) -> pd.Series:
        if getattr(s.index, "tz", None) is not None:
            y = s.index.tz_convert("Asia/Shanghai").year
        else:
            y = s.index.year
        return s.groupby(y).apply(lambda x: float(x.iloc[-1]))

    def yearly_dd(s: pd.Series) -> dict[int, float]:
        if getattr(s.index, "tz", None) is not None:
            y = s.index.tz_convert("Asia/Shanghai").year
        else:
            y = s.index.year
        out: dict[int, float] = {}
        for yr, part in s.groupby(y):
            dd = 1.0 - part / part.cummax()
            out[int(yr)] = float(dd.max()) * 100.0
        return out

    pe, be = year_end(port), year_end(bh)
    yds, ydb = yearly_dd(port), yearly_dd(bh)
    prev_p, prev_b = float(port.iloc[0]), float(bh.iloc[0])
    rows = []
    for yr in sorted(int(x) for x in pe.index):
        p1, b1 = float(pe.loc[yr]), float(be.loc[yr])
        rs, rb = p1 / prev_p - 1.0, b1 / prev_b - 1.0
        rows.append(
            {
                "年份": yr,
                "组合策略%": round(rs * 100, 2),
                "等权持有%": round(rb * 100, 2),
                "超额%": round((rs - rb) * 100, 2),
                "策略回撤%": round(yds[yr], 2),
                "持有回撤%": round(ydb[yr], 2),
            }
        )
        prev_p, prev_b = p1, b1
    return pd.DataFrame(rows)


def _bh_equal_weight(daily_k: pd.DataFrame, daily_t: pd.DataFrame, idx) -> pd.Series:
    def closes(daily: pd.DataFrame) -> pd.Series:
        d = daily.copy().set_index(pd.to_datetime(daily["date"]))
        c = d["close"].astype(float).sort_index()
        c.index = pd.to_datetime(c.index)
        if getattr(idx, "tz", None) is not None and c.index.tz is None:
            c.index = c.index.tz_localize(idx.tz)
        pidx = (
            idx.tz_localize(None).normalize()
            if getattr(idx, "tz", None) is not None
            else pd.DatetimeIndex(idx).normalize()
        )
        c2 = c.copy()
        c2.index = (
            c2.index.tz_localize(None).normalize()
            if c2.index.tz is not None
            else c2.index.normalize()
        )
        aligned = c2.reindex(pidx).ffill().bfill()
        aligned.index = idx
        return aligned / float(aligned.iloc[0])

    return 0.5 * closes(daily_k) + 0.5 * closes(daily_t)


def run_independent_half(
    *,
    sleeve_cash: float = 100_000.0,
    verbose: bool = True,
    force_daily_refresh: bool = False,
) -> dict[str, Any]:
    """独立半仓：两票各跑 akquant，等权合成组合净值。"""
    kc = replace(KAICHENG, initial_cash=float(sleeve_cash))
    tt = replace(TIANTONG, initial_cash=float(sleeve_cash))

    if verbose:
        print(
            "组合口径: 独立半仓等权合成\n"
            f"  · 凯盛 / 天通 各跑策略一（akquant），初始各 {sleeve_cash:,.0f}\n"
            "  · 组合净值 = 0.5×归一凯盛 + 0.5×归一天通\n"
            "  · 单票回撤 = 各自 akquant.metrics.max_drawdown_pct"
        )

    rk, dk = run_strategy1(
        kc,
        show_report=False,
        verbose=False,
        force_daily_refresh=force_daily_refresh,
        apply_factor2_overlay=False,
    )
    rt, dt = run_strategy1(
        tt,
        show_report=False,
        verbose=False,
        force_daily_refresh=force_daily_refresh,
        apply_factor2_overlay=False,
    )

    ek = rk.equity_curve.dropna().astype(float).sort_index()
    et = rt.equity_curve.dropna().astype(float).sort_index()
    common = ek.index.intersection(et.index)
    initial_show = float(sleeve_cash)
    port = (
        0.5 * (ek.reindex(common) / float(ek.iloc[0]))
        + 0.5 * (et.reindex(common) / float(et.iloc[0]))
    ) * initial_show

    bh = _bh_equal_weight(dk, dt, port.index) * initial_show
    pm = _portfolio_metrics(port)
    bm = _portfolio_metrics(bh)
    yearly = _yearly_table(port, bh)

    leg = {
        "凯盛": {
            "total_return_pct": _ak_metric(rk, "total_return_pct"),
            "max_drawdown_pct": _ak_metric(rk, "max_drawdown_pct"),
            "annualized_return": _ak_metric(rk, "annualized_return"),
            "sharpe_ratio": _ak_metric(rk, "sharpe_ratio"),
            "end_market_value": _ak_metric(rk, "end_market_value"),
        },
        "天通": {
            "total_return_pct": _ak_metric(rt, "total_return_pct"),
            "max_drawdown_pct": _ak_metric(rt, "max_drawdown_pct"),
            "annualized_return": _ak_metric(rt, "annualized_return"),
            "sharpe_ratio": _ak_metric(rt, "sharpe_ratio"),
            "end_market_value": _ak_metric(rt, "end_market_value"),
        },
    }

    if verbose:
        print("\n========== 单票（akquant.metrics）==========")
        for name, m in leg.items():
            print(
                f"{name}: 累计 {m['total_return_pct']:.2f}%  "
                f"年化 {m['annualized_return']*100:.2f}%  "
                f"最大回撤 {m['max_drawdown_pct']:.2f}%  "
                f"夏普 {m['sharpe_ratio']:.3f}"
            )

        print("\n========== 组合（独立半仓等权合成）==========")
        print(f"区间: {pm['start']} → {pm['end']}（{pm['years']:.3f} 年）")
        print(f"累计收益%:     {pm['total_return_pct']:.2f}")
        print(f"年化收益%:     {pm['annualized_return_pct']:.2f}")
        print(
            f"最大回撤%:     {pm['max_drawdown_pct']:.2f}  "
            f"@ {pm['max_drawdown_date']}"
        )
        print(f"夏普(近似):    {pm['sharpe_ratio']:.4f}")
        print(
            f"期末权益:      {pm['end_equity']:,.2f}  "
            f"（名义本金 {initial_show:,.0f}）"
        )
        print(
            f"等权持有:      {bm['total_return_pct']:.2f}%  "
            f"持有最大回撤 {bm['max_drawdown_pct']:.2f}%  "
            f"超额 {pm['total_return_pct']-bm['total_return_pct']:+.2f}pct"
        )
        print("\n========== 分年 ==========")
        print(yearly.to_string(index=False))

    out_csv = Path(__file__).parent / "kaicheng_tiantong_half_independent.csv"
    yearly.to_csv(out_csv, index=False, encoding="utf-8-sig")
    if verbose:
        print(f"\n分年已写入: {out_csv}")

    return {
        "portfolio": pm,
        "hold": bm,
        "legs": leg,
        "yearly": yearly,
        "equity": port,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="天通+凯盛半仓组合（独立半仓等权）")
    p.add_argument(
        "--sleeve-cash",
        type=float,
        default=100_000.0,
        help="每票独立账户初始资金（默认 10万）",
    )
    p.add_argument("--force-refresh", action="store_true")
    args = p.parse_args()
    run_independent_half(
        sleeve_cash=args.sleeve_cash,
        force_daily_refresh=args.force_refresh,
    )
