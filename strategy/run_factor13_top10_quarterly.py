"""因子13：Top10 + 年度/季度滚动选股，回测 2026。

  · 年度：用 2025 全年质量带选 Top10（不足则逐级放宽补齐）→ 2026 等权
  · 季度：T 季度末打分 → T+1 季度持有；贯穿 2026（及可选 2021 起）

  python strategy/run_factor13_top10_quarterly.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_SCRIPT = str(Path(__file__).resolve().parent)
if _SCRIPT in sys.path:
    sys.path.remove(_SCRIPT)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import (  # noqa: E402
    _metrics_from_equity,
    load_daily,
    simulate_open_break,
)
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402
from strategy import BacktestConfig  # noqa: E402
from strategy.factor13_fit import enrich_cross_section_scores  # noqa: E402
from strategy.runner import run_open_break_backtest  # noqa: E402

OUT = _MYQUAN / "backtest" / "factor13_top10_quarterly"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
DATA_CACHE = _MYQUAN / "data_cache"
THR = 0.025
TOP_K = 10
WORKERS = 8
MIN_BARS_Q = 35
MIN_BARS_Y = 80
OOS_START, OOS_END = "20260101", "20260825"
CASH = 100_000.0

# 质量带：主带 + 放宽带（补齐到 Top10）
BANDS = [
    dict(min_sharpe=1.0, max_sharpe=2.2, mdd_lo=18, mdd_hi=32, dd_ratio_max=0.55),
    dict(min_sharpe=0.8, max_sharpe=2.5, mdd_lo=15, mdd_hi=35, dd_ratio_max=0.65),
    dict(min_sharpe=0.5, max_sharpe=3.0, mdd_lo=12, mdd_hi=40, dd_ratio_max=0.80),
    dict(min_sharpe=0.3, max_sharpe=3.5, mdd_lo=10, mdd_hi=45, dd_ratio_max=1.00),
]


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _count_trades(holding: np.ndarray) -> int:
    if len(holding) < 2:
        return 0
    return int(np.sum(np.diff(holding.astype(int)) > 0))


def _filter(g: pd.DataFrame, band: dict) -> pd.DataFrame:
    out = g.copy()
    if "dd_ratio" not in out.columns:
        out["dd_ratio"] = out["mdd"] / out["bh_dd"].replace(0, np.nan)
    out = out[
        (out["sharpe"] >= band["min_sharpe"])
        & (out["sharpe"] <= band["max_sharpe"])
        & (out["mdd"] >= band["mdd_lo"])
        & (out["mdd"] <= band["mdd_hi"])
        & (out["dd_ratio"] <= band["dd_ratio_max"])
        & (out["bh_dd"] > 5)
    ]
    return out


def select_top_k(scored: pd.DataFrame, k: int = TOP_K) -> pd.DataFrame:
    """质量带硬过滤，不足则逐级放宽，按 score_quality 取 TopK。"""
    base = enrich_cross_section_scores(scored)
    picked_idx: list = []
    used = set()
    for band in BANDS:
        pool = _filter(base, band)
        pool = pool[~pool["symbol"].isin(used)].sort_values(
            "score_quality", ascending=False
        )
        for _, row in pool.iterrows():
            if len(picked_idx) >= k:
                break
            picked_idx.append(row)
            used.add(row["symbol"])
        if len(picked_idx) >= k:
            break
    if not picked_idx:
        # 最后兜底：不设带，只按 score_quality
        pool = base.sort_values("score_quality", ascending=False).head(k)
        return pool.reset_index(drop=True)
    return pd.DataFrame(picked_idx).head(k).reset_index(drop=True)


def process_symbol_periods(task: dict) -> list[dict]:
    """按年 + 按季输出策略指标（阈值 2.5%）。"""
    symbol = task["symbol"]
    name = task.get("name", "")
    daily = load_daily(symbol)
    if daily is None or daily.empty:
        return []
    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    rows: list[dict] = []

    def one_window(mask, period_id: str, kind: str, min_bars: int):
        idx = np.where(mask)[0]
        if len(idx) < min_bars:
            return
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        i_warm = max(0, i0 - 3)
        eq, hold = simulate_open_break(
            o[i_warm:i1], h[i_warm:i1], l[i_warm:i1], c[i_warm:i1], thr=THR
        )
        off = i0 - i_warm
        eq_y, hold_y, c_y = eq[off:], hold[off:], c[i0:i1]
        if len(eq_y) < min_bars or eq_y[0] <= 0:
            return
        eq_n = eq_y / eq_y[0] * 100_000.0
        met = _metrics_from_equity(eq_n, c_y)
        mdd = float(met["max_drawdown_pct"])
        bh_dd = float(met["bh_max_drawdown_pct"])
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "kind": kind,
                "period": period_id,
                "n_bars": int(i1 - i0),
                "mainboard": 1,
                "ret": met["total_return_pct"],
                "sharpe": met["sharpe_ratio"],
                "mdd": mdd,
                "bh": met["bh_return_pct"],
                "bh_dd": bh_dd,
                "excess": met["excess_return_pct"],
                "dd_improve": met["dd_improve_pct"],
                "dd_ratio": (mdd / bh_dd) if bh_dd > 1e-6 else np.nan,
                "trades": float(_count_trades(hold_y)),
            }
        )

    for y in range(2020, 2027):
        one_window(dates.year == y, str(y), "year", MIN_BARS_Y)
    # quarters
    periods = dates.to_period("Q")
    for p in sorted(set(periods)):
        if p.year < 2020:
            continue
        one_window(periods == p, str(p), "quarter", MIN_BARS_Q)
    return rows


def build_panel(force: bool = False) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "period_panel.parquet"
    if cache.exists() and not force:
        print(f"加载 {cache}")
        return pd.read_parquet(cache)
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    name_map = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    tasks = []
    for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet")):
        sym = fp.name.replace("_daily_qfq.parquet", "")
        if _is_mainboard(sym):
            tasks.append({"symbol": sym, "name": name_map.get(sym, "")})
    print(f"主板 {len(tasks)} 年/季指标...")
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process_symbol_periods, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                rows.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
                print("err", exc)
            if done % 100 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} rows={len(rows)}")
    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    print(f"面板 {df.shape} → {cache}")
    return df


def load_daily_bt(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    parts = []
    for p in [
        UNIV_CACHE / f"{symbol}_daily_qfq.parquet",
        DATA_CACHE / f"{symbol}_daily_qfq.parquet",
    ]:
        if not p.exists():
            continue
        df = pd.read_parquet(p).copy()
        df["date"] = pd.to_datetime(df["date"])
        if df["date"].dt.tz is None:
            df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
        else:
            df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        parts.append(df.dropna(subset=["open", "high", "low", "close"]))
    if not parts:
        return None
    d = pd.concat(parts).sort_values("date").drop_duplicates("date", keep="last")
    warm = pd.Timestamp(start).tz_localize("Asia/Shanghai") - pd.Timedelta(days=40)
    end_ts = pd.Timestamp(end).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    d = d[(d["date"] >= warm) & (d["date"] < end_ts)].reset_index(drop=True)
    return d if len(d) >= 40 else None


def backtest_symbol(symbol: str, name: str, start: str, end: str) -> dict:
    daily = load_daily_bt(symbol, start, end)
    if daily is None:
        return {"ok": 0, "symbol": symbol, "error": "no_data"}
    cfg = BacktestConfig(
        symbol=symbol,
        symbol_name=name or symbol,
        em_symbol=symbol[2:],
        threshold_pct=THR,
        entry_pct=THR,
        stop_pct=THR,
        start_date=start,
        end_date=end,
        initial_cash=CASH,
        factor2_enabled=False,
    )
    result = run_open_break_backtest(cfg, daily)
    eq = result.equity_curve
    if isinstance(eq, pd.DataFrame):
        s = eq["equity"] if "equity" in eq.columns else eq.iloc[:, 0]
    else:
        s = eq
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    nav = pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize()).dropna()
    nav = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))]
    if len(nav) < 2:
        return {"ok": 0, "symbol": symbol, "error": "short_nav"}
    nav = nav / float(nav.iloc[0])
    # BH
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    if getattr(d["date"].dt, "tz", None) is not None:
        d["date"] = d["date"].dt.tz_localize(None)
    d = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(end))]
    c = d["close"].astype(float)
    bh = float(c.iloc[-1] / c.iloc[0] - 1) * 100 if len(c) >= 2 else float("nan")
    bh_dd = float((1 - c / c.cummax()).max()) * 100 if len(c) >= 2 else float("nan")
    rets = nav.pct_change().dropna()
    tot = (float(nav.iloc[-1]) - 1) * 100
    vol = float(rets.std() * np.sqrt(252)) if len(rets) else 0.0
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    ann = float(nav.iloc[-1]) ** (1 / years) - 1 if float(nav.iloc[-1]) > 0 else 0.0
    sharpe = ann / vol if vol > 1e-12 else 0.0
    mdd = float((1 - nav / nav.cummax()).max()) * 100
    return {
        "ok": 1,
        "symbol": symbol,
        "name": name,
        "ret": tot,
        "bh": bh,
        "excess": tot - bh if np.isfinite(bh) else np.nan,
        "mdd": mdd,
        "bh_dd": bh_dd,
        "sharpe": sharpe,
        "nav": nav,
    }


def equal_weight(navs: dict[str, pd.Series]) -> pd.Series:
    if not navs:
        return pd.Series(dtype=float)
    df = pd.concat(navs, axis=1).sort_index().ffill()
    rets = df.pct_change()
    port = rets.mean(axis=1, skipna=True).fillna(0.0)
    nav = (1.0 + port).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 2:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    rets = nav.pct_change().dropna()
    tot = (float(nav.iloc[-1]) - 1) * 100
    vol = float(rets.std() * np.sqrt(252)) if len(rets) else 0.0
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    ann = float(nav.iloc[-1]) ** (1 / years) - 1 if float(nav.iloc[-1]) > 0 else 0.0
    return {
        "ret": tot,
        "mdd": float((1 - nav / nav.cummax()).max()) * 100,
        "sharpe": (ann / vol) if vol > 1e-12 else 0.0,
    }


def run_yearly_2026(panel: pd.DataFrame) -> dict:
    y = panel[(panel["kind"] == "year") & (panel["period"] == "2025")].copy()
    picks = select_top_k(y, TOP_K)
    picks.to_csv(OUT / "yearly_picks_2025_for_2026.csv", index=False, float_format="%.4f")
    print(f"\n=== 年度选股 Top{TOP_K}（2025→2026）N={len(picks)} ===")
    cols = [c for c in ("symbol", "name", "sharpe", "mdd", "dd_ratio", "excess", "score_quality") if c in picks.columns]
    print(picks[cols].to_string(index=False))

    rows = []
    navs = {}
    for _, r in picks.iterrows():
        res = backtest_symbol(str(r["symbol"]), str(r.get("name") or ""), OOS_START, OOS_END)
        if not res.get("ok"):
            print(" fail", r["symbol"], res.get("error"))
            continue
        rows.append({k: res[k] for k in ("symbol", "name", "ret", "bh", "excess", "mdd", "bh_dd", "sharpe")})
        navs[res["symbol"]] = res["nav"]
        print(
            f"  {res['symbol']} {res['name']}: 策略={res['ret']:+.1f}% 持有={res['bh']:+.1f}% "
            f"超额={res['excess']:+.1f}% 回撤={res['mdd']:.1f}%"
        )
    port = equal_weight(navs)
    st = nav_stats(port)
    pd.DataFrame(rows).to_csv(OUT / "yearly_2026_stocks.csv", index=False, float_format="%.4f")
    port.to_csv(OUT / "yearly_2026_port_nav.csv", header=["nav"])
    print(f"年度Top10组合: {st['ret']:.1f}% 回撤{st['mdd']:.1f}% 夏普{st['sharpe']:.2f}")
    return {"picks": picks, "stocks": rows, "port": st, "nav": port}


def quarter_hold_range(period: str) -> tuple[str, str]:
    """'2025Q4' 选股 → 持有 2026Q1。"""
    p = pd.Period(period, freq="Q")
    nxt = p + 1
    start = nxt.start_time.strftime("%Y%m%d")
    end = nxt.end_time.strftime("%Y%m%d")
    # 截到数据末日
    end = min(end, OOS_END)
    return start, end


def run_quarterly(panel: pd.DataFrame, *, from_year: int = 2025) -> dict:
    qpanel = panel[panel["kind"] == "quarter"].copy()
    periods = sorted(qpanel["period"].unique())
    # 只用能映射到下一季且下一季与 2026 有交集的选股季
    records = []
    port_navs = []
    for per in periods:
        p = pd.Period(per, freq="Q")
        if p.year < from_year - 1:
            continue
        hold_start, hold_end = quarter_hold_range(per)
        if hold_start > OOS_END:
            continue
        if hold_end < "20260101" and from_year >= 2025:
            # 主报告聚焦 2026；仍可从 2025Q4 起
            if hold_end < "20260101":
                continue
        scored = qpanel[qpanel["period"] == per].copy()
        picks = select_top_k(scored, TOP_K)
        if picks.empty:
            continue
        # 单季回测各票再等权
        navs = {}
        stock_rows = []
        for _, r in picks.iterrows():
            res = backtest_symbol(str(r["symbol"]), str(r.get("name") or ""), hold_start, hold_end)
            if not res.get("ok"):
                continue
            navs[res["symbol"]] = res["nav"]
            stock_rows.append(
                {
                    "select_period": per,
                    "hold_start": hold_start,
                    "hold_end": hold_end,
                    "symbol": res["symbol"],
                    "name": res["name"],
                    "ret": res["ret"],
                    "bh": res["bh"],
                    "excess": res["excess"],
                    "mdd": res["mdd"],
                }
            )
        if not navs:
            continue
        qnav = equal_weight(navs)
        st = nav_stats(qnav)
        records.append(
            {
                "select_period": per,
                "hold_start": hold_start,
                "hold_end": hold_end,
                "n_picks": len(navs),
                "symbols": ",".join(navs.keys()),
                "ret": st["ret"],
                "mdd": st["mdd"],
                "sharpe": st["sharpe"],
                "med_ret": float(pd.Series([x["ret"] for x in stock_rows]).median()),
            }
        )
        # 归一后接到组合：用收益链
        port_navs.append(qnav)
        print(
            f"  {per}→[{hold_start}-{hold_end}] N={len(navs)} "
            f"等权={st['ret']:+.1f}% 中位={records[-1]['med_ret']:+.1f}% 回撤={st['mdd']:.1f}%"
        )
        pd.DataFrame(stock_rows).to_csv(
            OUT / f"quarter_{per}_stocks.csv", index=False, float_format="%.4f"
        )

    # 拼接季度净值（收益串联）
    stitched = None
    for qnav in port_navs:
        r = qnav.pct_change().fillna(0.0)
        if stitched is None:
            stitched = (1.0 + r).cumprod()
            stitched.iloc[0] = 1.0
        else:
            # 新季度接在上一季末日之后
            base = float(stitched.iloc[-1])
            seg = (1.0 + r).cumprod() * base
            # 去重首日
            seg = seg[seg.index > stitched.index[-1]]
            stitched = pd.concat([stitched, seg])
    st_all = nav_stats(stitched) if stitched is not None and len(stitched) else {}
    wf = pd.DataFrame(records)
    wf.to_csv(OUT / "quarterly_walkforward.csv", index=False, float_format="%.4f")
    if stitched is not None:
        stitched.to_csv(OUT / "quarterly_2026_port_nav.csv", header=["nav"])
    return {"wf": wf, "port": st_all, "nav": stitched}


def write_html(yearly: dict, quarterly: dict) -> None:
    ys = yearly["stocks"]
    yp = yearly["port"]
    qwf = quarterly["wf"]
    qp = quarterly["port"]
    y_rows = "".join(
        f"<tr><td>{r['name']}</td><td>{r['symbol']}</td><td>{r['ret']:.1f}</td>"
        f"<td>{r['bh']:.1f}</td><td>{r['excess']:.1f}</td><td>{r['mdd']:.1f}</td></tr>"
        for r in ys
    )
    q_rows = "".join(
        f"<tr><td>{r.select_period}</td><td>{r.hold_start}→{r.hold_end}</td>"
        f"<td>{int(r.n_picks)}</td><td>{r.ret:.1f}</td><td>{r.med_ret:.1f}</td>"
        f"<td>{r.mdd:.1f}</td></tr>"
        for r in qwf.itertuples()
    ) if len(qwf) else ""
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>
<title>因子13 Top10 · 年度 vs 季度 · 2026</title>
<style>
body{{font-family:PingFang SC,Helvetica,sans-serif;background:#0f1115;color:#e8eaed;padding:28px}}
.wrap{{max-width:1000px;margin:0 auto}}.meta{{color:#9aa3b2}}
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.stat{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:14px}}
.stat .v{{font-size:1.5rem;font-weight:650;color:#3dd68c}}.stat .l{{color:#9aa3b2;font-size:.85rem}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:14px;margin:14px 0}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
th,td{{padding:7px 8px;border-bottom:1px solid #2a2f3a;text-align:right}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}} th{{color:#9aa3b2}}
.callout{{border-left:3px solid #3d8bfd;padding:10px 14px;background:#171a21;margin:12px 0}}
</style></head><body><div class="wrap">
<h1>因子13 · Top10 年度 vs 季度滚动 · 2026回测</h1>
<p class="meta">开盘±2.5%仅止损 · 质量带选股不足则放宽补齐到10 · 非投资建议</p>
<div class="callout">
<b>年度：</b>用2025全年打分，2026整段持有等权。<br/>
<b>季度：</b>上一季打分，下一季换仓（2025Q4→2026Q1→Q2→Q3…）。
</div>
<div class="stats">
  <div class="stat"><div class="l">年度 Top10 组合 2026</div>
    <div class="v">{yp.get('ret', float('nan')):.1f}%</div>
    <div class="l">回撤 {yp.get('mdd', float('nan')):.1f}% · 夏普 {yp.get('sharpe', float('nan')):.2f} · N={len(ys)}</div>
  </div>
  <div class="stat"><div class="l">季度滚动拼接 2026</div>
    <div class="v">{qp.get('ret', float('nan')):.1f}%</div>
    <div class="l">回撤 {qp.get('mdd', float('nan')):.1f}% · 夏普 {qp.get('sharpe', float('nan')):.2f}</div>
  </div>
</div>
<div class="card"><h3>年度入选 · 2026单票</h3>
<table><thead><tr><th>名称</th><th>代码</th><th>策略%</th><th>持有%</th><th>超额</th><th>回撤%</th></tr></thead>
<tbody>{y_rows}</tbody></table>
<p class="meta">等权均 {np.mean([r['ret'] for r in ys]):.1f}% · 中位 {np.median([r['ret'] for r in ys]):.1f}%</p>
</div>
<div class="card"><h3>季度滚动各季</h3>
<table><thead><tr><th>选股季</th><th>持有区间</th><th>N</th><th>等权%</th><th>中位%</th><th>回撤%</th></tr></thead>
<tbody>{q_rows}</tbody></table>
</div>
</div></body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = build_panel(force=False)
    panel = panel[panel["mainboard"] == 1].copy()

    print("\n######## 年度 Top10 → 2026 ########")
    yearly = run_yearly_2026(panel)

    print("\n######## 季度滚动 → 2026 ########")
    quarterly = run_quarterly(panel, from_year=2025)

    write_html(yearly, quarterly)
    meta = {
        "top_k": TOP_K,
        "threshold": THR,
        "bands": BANDS,
        "yearly_port": yearly["port"],
        "quarterly_port": quarterly["port"],
        "yearly_n": len(yearly["stocks"]),
        "quarterly_wf": quarterly["wf"].to_dict(orient="records") if len(quarterly["wf"]) else [],
    }
    (OUT / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    # 更新默认 TopK
    rule_path = _MYQUAN / "backtest" / "factor13_quality_opt" / "best_rule.json"
    if rule_path.exists():
        rule = json.loads(rule_path.read_text(encoding="utf-8"))
        rule["top_k"] = TOP_K
        rule["label"] = (
            f"±2.5% · score_quality Top{TOP_K} · 夏普[1.0,2.2](+放宽补齐) · "
            f"回撤带+dd_ratio · 支持季度滚动"
        )
        rule["fill_bands"] = BANDS
        rule_path.write_text(json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8")
        (_MYQUAN / "backtest" / "factor13_walkforward" / "best_rule.json").write_text(
            json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"\n报告 → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
