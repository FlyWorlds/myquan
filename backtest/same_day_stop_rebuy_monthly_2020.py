"""2020~今：止损后再买区间策略 — 分月对比 + 牛/熊/震荡月表现。

牛/熊/震荡：以中证500（000905）月末涨跌划分
  · 牛月：月涨幅 > +3%
  · 熊月：月涨幅 < -3%
  · 震荡月：[-3%, +3%]

仅供研究，不构成投资建议。
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy import BacktestConfig, run_open_break  # noqa: E402
from strategy.backtest import metric, monthly_returns_df  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from backtest.same_day_stop_rebuy_scan import UNIVERSE, _load_daily, _sina  # noqa: E402

_OUT = Path(__file__).resolve().parent / "same_day_stop_rebuy_2020_monthly"
START = "20200101"
END = dt.date.today().strftime("%Y%m%d")
INITIAL = 100_000.0

BULL_TH = 3.0
BEAR_TH = -3.0

BANDS: list[tuple[str, float, float | None]] = [
    ("基线_止损日禁买", 0.0, None),
    ("0-0.5点", 0.0, 0.005),
    ("0.5-1点", 0.005, 0.01),
    ("1-1.5点", 0.01, 0.015),
    ("1.5-2点", 0.015, 0.02),
    ("2-2.5点", 0.02, 0.025),
]

# 2025 样本内各标的最优区间（供对照）
BEST_BAND: dict[str, str] = {
    "东材科技": "0.5-1点",
    "西藏珠峰": "1.5-2点",
    "凯盛科技": "0-0.5点",
    "天通股份": "0-0.5点",
    "金安国纪": "1-1.5点",
    "科创综指ETF汇添富": "1.5-2点",
    "科创半导体ETF华夏": "0.5-1点",
}


def _fetch_csi500_monthly(start: str, end: str) -> pd.Series:
    """中证500 月收益率 %（月末/上月末-1）。"""
    cache = _ROOT / "data_cache" / "sh000905_index_daily.parquet"
    if cache.exists():
        px = pd.read_parquet(cache)
    else:
        raw = ak.stock_zh_index_daily(symbol="sh000905")
        px = raw.rename(columns={"date": "date", "close": "close"})
        px["date"] = pd.to_datetime(px["date"])
        px = px.sort_values("date")
        cache.parent.mkdir(parents=True, exist_ok=True)
        px.to_parquet(cache, index=False)
    px = px.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is not None:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    s = px.set_index("date")["close"].sort_index()
    s = s[(s.index >= pd.Timestamp(start[:4] + "-" + start[4:6] + "-" + start[6:8]))]
    monthly = s.resample("ME").last().pct_change() * 100.0
    monthly.index = monthly.index.to_period("M").astype(str)
    return monthly.dropna()


def _regime(mkt_ret: float) -> str:
    if mkt_ret > BULL_TH:
        return "牛月"
    if mkt_ret < BEAR_TH:
        return "熊月"
    return "震荡月"


def _cfg(item: dict[str, Any], start: str, end: str) -> BacktestConfig:
    code = str(item["code"])
    sym = _sina(code)
    cache = _ROOT / "data_cache" / f"{sym}_daily_qfq.parquet"
    kw: dict[str, Any] = dict(
        symbol=sym,
        symbol_name=str(item["name"]),
        em_symbol=code,
        entry_pct=float(item["entry"]),
        stop_pct=float(item["stop"]),
        threshold_pct=float(item["entry"]),
        start_date=start,
        end_date=end,
        initial_cash=INITIAL,
        t0=False,
        daily_cache=cache,
    )
    if item.get("etf"):
        kw["stamp_tax_rate"] = 0.0
        kw["tick"] = 0.001
    return BacktestConfig(**kw)


def _run_variant(
    base: BacktestConfig,
    daily: pd.DataFrame,
    label: str,
    lo: float,
    hi: float | None,
) -> tuple[Any, pd.DataFrame]:
    allow = label != "基线_止损日禁买"
    cfg = replace(
        base,
        allow_same_day_rebuy_after_stop=allow,
        rebuy_require_yang=False,
        rebuy_from_low_pct=0.0,
        rebuy_above_stop_pct=float(lo),
        rebuy_above_stop_max_pct=None if hi is None else float(hi),
        report_path=None,
    )
    result, data = run_open_break(cfg, show_report=False, verbose=False)
    mon = monthly_returns_df(result, data, initial_cash=INITIAL)
    mon["variant"] = label
    mon["symbol"] = cfg.symbol
    mon["name"] = cfg.symbol_name
    stats = {
        "name": cfg.symbol_name,
        "symbol": cfg.symbol,
        "variant": label,
        "total_return_pct": metric(result.metrics_df, "total_return_pct"),
        "max_drawdown_pct": metric(result.metrics_df, "max_drawdown_pct"),
        "sharpe_ratio": metric(result.metrics_df, "sharpe_ratio"),
        "closed_trades": metric(result.metrics_df, "closed_trade_count"),
    }
    return stats, mon


def main() -> None:
    logging.disable(logging.INFO)
    _OUT.mkdir(parents=True, exist_ok=True)

    mkt = _fetch_csi500_monthly(START, END)
    mkt_df = mkt.reset_index()
    mkt_df.columns = ["月份", "中证500月涨%"]
    mkt_df["市场状态"] = mkt_df["中证500月涨%"].map(_regime)
    mkt_df.to_csv(_OUT / "market_regime.csv", index=False, encoding="utf-8-sig")

    all_stats: list[dict[str, Any]] = []
    all_monthly: list[pd.DataFrame] = []

    print(f"区间 {START}~{END} | 牛/熊/震荡：中证500 月涨跌 ±{abs(BULL_TH):.0f}% 分界\n")

    for item in UNIVERSE:
        base = _cfg(item, START, END)
        daily = _load_daily(base)
        if daily.empty:
            print(f"[跳过] {item['name']}")
            continue
        d0 = str(pd.Timestamp(daily["date"].iloc[0]).date()).replace("-", "")
        d1 = str(pd.Timestamp(daily["date"].iloc[-1]).date()).replace("-", "")
        base = replace(base, start_date=d0, end_date=d1)
        print(f"== {item['name']} ({d0}~{d1})")

        for label, lo, hi in BANDS:
            key = label if label == "基线_止损日禁买" else label
            st, mon = _run_variant(base, daily, key, lo, hi)
            all_stats.append(st)
            all_monthly.append(mon)
            print(
                f"  {key}: 累计={st['total_return_pct']:.1f}% "
                f"夏普={st['sharpe_ratio']:.3f}"
            )

    stats_df = pd.DataFrame(all_stats)
    stats_df.to_csv(_OUT / "full_period_metrics.csv", index=False, encoding="utf-8-sig")

    mon_df = pd.concat(all_monthly, ignore_index=True)
    mon_df = mon_df.merge(mkt_df, on="月份", how="left")
    mon_df.to_csv(_OUT / "monthly_returns.csv", index=False, encoding="utf-8-sig")

    # 相对基线：每月策略收益差（百分点）
    base_mon = mon_df[mon_df["variant"] == "基线_止损日禁买"][
        ["name", "月份", "策略收益%", "市场状态", "中证500月涨%"]
    ].rename(columns={"策略收益%": "基线收益%"})
    gap_rows: list[dict[str, Any]] = []
    for name in mon_df["name"].unique():
        b = base_mon[base_mon["name"] == name].set_index("月份")
        for variant in mon_df["variant"].unique():
            if variant == "基线_止损日禁买":
                continue
            sub = mon_df[(mon_df["name"] == name) & (mon_df["variant"] == variant)].set_index(
                "月份"
            )
            for month in b.index.intersection(sub.index):
                gap_rows.append(
                    {
                        "name": name,
                        "月份": month,
                        "variant": variant,
                        "基线收益%": b.loc[month, "基线收益%"],
                        "variant收益%": sub.loc[month, "策略收益%"],
                        "差距%": float(sub.loc[month, "策略收益%"])
                        - float(b.loc[month, "基线收益%"])
                        if pd.notna(sub.loc[month, "策略收益%"])
                        and pd.notna(b.loc[month, "基线收益%"])
                        else None,
                        "市场状态": b.loc[month, "市场状态"],
                        "中证500月涨%": b.loc[month, "中证500月涨%"],
                    }
                )
    gap_df = pd.DataFrame(gap_rows)
    gap_df.to_csv(_OUT / "monthly_gap_vs_baseline.csv", index=False, encoding="utf-8-sig")

    # 各市场状态下：基线 vs 各区间 vs 个股最优区间
    regime_summary: list[dict[str, Any]] = []
    for name in mon_df["name"].unique():
        best_label = BEST_BAND.get(name, "0.5-1点")
        for regime in ("牛月", "震荡月", "熊月"):
            bm = base_mon[(base_mon["name"] == name) & (base_mon["市场状态"] == regime)]
            if bm.empty:
                continue
            months = set(bm["月份"])
            base_mean = float(bm["基线收益%"].mean())
            row: dict[str, Any] = {
                "name": name,
                "市场状态": regime,
                "月数": len(months),
                "基线均月收益%": round(base_mean, 2),
            }
            for variant in ["0-0.5点", "0.5-1点", "1-1.5点", "1.5-2点", "2-2.5点", best_label]:
                col = f"{variant}_均月%" if variant != best_label else f"最优({variant})_均月%"
                g = gap_df[
                    (gap_df["name"] == name)
                    & (gap_df["variant"] == variant)
                    & (gap_df["月份"].isin(months))
                ]
                if g.empty:
                    row[col] = None
                    row[col.replace("_均月%", "_Δ均%")] = None
                    continue
                var_mean = float(g["variant收益%"].mean())
                row[col] = round(var_mean, 2)
                row[col.replace("_均月%", "_Δ均%")] = round(var_mean - base_mean, 2)
            regime_summary.append(row)

    regime_df = pd.DataFrame(regime_summary)
    regime_df.to_csv(_OUT / "regime_summary.csv", index=False, encoding="utf-8-sig")

    # 全样本：各区间相对基线的月均差距（按市场状态）
    agg_rows: list[dict[str, Any]] = []
    for regime in ("牛月", "震荡月", "熊月"):
        g = gap_df[gap_df["市场状态"] == regime]
        if g.empty:
            continue
        for variant in g["variant"].unique():
            sub = g[g["variant"] == variant]
            agg_rows.append(
                {
                    "市场状态": regime,
                    "variant": variant,
                    "样本月数": len(sub),
                    "平均差距%": round(float(sub["差距%"].mean()), 2),
                    "差距>0占比%": round(float((sub["差距%"] > 0).mean()) * 100, 1),
                    "基线均月%": round(float(sub["基线收益%"].mean()), 2),
                    "variant均月%": round(float(sub["variant收益%"].mean()), 2),
                }
            )
    agg_df = pd.DataFrame(agg_rows)
    agg_df.to_csv(_OUT / "regime_agg_all_symbols.csv", index=False, encoding="utf-8-sig")

    # 个股最优区间：全周期 + 分状态
    best_rows: list[dict[str, Any]] = []
    for name, band in BEST_BAND.items():
        b = stats_df[
            (stats_df["name"] == name) & (stats_df["variant"] == "基线_止损日禁买")
        ]
        v = stats_df[(stats_df["name"] == name) & (stats_df["variant"] == band)]
        if b.empty or v.empty:
            continue
        best_rows.append(
            {
                "name": name,
                "最优区间": band,
                "基线累计%": float(b.iloc[0]["total_return_pct"]),
                "最优累计%": float(v.iloc[0]["total_return_pct"]),
                "d累计%": float(v.iloc[0]["total_return_pct"])
                - float(b.iloc[0]["total_return_pct"]),
                "基线夏普": float(b.iloc[0]["sharpe_ratio"]),
                "最优夏普": float(v.iloc[0]["sharpe_ratio"]),
            }
        )
    best_df = pd.DataFrame(best_rows)
    best_df.to_csv(_OUT / "best_band_full_period.csv", index=False, encoding="utf-8-sig")

    # Markdown 报告
    lines = [
        f"# 止损后再买 · 2020~今 分月 & 牛熊震荡分析",
        "",
        f"- 区间：各标的可用日线（ETF 自上市日起）",
        f"- 市场状态：**中证500** 月涨跌 — 牛月 >+{BULL_TH:.0f}% / 熊月 <-{abs(BEAR_TH):.0f}% / 震荡 [-{abs(BEAR_TH):.0f}%,+{BULL_TH:.0f}%]",
        "- 差距 = 区间策略月收益 − 基线月收益（百分点）",
        "- **仅供研究，不构成投资建议。**",
        "",
        "## 全周期累计（2020~今）",
        "",
        "| 标的 | 基线% | 0-0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-2.5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in stats_df["name"].unique():
        sub = stats_df[stats_df["name"] == name].set_index("variant")
        vals = [name]
        for v in ["基线_止损日禁买", "0-0.5点", "0.5-1点", "1-1.5点", "1.5-2点", "2-2.5点"]:
            vals.append(f"{float(sub.loc[v, 'total_return_pct']):.1f}")
        lines.append("| " + " | ".join(vals) + " |")

    lines += [
        "",
        "## 全市场聚合：各区间 vs 基线 月均差距（所有标的×月份）",
        "",
        "| 市场状态 | 区间 | 样本月 | 基线均月% | 区间均月% | 平均差距% | 区间胜出占比% |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for regime in ("牛月", "震荡月", "熊月"):
        sub = agg_df[agg_df["市场状态"] == regime].sort_values("平均差距%", ascending=False)
        for _, r in sub.iterrows():
            lines.append(
                "| {reg} | {var} | {n} | {base} | {vmean} | {gap:+.2f} | {win:.1f} |".format(
                    reg=r["市场状态"],
                    var=r["variant"],
                    n=int(r["样本月数"]),
                    base=r["基线均月%"],
                    vmean=r["variant均月%"],
                    gap=r["平均差距%"],
                    win=r["差距>0占比%"],
                )
            )

    lines += [
        "",
        "## 个股最优区间 · 全周期",
        "",
        "| 标的 | 最优区间 | 基线累计% | 最优累计% | Δ累计 | 基线夏普 | 最优夏普 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for _, r in best_df.iterrows():
        lines.append(
            "| {name} | {band} | {b:.1f} | {v:.1f} | {d:+.1f} | {bs:.3f} | {vs:.3f} |".format(
                name=r["name"],
                band=r["最优区间"],
                b=r["基线累计%"],
                v=r["最优累计%"],
                d=r["d累计%"],
                bs=r["基线夏普"],
                vs=r["最优夏普"],
            )
        )

    lines += [
        "",
        "## 分市场状态 · 基线 vs 个股最优区间（均月收益%）",
        "",
        "| 标的 | 状态 | 月数 | 基线 | 最优区间 | 最优 | Δ |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for _, r in regime_df.iterrows():
        band = BEST_BAND.get(r["name"], "?")
        opt_col = f"最优({band})_均月%"
        d_col = f"最优({band})_Δ均%"
        opt_v = r.get(opt_col)
        d_v = r.get(d_col)
        lines.append(
            "| {name} | {reg} | {n} | {base} | {band} | {opt} | {d} |".format(
                name=r["name"],
                reg=r["市场状态"],
                n=r["月数"],
                base=r["基线均月收益%"],
                band=band,
                opt=opt_v if pd.notna(opt_v) else "-",
                d=d_v if pd.notna(d_v) else "-",
            )
        )

    lines += ["", f"明细目录：`{_OUT}`", ""]
    report = "\n".join(lines)
    (_OUT / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
