"""因子13·熊市盾牌 v3：2020–2025 定个股 thr → 软牛市打分选股 → 回测 2025–2026 / 2026。

  python strategy/run_factor13_bear_shield_v3.py
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
_SCRIPT = str(Path(__file__).resolve().parent)
if _SCRIPT in sys.path:
    sys.path.remove(_SCRIPT)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import load_daily, simulate_open_break  # noqa: E402
from backtest.universe_zz500_1000 import CACHE_DIR  # noqa: E402
from strategy.factor13_bear_shield import (  # noqa: E402
    DEFAULT_PARAMS,
    fit_symbol_thresholds,
    rules_text,
    select_top,
)

OUT = _MYQUAN / "backtest" / "factor13_bear_shield_v3"
PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"

THR_FIT_START, THR_FIT_END = 2020, 2025
SCORE_FIT_END = 2025
OOS_A = ("2025-01-01", "2026-08-25")
OOS_B = ("2026-01-01", "2026-08-25")


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def _load_sym(sym: str) -> pd.DataFrame | None:
    d = load_daily(sym)
    if d is None:
        p = CACHE_DIR / f"{sym}_daily_qfq.parquet"
        if not p.exists():
            return None
        d = pd.read_parquet(p)
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    else:
        d = d.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    return d.reset_index(drop=True)


def _nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 5:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    ret = float(nav.iloc[-1] / nav.iloc[0] - 1) * 100
    mdd = abs(float((nav / nav.cummax() - 1).min() * 100))
    r = nav.pct_change().dropna()
    sh = float(r.mean() / r.std() * np.sqrt(252)) if float(r.std()) > 1e-12 else np.nan
    return {"ret": ret, "mdd": mdd, "sharpe": sh}


def sim_window(sym: str, thr: float, start: str, end: str) -> dict:
    d = _load_sym(sym)
    if d is None or len(d) < 40:
        return {"ok": 0, "error": "no_data"}
    dates = pd.DatetimeIndex(pd.to_datetime(d["date"])).normalize()
    eq, _ = simulate_open_break(
        d["open"].to_numpy(float),
        d["high"].to_numpy(float),
        d["low"].to_numpy(float),
        d["close"].to_numpy(float),
        thr=float(thr),
    )
    s = pd.Series(eq, index=dates)
    c = pd.Series(d["close"].to_numpy(float), index=dates)
    m = (s.index >= start) & (s.index <= end)
    s, c = s[m], c[m]
    if len(s) < 5:
        return {"ok": 0, "error": "short"}
    nav = s / float(s.iloc[0])
    st = _nav_stats(nav)
    bh = float(c.iloc[-1] / c.iloc[0] - 1) * 100
    return {
        "ok": 1,
        "nav": nav,
        "bh": bh,
        "excess": st["ret"] - bh,
        **st,
    }


def equal_weight(navs: dict[str, pd.Series]) -> pd.Series:
    df = pd.concat(navs, axis=1).sort_index().ffill()
    port = (1 + df.pct_change().mean(axis=1).fillna(0)).cumprod()
    port.iloc[0] = 1.0
    return port


def run_basket(picks: pd.DataFrame, start: str, end: str) -> tuple[dict, pd.DataFrame, pd.Series]:
    navs, rows = {}, []
    for _, r in picks.iterrows():
        sym = str(r["symbol"]).lower()
        thr = float(r.get("thr", 0.025))
        name = str(r.get("name", sym))
        res = sim_window(sym, thr, start, end)
        if not res.get("ok"):
            continue
        navs[sym] = res["nav"]
        rows.append(
            {
                "symbol": sym,
                "name": name,
                "thr": thr,
                "ret": res["ret"],
                "bh": res["bh"],
                "excess": res["excess"],
                "mdd": res["mdd"],
                "sharpe": res["sharpe"],
            }
        )
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    return _nav_stats(port), pd.DataFrame(rows), port


def html_report(
    picks: pd.DataFrame,
    thr_df: pd.DataFrame,
    oos_a: dict,
    detail_a: pd.DataFrame,
    oos_b: dict,
    detail_b: pd.DataFrame,
    legacy: dict,
) -> str:
    def tbl(df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return "<p>（空）</p>"
        show = df.copy()
        for c in show.select_dtypes(include=[float, np.floating]).columns:
            show[c] = show[c].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")
        return show.to_html(index=False, border=0, classes="t")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>因子13 熊市盾牌 v3</title>
<style>
body{{font-family:-apple-system,PingFang SC,sans-serif;max-width:980px;margin:32px auto;padding:0 16px;color:#e8eaed;background:#0f1115;line-height:1.55}}
h1,h2{{font-weight:650}} h2{{margin-top:2rem;border-bottom:1px solid #2a2f3a;padding-bottom:6px}}
.muted{{color:#9aa3b2}} .t{{width:100%;border-collapse:collapse;font-size:13px}}
.t th,.t td{{border-bottom:1px solid #2a2f3a;padding:6px 8px;text-align:left}}
.stat{{display:inline-block;margin:8px 16px 8px 0}} .stat b{{font-size:1.25rem}}
.good{{color:#3dd68c}} .warn{{color:#e6c07b}}
</style></head><body>
<h1>因子13 · 熊市盾牌 v3</h1>
<p class="muted">thr*：{THR_FIT_START}–{THR_FIT_END} 夏普择优（天通钉 ±3%）；打分拟合至 {SCORE_FIT_END}；
软牛：年均策略≥5%，有牛年则牛年策略≥0。研究用途，非投资建议。</p>
<p class="muted">注：thr 拟合窗含 2025，故「2025–2026」区间 thr 有部分样本内重合；2026 单独更干净。</p>

<h2>组合表现</h2>
<p class="stat">2025–2026 <b class="good">{oos_a.get('ret', float('nan')):+.1f}%</b>
<span class="muted">回撤 {oos_a.get('mdd', float('nan')):.1f}% · 夏普 {oos_a.get('sharpe', float('nan')):.2f}</span></p>
<p class="stat">2026YTD <b class="good">{oos_b.get('ret', float('nan')):+.1f}%</b>
<span class="muted">回撤 {oos_b.get('mdd', float('nan')):.1f}% · 夏普 {oos_b.get('sharpe', float('nan')):.2f}</span></p>
<p class="stat">对照旧版统一±2.5% Top5·2026 <b>{legacy.get('ret', float('nan')):+.1f}%</b>
<span class="muted">回撤 {legacy.get('mdd', float('nan')):.1f}%</span></p>

<h2>入选 Top{len(picks)}</h2>
{tbl(picks[[c for c in ('symbol','name','thr','obear_ex','obear_ret','ret_mean','obull_ret','q_obear_ex','score') if c in picks.columns]])}

<h2>2025–2026 个股</h2>
{tbl(detail_a)}

<h2>2026YTD 个股</h2>
{tbl(detail_b)}

<h2>thr* 分布（拟合窗）</h2>
<p class="muted">入选票 thr 见上表；全市场 thr* 计数：</p>
{tbl(thr_df['thr'].value_counts().rename_axis('thr').reset_index(name='n'))}

</body></html>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL)
    q_panel = pd.read_parquet(Q_PANEL) if Q_PANEL.exists() else None
    name_map = _name_map()

    params = {**DEFAULT_PARAMS, "rule": "qy_blend", "top_k": 3, "use_per_stock_thr": True}
    print(rules_text(params))

    thr_df = fit_symbol_thresholds(
        panel,
        fit_start_year=THR_FIT_START,
        fit_end_year=THR_FIT_END,
        pin=params.get("pin_thr"),
    )
    thr_df.to_csv(OUT / "thr_fit_2020_2025.csv", index=False, float_format="%.6f")
    thr_map = dict(zip(thr_df["symbol"], thr_df["thr"]))
    print(f"thr* 覆盖 {len(thr_map)} 只 | 分布:\n{thr_df['thr'].value_counts().sort_index()}")

    picks = select_top(
        panel,
        fit_end_year=SCORE_FIT_END,
        params=params,
        quarter_panel=q_panel,
        thr_map=thr_map,
    )
    if "name" in picks.columns:
        picks["name"] = picks.apply(
            lambda r: r["name"] if str(r["name"]).strip() else name_map.get(str(r["symbol"]), ""),
            axis=1,
        )
    picks.to_csv(OUT / "picks_fit2025.csv", index=False, float_format="%.4f")
    show = [c for c in ("symbol", "name", "thr", "obear_ex", "ret_mean", "obull_ret", "q_obear_ex", "score") if c in picks.columns]
    print("\n入选:")
    print(picks[show].round(2).to_string(index=False))

    # 天通是否入选
    tt = picks[picks["symbol"].astype(str).str.lower() == "sh600330"]
    print(f"\n天通入选: {'是 thr='+str(float(tt.iloc[0]['thr'])) if len(tt) else '否'}")
    if "sh600330" in thr_map:
        # 全排名看天通
        full = select_top(
            panel, fit_end_year=SCORE_FIT_END, params={**params, "top_k": 200},
            quarter_panel=q_panel, thr_map=thr_map, k=200,
        )
        full = full.reset_index(drop=True)
        full["rk"] = full.index + 1
        ttr = full[full.symbol.str.lower() == "sh600330"]
        if len(ttr):
            print(f"天通全榜 rank={int(ttr.iloc[0]['rk'])} score={float(ttr.iloc[0]['score']):.3f}")
        full.to_csv(OUT / "rank_full.csv", index=False, float_format="%.4f")

    oos_a, detail_a, port_a = run_basket(picks, *OOS_A)
    oos_b, detail_b, port_b = run_basket(picks, *OOS_B)
    detail_a.to_csv(OUT / "oos_2025_2026_detail.csv", index=False, float_format="%.4f")
    detail_b.to_csv(OUT / "oos_2026_detail.csv", index=False, float_format="%.4f")
    port_a.to_csv(OUT / "nav_2025_2026.csv")
    port_b.to_csv(OUT / "nav_2026.csv")

    print(f"\n2025–2026 等权: {oos_a['ret']:+.1f}%  MDD {oos_a['mdd']:.1f}%  sh={oos_a['sharpe']:.2f}")
    print(f"2026YTD   等权: {oos_b['ret']:+.1f}%  MDD {oos_b['mdd']:.1f}%  sh={oos_b['sharpe']:.2f}")
    if len(detail_b):
        print(detail_b[["name", "thr", "ret", "bh", "excess", "mdd"]].round(1).to_string(index=False))

    # 对照：上一版已落盘的 Top5（统一 ±2.5%）
    legacy_path = _MYQUAN / "backtest" / "factor13_bear_shield" / "picks_2025_for_2026.csv"
    legacy_st_a = legacy_st_b = {"ret": float("nan"), "mdd": float("nan"), "sharpe": float("nan")}
    legacy_names = []
    if legacy_path.exists():
        lp = pd.read_csv(legacy_path)
        lp["thr"] = 0.025
        legacy_names = lp["name"].astype(str).tolist() if "name" in lp.columns else lp["symbol"].tolist()
        legacy_st_a, _, _ = run_basket(lp, *OOS_A)
        legacy_st_b, _, _ = run_basket(lp, *OOS_B)
        print(f"\n对照旧Top5统一±2.5% · 2025–2026: {legacy_st_a['ret']:+.1f}% MDD {legacy_st_a['mdd']:.1f}%")
        print(f"对照旧Top5统一±2.5% · 2026:       {legacy_st_b['ret']:+.1f}% MDD {legacy_st_b['mdd']:.1f}%")
        print("旧名单:", ", ".join(legacy_names))

    meta = {
        "thr_fit": f"{THR_FIT_START}-{THR_FIT_END}",
        "score_fit_end": SCORE_FIT_END,
        "oos_a": OOS_A,
        "oos_b": OOS_B,
        "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items() if k != "pin_thr"},
        "pin_thr": params.get("pin_thr"),
        "oos_a_stats": oos_a,
        "oos_b_stats": oos_b,
        "legacy_2025_2026": legacy_st_a,
        "legacy_2026": legacy_st_b,
        "legacy_names": legacy_names,
        "picks": picks[["symbol", "name", "thr", "score"]].to_dict(orient="records") if len(picks) else [],
        "note": "thr fit window includes 2025; 2025-2026 OOS partially overlaps thr fit",
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.html").write_text(
        html_report(picks, thr_df, oos_a, detail_a, oos_b, detail_b, legacy_st_b),
        encoding="utf-8",
    )
    print(f"\n→ {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
