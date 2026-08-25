"""因子13：2020–2025 风格孪生选股 → 2026 策略一基线样本外回测。

  python strategy/run_factor13_twin.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy import BacktestConfig  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.factor13_twin import (  # noqa: E402
    DEFAULT_PARAMS,
    factor13_signal,
)
from strategy.runner import run_open_break_backtest  # noqa: E402

OUT = _MYQUAN / "backtest" / "factor13_twin"
UNIV_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
DATA_CACHE = _MYQUAN / "data_cache"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"

FIT_START = "2020-01-01"
FIT_END = "2025-12-31"
OOS_START = "20260101"
OOS_END = "20260825"
CASH = 100_000.0
TOP_K = 12
THRESHOLD = 0.025
SEEDS = ("sh600330", "sh600552")


def load_daily(symbol: str) -> pd.DataFrame | None:
    paths = [
        UNIV_CACHE / f"{symbol}_daily_qfq.parquet",
        DATA_CACHE / f"{symbol}_daily_qfq.parquet",
    ]
    parts: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty or "date" not in df.columns:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
        else:
            df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        df["symbol"] = symbol
        parts.append(df)
    if not parts:
        return None
    merged = (
        pd.concat(parts, ignore_index=True)
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    return merged if len(merged) >= 80 else None


def load_names() -> dict[str, str]:
    if not META_CSV.exists():
        return {}
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name", "code"])
    out: dict[str, str] = {}
    for _, r in meta.iterrows():
        sym = str(r["symbol"]).lower()
        out[sym] = str(r["name"])
        code = str(r["code"]).zfill(6)
        out[code] = str(r["name"])
    # 种子兜底
    out.setdefault("sh600330", "天通股份")
    out.setdefault("sh600552", "凯盛科技")
    return out


def em_code(symbol: str) -> str:
    s = str(symbol).lower()
    return s[2:] if s.startswith(("sh", "sz")) else s


def slice_oos(daily: pd.DataFrame) -> pd.DataFrame:
    start = pd.Timestamp(OOS_START).tz_localize("Asia/Shanghai")
    end = pd.Timestamp(OOS_END).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    # 预热约 40 个自然日，供阴/小阳与双阳过滤；成交与收益仍从 OOS_START 起算
    warm = start - pd.Timedelta(days=40)
    out = daily[(daily["date"] >= warm) & (daily["date"] < end)].copy()
    return out.reset_index(drop=True)


def _nav_from_oos(nav: pd.Series) -> pd.Series:
    """权益曲线截到样本外起点再归一（避免预热段交易污染收益）。"""
    if nav is None or len(nav) == 0:
        return pd.Series(dtype=float)
    s = nav.copy()
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[s.index >= pd.Timestamp(OOS_START)]
    s = s[s.index <= pd.Timestamp(OOS_END)]
    if len(s) < 2:
        return pd.Series(dtype=float)
    return s / float(s.iloc[0])


def run_one(symbol: str, name: str, daily: pd.DataFrame) -> dict:
    d = slice_oos(daily)
    if len(d) < 40:
        return {"ok": 0, "error": "oos bars insufficient"}
    thr = 0.03 if symbol.lower() == "sh600330" else THRESHOLD
    cfg = BacktestConfig(
        symbol=symbol,
        symbol_name=name or symbol,
        em_symbol=em_code(symbol),
        threshold_pct=thr,
        entry_pct=thr,
        stop_pct=thr,
        start_date=OOS_START,
        end_date=OOS_END,
        initial_cash=CASH,
        factor2_enabled=False,
    )
    try:
        result = run_open_break_backtest(cfg, d)
    except Exception as exc:  # noqa: BLE001
        return {"ok": 0, "error": str(exc)}
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        nav_raw = pd.Series(dtype=float)
    else:
        if isinstance(eq, pd.DataFrame):
            col = "equity" if "equity" in eq.columns else eq.columns[0]
            s = eq[col]
        else:
            s = eq
        idx = pd.to_datetime(s.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        nav_raw = pd.Series(
            pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize()
        ).dropna()

    nav = _nav_from_oos(nav_raw)
    if len(nav) < 2:
        return {"ok": 0, "error": "oos nav empty"}
    stats = window_stats(nav)

    dd = d.copy()
    dd["date"] = pd.to_datetime(dd["date"])
    if getattr(dd["date"].dt, "tz", None) is not None:
        dd["date"] = dd["date"].dt.tz_localize(None)
    oos = dd[
        (dd["date"] >= pd.Timestamp(OOS_START))
        & (dd["date"] <= pd.Timestamp(OOS_END))
    ]
    if len(oos) >= 2:
        bh = float(oos["close"].iloc[-1] / oos["close"].iloc[0] - 1.0) * 100.0
        bh_dd = float((oos["close"] / oos["close"].cummax() - 1.0).min()) * 100.0
    else:
        bh, bh_dd = float("nan"), float("nan")

    # 闭环：仅统计 OOS 内平仓
    trades = float(metric(result.metrics_df, "closed_trade_count"))
    tdf = getattr(result, "trades_df", None)
    if tdf is not None and not getattr(tdf, "empty", True):
        tcol = next(
            (c for c in ("exit_time", "exit_date", "timestamp", "date") if c in tdf.columns),
            None,
        )
        if tcol is not None:
            ts = pd.to_datetime(tdf[tcol])
            if getattr(ts.dt, "tz", None) is not None:
                ts = ts.dt.tz_localize(None)
            mask = (ts >= pd.Timestamp(OOS_START)) & (ts <= pd.Timestamp(OOS_END))
            trades = float(mask.sum())

    ret = float(stats["ret_pct"])
    return {
        "ok": 1,
        "error": "",
        "ret_pct": ret,
        "mdd_pct": float(stats["mdd_pct"]),
        "sharpe": float(stats["sharpe"]),
        "trades": trades,
        "bh_pct": bh,
        "bh_dd_pct": bh_dd,
        "excess_pct": ret - bh if np.isfinite(bh) else float("nan"),
        "nav": nav,
    }


def equal_weight_nav(navs: dict[str, pd.Series]) -> pd.Series:
    df = pd.concat(navs, axis=1).sort_index().ffill()
    rets = df.pct_change()
    port = rets.mean(axis=1, skipna=True).fillna(0.0)
    nav = (1.0 + port).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def window_stats(nav: pd.Series) -> dict[str, float]:
    s = nav.dropna().astype(float)
    if len(s) < 5:
        return {"ret_pct": float("nan"), "mdd_pct": float("nan"), "sharpe": float("nan")}
    tot = float(s.iloc[-1] / s.iloc[0] - 1.0)
    rets = s.pct_change().dropna()
    vol = float(rets.std() * np.sqrt(252)) if len(rets) else 0.0
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    mdd = float((1.0 - s / s.cummax()).max())
    return {"ret_pct": tot * 100.0, "mdd_pct": mdd * 100.0, "sharpe": sharpe}


def write_html(report: dict, path: Path) -> None:
    picks = pd.DataFrame(report["picks_table"])
    oos = pd.DataFrame(report["oos_table"])
    rows_pick = "".join(
        f"<tr><td>{r['rank']}</td><td>{r['symbol']}</td><td>{r['name']}</td>"
        f"<td>{r['dist']:.3f}</td><td>{r['oc_ge_2p5']*100:.1f}</td>"
        f"<td>{r['break_hit']*100:.1f}</td><td>{r['amp_mean']*100:.2f}</td>"
        f"<td>{r['vol_ann']*100:.1f}</td></tr>"
        for _, r in picks.iterrows()
    )
    rows_oos = "".join(
        f"<tr class='{'seed' if r['group']=='seed' else ''}'>"
        f"<td>{r['group']}</td><td>{r['symbol']}</td><td>{r['name']}</td>"
        f"<td>{r['ret_pct']:.1f}</td><td>{r['bh_pct']:.1f}</td>"
        f"<td>{r['excess_pct']:.1f}</td><td>{r['mdd_pct']:.1f}</td>"
        f"<td>{r['bh_dd_pct']:.1f}</td><td>{r['sharpe']:.2f}</td>"
        f"<td>{int(r['trades'])}</td></tr>"
        for _, r in oos.iterrows()
    )
    port = report["portfolio"]
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>因子13 风格孪生 · 2026 OOS</title>
<style>
body{{font-family:PingFang SC,Helvetica,sans-serif;background:#0f1115;color:#e8eaed;padding:28px;}}
.wrap{{max-width:1100px;margin:0 auto}}
h1{{font-size:1.6rem;margin:0 0 6px}} .meta{{color:#9aa3b2;margin-bottom:18px}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:14px 16px;margin:14px 0}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.stat{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:12px}}
.stat .v{{font-size:1.4rem;font-weight:650;color:#3dd68c}}
.stat .l{{color:#9aa3b2;font-size:.8rem}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
th,td{{padding:7px 8px;border-bottom:1px solid #2a2f3a;text-align:right}}
th:nth-child(1),th:nth-child(2),th:nth-child(3),td:nth-child(1),td:nth-child(2),td:nth-child(3){{text-align:left}}
th{{color:#9aa3b2;font-weight:550}}
tr.seed td{{color:#3d8bfd}}
.callout{{border-left:3px solid #3dd68c;padding:10px 14px;background:#171a21;margin:12px 0}}
</style></head><body><div class="wrap">
<h1>因子13 · 天通/凯盛风格孪生选股</h1>
<p class="meta">拟合 {FIT_START}→{FIT_END}（不含2026）选股 · 样本外 {OOS_START}→{OOS_END} · 策略一基线仅止损 · 非投资建议</p>
<div class="callout"><b>风格结论：</b>种子票相对全市场最突出的是「大开大合」(|C/O|≥2.5% 约 P73)
与开盘±2.5%触及率，其次是大涨跌日频次；不是极致动量也不是低波。</div>
<div class="stats">
  <div class="stat"><div class="v">{port['twins_ew']['ret_pct']:.1f}%</div><div class="l">孪生等权策略 2026</div></div>
  <div class="stat"><div class="v">{port['seeds_ew']['ret_pct']:.1f}%</div><div class="l">种子等权策略 2026</div></div>
  <div class="stat"><div class="v">{port['twins_ew']['mdd_pct']:.1f}%</div><div class="l">孪生等权最大回撤</div></div>
  <div class="stat"><div class="v">{port['twins_bh_med']:.1f}%</div><div class="l">孪生持有收益中位</div></div>
</div>
<div class="card"><h3>拟合窗选出的主板孪生 Top{TOP_K}</h3>
<table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>距离</th><th>大开大合%</th><th>突破触及%</th><th>震幅%</th><th>年化波%</th></tr></thead>
<tbody>{rows_pick}</tbody></table></div>
<div class="card"><h3>2026 单票回测（策略 vs 持有）</h3>
<table><thead><tr><th>组</th><th>代码</th><th>名称</th><th>策略%</th><th>持有%</th><th>超额</th><th>策略回撤</th><th>持有回撤</th><th>夏普</th><th>闭环</th></tr></thead>
<tbody>{rows_oos}</tbody></table></div>
<p class="meta">产物目录 {OUT}</p>
</div></body></html>"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = load_names()
    print("加载日线...")
    dailies: dict[str, pd.DataFrame] = {}
    for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet")):
        sym = fp.name.replace("_daily_qfq.parquet", "")
        df = load_daily(sym)
        if df is not None:
            dailies[sym] = df
    # 确保种子
    for s in SEEDS:
        if s not in dailies:
            df = load_daily(s)
            if df is not None:
                dailies[s] = df
    print(f"universe {len(dailies)}")

    params = {
        **DEFAULT_PARAMS,
        "fit_start": FIT_START,
        "fit_end": FIT_END,
        "top_k": TOP_K,
        "mainboard_only": True,
        "seeds": SEEDS,
    }
    sig = factor13_signal(dailies=dailies, params=params, names=names)
    scored: pd.DataFrame = sig["scored"]
    picks: pd.DataFrame = sig["picks"]
    seeds_df: pd.DataFrame = sig["seeds"]

    scored_out = scored.reset_index()
    scored_out["name"] = scored_out["symbol"].map(lambda s: names.get(s, ""))
    scored_out.to_csv(OUT / "scored_2020_2025.csv", index=False, float_format="%.6f")

    picks_table = []
    for i, (sym, r) in enumerate(picks.iterrows(), 1):
        picks_table.append(
            {
                "rank": i,
                "symbol": sym,
                "name": names.get(sym, ""),
                "dist": float(r["dist"]),
                "sim_score": float(r["sim_score"]),
                "amp_mean": float(r["amp_mean"]),
                "oc_ge_2p5": float(r["oc_ge_2p5"]),
                "break_hit": float(r["break_hit"]),
                "vol_ann": float(r["vol_ann"]),
                "big_move_freq": float(r["big_move_freq"]),
                "yr_range_med": float(r["yr_range_med"]),
            }
        )
    pd.DataFrame(picks_table).to_csv(OUT / "picks_top12.csv", index=False)

    print("\n=== 因子13 主板孪生 Top12（仅 2020-2025）===")
    print(pd.DataFrame(picks_table)[["rank", "symbol", "name", "dist", "oc_ge_2p5", "break_hit"]].to_string(index=False))

    run_list = [(s, "seed") for s in SEEDS] + [(s, "twin") for s in picks.index.tolist()]
    oos_rows = []
    navs_seed: dict[str, pd.Series] = {}
    navs_twin: dict[str, pd.Series] = {}
    print(f"\n=== 2026 OOS 回测 ({OOS_START}→{OOS_END}) ===")
    for sym, group in run_list:
        daily = dailies[sym] if sym in dailies else load_daily(sym)
        name = names.get(sym, sym)
        if daily is None:
            print(f"  skip {sym} no data")
            continue
        res = run_one(sym, name, daily)
        if not res.get("ok"):
            print(f"  fail {sym}: {res.get('error')}")
            continue
        row = {
            "group": group,
            "symbol": sym,
            "name": name,
            "ret_pct": res["ret_pct"],
            "bh_pct": res["bh_pct"],
            "excess_pct": res["excess_pct"],
            "mdd_pct": res["mdd_pct"],
            "bh_dd_pct": res["bh_dd_pct"],
            "sharpe": res["sharpe"],
            "trades": res["trades"],
        }
        oos_rows.append(row)
        nav = res["nav"]
        if len(nav):
            # 归一
            n0 = float(nav.iloc[0])
            nav_n = nav / n0 if n0 else nav
            if group == "seed":
                navs_seed[sym] = nav_n
            else:
                navs_twin[sym] = nav_n
        print(
            f"  {group:4s} {sym} {name:8s} 策略={res['ret_pct']:+7.1f}% "
            f"持有={res['bh_pct']:+7.1f}% 超额={res['excess_pct']:+7.1f}% "
            f"回撤={res['mdd_pct']:.1f}%/{res['bh_dd_pct']:.1f}%"
        )

    oos_df = pd.DataFrame(oos_rows)
    oos_df.to_csv(OUT / "oos_2026.csv", index=False, float_format="%.4f")

    port = {
        "seeds_ew": window_stats(equal_weight_nav(navs_seed)) if navs_seed else {},
        "twins_ew": window_stats(equal_weight_nav(navs_twin)) if navs_twin else {},
        "twins_bh_med": float(oos_df.loc[oos_df.group == "twin", "bh_pct"].median())
        if len(oos_df)
        else float("nan"),
        "twins_ret_med": float(oos_df.loc[oos_df.group == "twin", "ret_pct"].median())
        if len(oos_df)
        else float("nan"),
        "twins_beat_bh": int((oos_df.loc[oos_df.group == "twin", "excess_pct"] > 0).sum())
        if len(oos_df)
        else 0,
        "twins_n": int((oos_df.group == "twin").sum()) if len(oos_df) else 0,
    }
    print("\n=== 组合 ===")
    print("种子等权", port["seeds_ew"])
    print("孪生等权", port["twins_ew"])
    print(
        f"孪生中位策略 {port['twins_ret_med']:.1f}% / 持有中位 {port['twins_bh_med']:.1f}% "
        f"/ 跑赢持有 {port['twins_beat_bh']}/{port['twins_n']}"
    )

    report = {
        "fit": {"start": FIT_START, "end": FIT_END, "top_k": TOP_K},
        "oos": {"start": OOS_START, "end": OOS_END},
        "params": params,
        "picks_table": picks_table,
        "oos_table": oos_rows,
        "portfolio": port,
        "seed_features": seeds_df.reset_index().to_dict(orient="records"),
    }
    (OUT / "meta.json").write_text(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("picks_table", "oos_table", "seed_features")},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    write_html(report, OUT / "report.html")

    # markdown
    md = [
        "# 因子13 · 天通/凯盛风格孪生选股报告",
        "",
        f"- 拟合窗：**{FIT_START} → {FIT_END}**（选股**不用**2026）",
        f"- 样本外：策略一基线仅止损，**{OOS_START} → {OOS_END}**",
        "- 池：中证500/1000 日线缓存；主板 60/00；Top12",
        "- 研究用途，非投资建议",
        "",
        "## 1. 风格发现",
        "",
        "相对全市场，天通+凯盛最突出的不是极致动量，而是：",
        "1. **大开大合**：|收盘/开盘|≥2.5% 日占比约 **P73**",
        "2. **开盘突破可交易**：日内触及开盘±2.5% 约 **P66**",
        "3. **大涨跌日频次** 约 P68；震幅/波动约 P62（中等偏高）",
        "",
        "## 2. 选出的主板孪生",
        "",
        "|#|代码|名称|距离|大开大合%|突破触及%|震幅%|年化波%|",
        "|--:|---|---|--:|--:|--:|--:|--:|",
    ]
    for r in picks_table:
        md.append(
            f"|{r['rank']}|{r['symbol']}|{r['name']}|{r['dist']:.3f}|"
            f"{r['oc_ge_2p5']*100:.1f}|{r['break_hit']*100:.1f}|"
            f"{r['amp_mean']*100:.2f}|{r['vol_ann']*100:.1f}|"
        )
    md += [
        "",
        "## 3. 2026 样本外",
        "",
        f"- 孪生等权策略：**{port['twins_ew'].get('ret_pct', float('nan')):.1f}%**，"
        f"回撤 {port['twins_ew'].get('mdd_pct', float('nan')):.1f}%",
        f"- 种子等权策略：**{port['seeds_ew'].get('ret_pct', float('nan')):.1f}%**，"
        f"回撤 {port['seeds_ew'].get('mdd_pct', float('nan')):.1f}%",
        f"- 孪生策略中位 {port['twins_ret_med']:.1f}% / 持有中位 {port['twins_bh_med']:.1f}% / "
        f"跑赢持有 {port['twins_beat_bh']}/{port['twins_n']}",
        "",
        "|组|代码|名称|策略%|持有%|超额|策略回撤|持有回撤|夏普|",
        "|---|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for r in oos_rows:
        md.append(
            f"|{r['group']}|{r['symbol']}|{r['name']}|{r['ret_pct']:.1f}|"
            f"{r['bh_pct']:.1f}|{r['excess_pct']:.1f}|{r['mdd_pct']:.1f}|"
            f"{r['bh_dd_pct']:.1f}|{r['sharpe']:.2f}|"
        )
    md += [
        "",
        "## 4. 结论",
        "",
        "- 因子13 抓的是「**大开大合 + 开盘突破亲和**」中盘风格，不是单纯动量排名。",
        "- 选股严格锁在 2020–2025；2026 仅作样本外检验。",
        "- 若孪生组合 2026 仍具备「熊段回撤好于持有、牛段或跑不赢持有」形态，则风格迁移成立。",
        "",
        f"HTML：`{OUT / 'report.html'}`",
    ]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nCSV/HTML/MD -> {OUT}")


if __name__ == "__main__":
    main()
