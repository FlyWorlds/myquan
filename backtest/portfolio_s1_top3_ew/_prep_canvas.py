"""Prepare JSON payload for portfolio canvas visualization."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
eq = pd.read_csv(HERE / "equity.csv", parse_dates=["date"]).set_index("date").sort_index()
hold = pd.read_csv(HERE / "daily_holdings.csv", parse_dates=["date"])
year = pd.read_csv(HERE / "yearly.csv")
tr = pd.read_csv(HERE / "trades.csv", parse_dates=["date"])

peak = eq["strategy"].cummax()
dd = (1 - eq["strategy"] / peak) * 100
m = eq.resample("ME").last().dropna()
if eq.index[0] not in m.index:
    m.loc[eq.index[0]] = eq.iloc[0]
m = m.sort_index()
dd_m = pd.Series({d: float(dd.loc[:d].iloc[-1]) for d in m.index})

hm = hold.set_index("date")["n_hold"].resample("ME").mean()
dist = hold["n_hold"].value_counts().sort_index()
buys = tr[tr.side == "buy"]
by_year = buys.groupby(buys.date.dt.year).size()
by_name = buys.groupby("name").size()
moves = hold[
    (hold["entered"].fillna("").astype(str).str.len() > 0)
    | (hold["exited"].fillna("").astype(str).str.len() > 0)
].tail(18)

s0, s1 = float(eq["strategy"].iloc[0]), float(eq["strategy"].iloc[-1])
b0, b1 = float(eq["bh_equal"].iloc[0]), float(eq["bh_equal"].iloc[-1])
tot = (s1 / s0 - 1) * 100
bh = (b1 / b0 - 1) * 100
years = (eq.index[-1] - eq.index[0]).days / 365.25
ann = ((1 + tot / 100) ** (1 / years) - 1) * 100
mdd = float(dd.max())
mdd_date = str(dd.idxmax().date())

cats = [d.strftime("%Y-%m") for d in m.index]
data = {
    "meta": {
        "names": "禾盛新材 / 凯盛科技 / 东材科技",
        "range": "2020-01-02 → 2026-08-11",
        "total": round(tot, 2),
        "bh": round(bh, 2),
        "excess": round(tot - bh, 2),
        "ann": round(ann, 2),
        "mdd": round(mdd, 2),
        "mdd_date": mdd_date,
        "end_equity": round(s1, 2),
        "hold_pct": round((hold.n_hold > 0).mean() * 100, 1),
        "avg_hold": round(float(hold.n_hold.mean()), 2),
        "n_buys": int((tr.side == "buy").sum()),
        "n_sells": int((tr.side == "sell").sum()),
    },
    "equity_cats": cats,
    "equity_strat": [round(float(x) / 10000, 2) for x in m["strategy"]],
    "equity_bh": [round(float(x) / 10000, 2) for x in m["bh_equal"]],
    "dd": [round(float(dd_m.loc[d]), 2) for d in m.index],
    "year_cats": [str(int(r["年份"])) for _, r in year.iterrows()],
    "year_strat": [float(r["组合策略%"]) for _, r in year.iterrows()],
    "year_bh": [float(r["等权持有%"]) for _, r in year.iterrows()],
    "year_excess": [float(r["超额%"]) for _, r in year.iterrows()],
    "year_dd": [float(r["策略回撤%"]) for _, r in year.iterrows()],
    "year_rows": [
        {
            "年份": str(int(r["年份"])),
            "组合策略%": f"{r['组合策略%']:+.1f}",
            "等权持有%": f"{r['等权持有%']:+.1f}",
            "超额%": f"{r['超额%']:+.1f}",
            "策略回撤%": f"{r['策略回撤%']:.1f}",
            "持有回撤%": f"{r['持有回撤%']:.1f}",
            "_tone": "success" if r["超额%"] > 0 else "danger",
        }
        for _, r in year.iterrows()
    ],
    "hold_dist_cats": [f"{int(k)}票" for k in dist.index],
    "hold_dist_vals": [int(v) for v in dist.values],
    "hold_cats": [d.strftime("%Y-%m") for d in hm.index],
    "hold_avg": [round(float(v), 2) for v in hm.values],
    "buy_year_cats": [str(k) for k in by_year.index],
    "buy_year_vals": [int(v) for v in by_year.values],
    "buy_name_cats": list(by_name.index),
    "buy_name_vals": [int(v) for v in by_name.values],
    "recent": [
        {
            "日期": r.date.strftime("%Y-%m-%d"),
            "持仓数": int(r.n_hold),
            "持仓": "" if pd.isna(r.names) else str(r.names).replace("|", " / "),
            "买入": "" if pd.isna(r.entered) else str(r.entered).replace("|", " / "),
            "卖出": "" if pd.isna(r.exited) else str(r.exited).replace("|", " / "),
        }
        for _, r in moves.iterrows()
    ],
}
(HERE / "_canvas_payload.json").write_text(
    json.dumps(data, ensure_ascii=False), encoding="utf-8"
)
print("months", len(cats), "bytes", (HERE / "_canvas_payload.json").stat().st_size)
