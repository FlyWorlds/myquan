"""因子13 v3：质量带优化（夏普适中 + 回撤20–30% + 策略回撤≤持有一半）+ 自选 TopK。

阈值：±2.5% 与 ±3% 分别回测；可选「两年内按夏普择优阈值」。
选股年 T 过滤后排序 → 交易年 T+1 等权盲测。

  python strategy/run_factor13_quality_opt.py
"""

from __future__ import annotations

import json
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR in sys.path:
    sys.path.remove(_SCRIPT_DIR)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from backtest.factor1_monthly_top3 import (  # noqa: E402
    _metrics_from_equity,
    load_daily,
    simulate_open_break,
)
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402

OUT = _MYQUAN / "backtest" / "factor13_quality_opt"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
YEARS = list(range(2020, 2027))
THRESHOLDS = (0.025, 0.03)
WORKERS = 8
MIN_BARS = 80
TRAIN_FITS = [2020, 2021, 2022, 2023, 2024]  # OOS 2021-2025
BLIND_FIT = 2025  # OOS 2026


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _count_trades(holding: np.ndarray) -> int:
    if len(holding) < 2:
        return 0
    return int(np.sum(np.diff(holding.astype(int)) > 0))


def process_symbol(task: dict) -> list[dict]:
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
    rows = []
    for y in YEARS:
        mask = dates.year == y
        idx = np.where(mask)[0]
        if len(idx) < MIN_BARS:
            continue
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        i_warm = max(0, i0 - 3)
        by_thr: dict[float, dict] = {}
        for thr in THRESHOLDS:
            eq, hold = simulate_open_break(
                o[i_warm:i1], h[i_warm:i1], l[i_warm:i1], c[i_warm:i1], thr=thr
            )
            off = i0 - i_warm
            eq_y, hold_y, c_y = eq[off:], hold[off:], c[i0:i1]
            if len(eq_y) < MIN_BARS or eq_y[0] <= 0:
                continue
            eq_n = eq_y / eq_y[0] * 100_000.0
            met = _metrics_from_equity(eq_n, c_y)
            met["trades"] = float(_count_trades(hold_y))
            met["threshold_pct"] = thr
            by_thr[thr] = met
        if not by_thr:
            continue
        # 择优：两阈值中夏普更高者
        best_thr = max(by_thr.keys(), key=lambda t: by_thr[t]["sharpe_ratio"])
        best = by_thr[best_thr]
        for thr, met in by_thr.items():
            bh_dd = float(met["bh_max_drawdown_pct"])
            mdd = float(met["max_drawdown_pct"])
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "year": y,
                    "n_bars": int(i1 - i0),
                    "mainboard": int(_is_mainboard(symbol)),
                    "thr_mode": f"{thr:.3f}",
                    "thr": thr,
                    "ret": met["total_return_pct"],
                    "sharpe": met["sharpe_ratio"],
                    "mdd": mdd,
                    "bh": met["bh_return_pct"],
                    "bh_dd": bh_dd,
                    "excess": met["excess_return_pct"],
                    "dd_improve": met["dd_improve_pct"],
                    "dd_ratio": (mdd / bh_dd) if bh_dd > 1e-6 else np.nan,
                    "trades": met["trades"],
                    "is_best_thr": int(thr == best_thr),
                }
            )
        # 合成行：每年一票用择优阈值（供 thr_mode=best）
        bh_dd = float(best["bh_max_drawdown_pct"])
        mdd = float(best["max_drawdown_pct"])
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "year": y,
                "n_bars": int(i1 - i0),
                "mainboard": int(_is_mainboard(symbol)),
                "thr_mode": "best",
                "thr": best_thr,
                "ret": best["total_return_pct"],
                "sharpe": best["sharpe_ratio"],
                "mdd": mdd,
                "bh": best["bh_return_pct"],
                "bh_dd": bh_dd,
                "excess": best["excess_return_pct"],
                "dd_improve": best["dd_improve_pct"],
                "dd_ratio": (mdd / bh_dd) if bh_dd > 1e-6 else np.nan,
                "trades": best["trades"],
                "is_best_thr": 1,
            }
        )
    return rows


def build_panel(force: bool = False) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "year_thr_panel.parquet"
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
    print(f"主板 {len(tasks)} × 阈值{{2.5%,3%,best}} 分年模拟...")
    rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process_symbol, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                rows.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
                print("err", exc)
            if done % 100 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} ({time.time()-t0:.0f}s) rows={len(rows)}")
    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    print(f"面板 {df.shape} → {cache}")
    return df


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def enrich(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["rk_excess"] = _pct_rank(g["excess"])
    g["rk_sharpe"] = _pct_rank(g["sharpe"])
    g["rk_dd_imp"] = _pct_rank(g["dd_improve"])
    g["rk_ret"] = _pct_rank(g["ret"])
    # 质量偏好：回撤越接近 25% 越好（高斯），dd_ratio 越低越好
    g["mdd_sweet"] = np.exp(-0.5 * ((g["mdd"] - 25.0) / 6.0) ** 2)
    g["rk_mdd_sweet"] = _pct_rank(g["mdd_sweet"])
    g["rk_dd_ratio_inv"] = _pct_rank(-g["dd_ratio"])  # 低比率更好
    g["score_esd"] = 5 * g["rk_excess"] + 3 * g["rk_sharpe"] + 2 * g["rk_dd_imp"]
    g["score_fit"] = 4 * g["rk_excess"] + 3 * g["rk_sharpe"] + 2 * g["rk_dd_imp"] + g["rk_ret"]
    g["score_quality"] = (
        3 * g["rk_excess"]
        + 2 * g["rk_sharpe"]
        + 2 * g["rk_mdd_sweet"]
        + 2 * g["rk_dd_ratio_inv"]
        + 1 * g["rk_dd_imp"]
    )
    return g


# 夏普「大点但不要特别大」：多组带宽
SHARPE_BANDS = [
    (0.8, 2.0),
    (1.0, 2.2),
    (0.7, 1.8),
    (0.5, 2.0),
    (1.0, 2.5),
]
MDD_BANDS = [
    (20.0, 30.0),
    (18.0, 32.0),
    (15.0, 35.0),  # 略放宽对照
]
DD_RATIO_MAX = [0.50, 0.55, 0.60]  # ≤持有回撤一半为主
TOP_K = [3, 5, 8, 10]
RANK_COLS = ["excess", "score_quality", "score_fit", "sharpe"]


def apply_filters(
    g: pd.DataFrame,
    *,
    sharpe_lo: float,
    sharpe_hi: float,
    mdd_lo: float,
    mdd_hi: float,
    dd_ratio_max: float,
) -> pd.DataFrame:
    out = g.copy()
    out = out[(out["sharpe"] >= sharpe_lo) & (out["sharpe"] <= sharpe_hi)]
    out = out[(out["mdd"] >= mdd_lo) & (out["mdd"] <= mdd_hi)]
    out = out[out["dd_ratio"] <= dd_ratio_max]
    out = out[out["bh_dd"] > 5]  # 持有几乎无回撤则比率无意义
    return out


def select(
    panel: pd.DataFrame,
    fit_year: int,
    thr_mode: str,
    *,
    sharpe_lo: float,
    sharpe_hi: float,
    mdd_lo: float,
    mdd_hi: float,
    dd_ratio_max: float,
    rank_col: str,
    top_k: int,
) -> pd.DataFrame:
    g = panel[(panel["year"] == fit_year) & (panel["thr_mode"] == thr_mode)].copy()
    if g.empty:
        return g
    g = enrich(g)
    g = apply_filters(
        g,
        sharpe_lo=sharpe_lo,
        sharpe_hi=sharpe_hi,
        mdd_lo=mdd_lo,
        mdd_hi=mdd_hi,
        dd_ratio_max=dd_ratio_max,
    )
    if g.empty:
        return g
    return g.sort_values(rank_col, ascending=False).head(int(top_k))


def eval_oos(
    panel: pd.DataFrame,
    symbols: list[str],
    oos_year: int,
    thr_mode: str,
) -> dict:
    g = panel[
        (panel["year"] == oos_year)
        & (panel["thr_mode"] == thr_mode)
        & (panel["symbol"].isin(symbols))
    ]
    univ = panel[(panel["year"] == oos_year) & (panel["thr_mode"] == thr_mode)]
    if g.empty:
        return {
            "n": 0,
            "ret": np.nan,
            "med_ret": np.nan,
            "sharpe": np.nan,
            "mdd": np.nan,
            "excess": np.nan,
            "bh": np.nan,
            "univ_ret": float(univ["ret"].mean()) if len(univ) else np.nan,
            "alpha": np.nan,
            "pos_n": 0,
            "beat_bh_n": 0,
        }
    return {
        "n": int(len(g)),
        "ret": float(g["ret"].mean()),
        "med_ret": float(g["ret"].median()),
        "sharpe": float(g["sharpe"].mean()),
        "mdd": float(g["mdd"].mean()),
        "excess": float(g["excess"].mean()),
        "bh": float(g["bh"].mean()),
        "univ_ret": float(univ["ret"].mean()),
        "alpha": float(g["ret"].mean() - univ["ret"].mean()),
        "pos_n": int((g["ret"] > 0).sum()),
        "beat_bh_n": int((g["excess"] > 0).sum()),
    }


def walk_forward(panel: pd.DataFrame, cfg: dict, fit_years: list[int]) -> pd.DataFrame:
    rows = []
    for t in fit_years:
        picks = select(
            panel,
            t,
            cfg["thr_mode"],
            sharpe_lo=cfg["sharpe_lo"],
            sharpe_hi=cfg["sharpe_hi"],
            mdd_lo=cfg["mdd_lo"],
            mdd_hi=cfg["mdd_hi"],
            dd_ratio_max=cfg["dd_ratio_max"],
            rank_col=cfg["rank_col"],
            top_k=cfg["top_k"],
        )
        syms = picks["symbol"].tolist()
        # OOS 用同一 thr_mode 评估（best 则用各票当年 best 行）
        ev = eval_oos(panel, syms, t + 1, cfg["thr_mode"])
        rows.append(
            {
                **{f"cfg_{k}": v for k, v in cfg.items()},
                "fit_year": t,
                "oos_year": t + 1,
                "n_cand": len(
                    apply_filters(
                        enrich(
                            panel[
                                (panel["year"] == t) & (panel["thr_mode"] == cfg["thr_mode"])
                            ]
                        ),
                        sharpe_lo=cfg["sharpe_lo"],
                        sharpe_hi=cfg["sharpe_hi"],
                        mdd_lo=cfg["mdd_lo"],
                        mdd_hi=cfg["mdd_hi"],
                        dd_ratio_max=cfg["dd_ratio_max"],
                    )
                ),
                "n_picks": len(syms),
                "symbols": ",".join(syms),
                "oos_ret": ev["ret"],
                "oos_med": ev["med_ret"],
                "oos_sharpe": ev["sharpe"],
                "oos_mdd": ev["mdd"],
                "oos_excess": ev["excess"],
                "univ_ret": ev["univ_ret"],
                "alpha": ev["alpha"],
                "pos_n": ev["pos_n"],
                "beat_bh_n": ev["beat_bh_n"],
            }
        )
    return pd.DataFrame(rows)


def grid_search(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    configs = []
    for thr_mode in ["0.025", "0.030", "best"]:
        for sh in SHARPE_BANDS:
            for mdd in MDD_BANDS:
                for ddr in DD_RATIO_MAX:
                    for rank_col in RANK_COLS:
                        for k in TOP_K:
                            configs.append(
                                {
                                    "thr_mode": thr_mode,
                                    "sharpe_lo": sh[0],
                                    "sharpe_hi": sh[1],
                                    "mdd_lo": mdd[0],
                                    "mdd_hi": mdd[1],
                                    "dd_ratio_max": ddr,
                                    "rank_col": rank_col,
                                    "top_k": k,
                                }
                            )
    print(f"网格 {len(configs)} 组...")
    summaries = []
    # 预先按 thr_mode 切，加速
    best_summary = None
    best_cfg = None
    best_wf = None
    for i, cfg in enumerate(configs):
        wf = walk_forward(panel, cfg, TRAIN_FITS)
        # 要求多数年份能选出足够票
        if wf["n_picks"].mean() < max(2, cfg["top_k"] * 0.5):
            continue
        # 稳健目标：alpha 为主，兼顾中位收益、少极端依赖（med 接近 mean）
        avg_alpha = float(wf["alpha"].mean())
        avg_ret = float(wf["oos_ret"].mean())
        avg_med = float(wf["oos_med"].mean())
        beat = int((wf["alpha"] > 0).sum())
        # 惩罚 mean-med 巨大背离（单票依赖）
        skew_pen = abs(avg_ret - avg_med)
        score = avg_alpha + 0.25 * avg_med - 0.15 * skew_pen + 0.5 * beat
        row = {
            **cfg,
            "avg_ret": avg_ret,
            "avg_med": avg_med,
            "avg_alpha": avg_alpha,
            "avg_sharpe": float(wf["oos_sharpe"].mean()),
            "avg_mdd": float(wf["oos_mdd"].mean()),
            "beat_univ_n": beat,
            "n_years": len(wf),
            "skew_pen": skew_pen,
            "score": score,
            "avg_n_cand": float(wf["n_cand"].mean()),
        }
        summaries.append(row)
        if best_summary is None or score > best_summary["score"]:
            best_summary = row
            best_cfg = cfg
            best_wf = wf
        if (i + 1) % 200 == 0:
            print(f"  grid {i+1}/{len(configs)}")
    grid = pd.DataFrame(summaries).sort_values("score", ascending=False)
    assert best_cfg is not None and best_wf is not None
    return grid, best_cfg, best_wf


def write_html(report: dict, path: Path) -> None:
    top = pd.DataFrame(report["grid_top"])
    wf = pd.DataFrame(report["wf_all"])
    rows_g = "".join(
        f"<tr><td>{r.thr_mode}</td><td>{r.rank_col}</td><td>{int(r.top_k)}</td>"
        f"<td>{r.sharpe_lo}-{r.sharpe_hi}</td><td>{r.mdd_lo}-{r.mdd_hi}</td>"
        f"<td>{r.dd_ratio_max}</td><td>{r.avg_ret:.1f}</td><td>{r.avg_med:.1f}</td>"
        f"<td>{r.avg_alpha:.1f}</td><td>{r.beat_univ_n}/{int(r.n_years)}</td><td>{r.score:.2f}</td></tr>"
        for r in top.head(12).itertuples()
    )
    rows_w = "".join(
        f"<tr><td>{int(r.fit_year)}→{int(r.oos_year)}</td><td>{r.n_picks}</td>"
        f"<td>{r.oos_ret:.1f}</td><td>{r.oos_med:.1f}</td><td>{r.alpha:.1f}</td>"
        f"<td>{r.oos_mdd:.1f}</td><td>{r.symbols}</td></tr>"
        for r in wf.itertuples()
    )
    b = report["blind"]
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>
<title>因子13 质量带优化</title>
<style>
body{{font-family:PingFang SC,Helvetica,sans-serif;background:#0f1115;color:#e8eaed;padding:28px}}
.wrap{{max-width:1100px;margin:0 auto}}.meta{{color:#9aa3b2}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:14px;margin:14px 0}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.stat{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:12px}}
.stat .v{{font-size:1.35rem;font-weight:650;color:#3dd68c}}.stat .l{{color:#9aa3b2;font-size:.8rem}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
th,td{{padding:6px 8px;border-bottom:1px solid #2a2f3a;text-align:right}}
th:first-child,td:first-child,td:nth-child(7){{text-align:left}} th{{color:#9aa3b2}}
.callout{{border-left:3px solid #3d8bfd;padding:10px 14px;background:#171a21}}
</style></head><body><div class="wrap">
<h1>因子13 · 质量带优化（夏普适中 + 回撤带 + 半回撤）</h1>
<p class="meta">阈值 2.5%/3%/择优 · 调参 2020→2025 · 盲测 2025→2026 · 非投资建议</p>
<div class="callout"><b>最优：</b>{report['label']}</div>
<div class="stats">
<div class="stat"><div class="v">{report['train_avg_ret']:.1f}%</div><div class="l">调参窗均收益</div></div>
<div class="stat"><div class="v">{report['train_avg_med']:.1f}%</div><div class="l">调参窗均中位</div></div>
<div class="stat"><div class="v">{report['train_avg_alpha']:.1f}pp</div><div class="l">相对全池</div></div>
<div class="stat"><div class="v">{b['oos_ret']:.1f}%</div><div class="l">盲测2026等权 / 中位 {b['oos_med']:.1f}%</div></div>
</div>
<div class="card"><h3>网格 Top12</h3>
<table><thead><tr><th>阈值</th><th>排序</th><th>K</th><th>夏普带</th><th>回撤带</th><th>dd比值≤</th><th>均收益</th><th>均中位</th><th>vs全池</th><th>胜年</th><th>score</th></tr></thead>
<tbody>{rows_g}</tbody></table></div>
<div class="card"><h3>最优参数逐年</h3>
<table><thead><tr><th>年</th><th>N</th><th>等权%</th><th>中位%</th><th>vs全池</th><th>均回撤</th><th>名单</th></tr></thead>
<tbody>{rows_w}</tbody></table></div>
</div></body></html>"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = build_panel(force=False)
    panel = panel[panel["mainboard"] == 1].copy()

    grid, best_cfg, train_wf = grid_search(panel)
    grid.to_csv(OUT / "grid_results.csv", index=False, float_format="%.4f")
    print("\n=== TOP 8 ===")
    print(
        grid.head(8)[
            [
                "thr_mode",
                "rank_col",
                "top_k",
                "sharpe_lo",
                "sharpe_hi",
                "mdd_lo",
                "mdd_hi",
                "dd_ratio_max",
                "avg_ret",
                "avg_med",
                "avg_alpha",
                "beat_univ_n",
                "score",
            ]
        ].to_string(index=False)
    )

    wf_all = walk_forward(panel, best_cfg, TRAIN_FITS + [BLIND_FIT])
    wf_all.to_csv(OUT / "best_walkforward.csv", index=False, float_format="%.4f")
    train = wf_all[wf_all["oos_year"] <= 2025]
    blind = wf_all[wf_all["oos_year"] == 2026].iloc[0].to_dict()

    # 盲测个股明细
    picks_2026 = blind["symbols"].split(",") if blind.get("symbols") else []
    detail = panel[
        (panel["year"] == 2026)
        & (panel["thr_mode"] == best_cfg["thr_mode"])
        & (panel["symbol"].isin(picks_2026))
    ][["symbol", "name", "thr", "ret", "bh", "excess", "sharpe", "mdd", "bh_dd", "dd_ratio"]]
    detail.to_csv(OUT / "blind_2026_detail.csv", index=False, float_format="%.4f")

    # 选股年质量快照
    fit_picks = select(panel, BLIND_FIT, best_cfg["thr_mode"], **{
        k: best_cfg[k]
        for k in (
            "sharpe_lo",
            "sharpe_hi",
            "mdd_lo",
            "mdd_hi",
            "dd_ratio_max",
            "rank_col",
            "top_k",
        )
    })
    fit_picks.to_csv(OUT / "select_2025_for_2026.csv", index=False, float_format="%.4f")

    label = (
        f"{best_cfg['thr_mode']} · {best_cfg['rank_col']} Top{best_cfg['top_k']} · "
        f"夏普[{best_cfg['sharpe_lo']},{best_cfg['sharpe_hi']}] · "
        f"回撤[{best_cfg['mdd_lo']},{best_cfg['mdd_hi']}] · "
        f"dd_ratio≤{best_cfg['dd_ratio_max']}"
    )
    report = {
        "label": label,
        "best_cfg": best_cfg,
        "train_avg_ret": float(train["oos_ret"].mean()),
        "train_avg_med": float(train["oos_med"].mean()),
        "train_avg_alpha": float(train["alpha"].mean()),
        "blind": {
            "oos_ret": float(blind["oos_ret"]),
            "oos_med": float(blind["oos_med"]),
            "alpha": float(blind["alpha"]),
            "symbols": blind["symbols"],
            "n_picks": int(blind["n_picks"]),
        },
        "grid_top": grid.head(20).to_dict(orient="records"),
        "wf_all": wf_all.to_dict(orient="records"),
    }
    (OUT / "best_rule.json").write_text(
        json.dumps({"label": label, **best_cfg}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "meta.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_html(report, OUT / "report.html")

    # 同步更新 factor13 默认规则
    rule_path = _MYQUAN / "backtest" / "factor13_walkforward" / "best_rule.json"
    legacy = {
        "signal": best_cfg["rank_col"],
        "top_k": best_cfg["top_k"],
        "min_sharpe": best_cfg["sharpe_lo"],
        "max_sharpe": best_cfg["sharpe_hi"],
        "mdd_lo": best_cfg["mdd_lo"],
        "mdd_hi": best_cfg["mdd_hi"],
        "dd_ratio_max": best_cfg["dd_ratio_max"],
        "thr_mode": best_cfg["thr_mode"],
        "threshold_pct": 0.025 if best_cfg["thr_mode"] == "0.025" else 0.03,
        "mainboard_only": True,
        "timing": "year_t_quality_band_hold_year_t_plus_1",
        "label": label,
        "version": "quality_v3",
    }
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    rule_path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "best_rule.json").write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== BEST ===", label)
    print(wf_all[["fit_year", "oos_year", "n_picks", "oos_ret", "oos_med", "alpha", "symbols"]].to_string(index=False))
    print("\n盲测2026明细:")
    print(detail.to_string(index=False))
    print(f"\n报告 → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
