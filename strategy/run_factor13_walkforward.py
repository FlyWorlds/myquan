"""因子13 v2：策略一·因子1 契合选股（逐年 walk-forward）。

逻辑：
  · 用日历年 T 的策略表现/特征打分选股（可多信号、多参数）
  · 在日历年 T+1 等权持有选出的票，跑同一套开盘突破基线
  · 选股绝不偷看 T+1；2026 仅作末年样本外

目标：找出「上年什么指标」最能预测「下年策略1表现」，
不绑定天通/凯盛风格孪生。

  python strategy/run_factor13_walkforward.py
"""

from __future__ import annotations

import json
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
# 以脚本方式运行时 sys.path[0] 会是 strategy/，会遮蔽仓库根下的 backtest/ 包
if _SCRIPT_DIR in sys.path:
    sys.path.remove(_SCRIPT_DIR)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))
elif sys.path[0] != str(_MYQUAN):
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from backtest.factor1_monthly_top3 import (  # noqa: E402
    _metrics_from_equity,
    load_daily,
    simulate_open_break,
)
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402

OUT = _MYQUAN / "backtest" / "factor13_walkforward"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
YEARS = list(range(2020, 2027))  # 特征到 2025，OOS 到 2026
THRESHOLDS = (0.02, 0.025, 0.03)
DEFAULT_THR = 0.025
WORKERS = 8
MIN_BARS = 80
TOP_K_GRID = (5, 8, 10, 15, 20)
MIN_SHARPE_GRID = (None, 0.5, 1.0)
MIN_TRADES_GRID = (0, 8)


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _year_style_feats(o, h, l, c) -> dict[str, float]:
    o = np.asarray(o, float)
    h = np.asarray(h, float)
    l = np.asarray(l, float)
    c = np.asarray(c, float)
    ret = np.diff(c) / c[:-1]
    ret = ret[np.isfinite(ret)]
    amp = (h - l) / np.where(c > 0, c, np.nan)
    oc = np.abs(c / np.where(o > 0, o, np.nan) - 1.0)
    up = h >= o * 1.025
    dn = l <= o * 0.975
    return {
        "amp_mean": float(np.nanmean(amp)),
        "oc_ge_2p5": float(np.nanmean(oc >= 0.025)),
        "break_hit": float(np.mean(up | dn)),
        "vol_ann": float(np.std(ret, ddof=1) * math.sqrt(242)) if len(ret) >= 5 else np.nan,
        "big_move_freq": float(np.mean(np.abs(ret) >= 0.03)) if len(ret) else np.nan,
        "bh_ret": float(c[-1] / c[0] - 1.0) * 100.0 if c[0] > 0 else np.nan,
        "bh_dd": float(-np.min(c / np.maximum.accumulate(c) - 1.0)) * 100.0,
    }


def _count_trades(equity: np.ndarray, holding: np.ndarray) -> int:
    """持仓 0→1 次数近似开仓次数。"""
    if len(holding) < 2:
        return 0
    d = np.diff(holding.astype(int))
    return int(np.sum(d > 0))


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
        mask = (dates.year == y)
        idx = np.where(mask)[0]
        if len(idx) < MIN_BARS:
            continue
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        # 前多留 3 日供过滤（若有）
        i_warm = max(0, i0 - 3)
        best = None
        fixed = None
        for thr in THRESHOLDS:
            eq, hold = simulate_open_break(
                o[i_warm:i1], h[i_warm:i1], l[i_warm:i1], c[i_warm:i1], thr=thr
            )
            # 截到自然年
            off = i0 - i_warm
            eq_y = eq[off:]
            hold_y = hold[off:]
            c_y = c[i0:i1]
            if len(eq_y) < MIN_BARS or eq_y[0] <= 0:
                continue
            # 归一：年首权益为起点
            eq_n = eq_y / eq_y[0] * 100_000.0
            met = _metrics_from_equity(eq_n, c_y)
            met["trades"] = float(_count_trades(eq_n, hold_y))
            met["threshold_pct"] = thr
            if best is None or (
                np.isfinite(met["sharpe_ratio"])
                and met["sharpe_ratio"] > best["sharpe_ratio"]
            ):
                best = met
            if abs(thr - DEFAULT_THR) < 1e-12:
                fixed = dict(met)
        if best is None or fixed is None:
            continue
        style = _year_style_feats(o[i0:i1], h[i0:i1], l[i0:i1], c[i0:i1])
        row = {
            "symbol": symbol,
            "name": name,
            "year": y,
            "n_bars": int(i1 - i0),
            "mainboard": int(_is_mainboard(symbol)),
            # 默认阈值 2.5%
            "ret": fixed["total_return_pct"],
            "sharpe": fixed["sharpe_ratio"],
            "mdd": fixed["max_drawdown_pct"],
            "bh": fixed["bh_return_pct"],
            "bh_dd": fixed["bh_max_drawdown_pct"],
            "excess": fixed["excess_return_pct"],
            "dd_improve": fixed["dd_improve_pct"],
            "trades": fixed["trades"],
            "thr": fixed["threshold_pct"],
            # 年内最优阈值（按夏普）
            "ret_best": best["total_return_pct"],
            "sharpe_best": best["sharpe_ratio"],
            "excess_best": best["excess_return_pct"],
            "dd_improve_best": best["dd_improve_pct"],
            "trades_best": best["trades"],
            "thr_best": best["threshold_pct"],
            **style,
        }
        rows.append(row)
    return rows


def build_year_panel(force: bool = False) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "year_panel.parquet"
    if cache.exists() and not force:
        print(f"加载年面板缓存 {cache}")
        return pd.read_parquet(cache)

    meta = pd.read_csv(META_CSV, usecols=["symbol", "name", "code"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    # 仅有缓存的主板优先；也允许全池但默认评分时过滤主板
    symbols = []
    for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet")):
        sym = fp.name.replace("_daily_qfq.parquet", "")
        if _is_mainboard(sym):
            symbols.append(sym)
    name_map = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    tasks = [{"symbol": s, "name": name_map.get(s, "")} for s in symbols]
    print(f"主板候选 {len(tasks)}，并行计算分年策略指标...")
    rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process_symbol, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                part = fut.result()
            except Exception as exc:  # noqa: BLE001
                part = []
                print(f"  worker err: {exc}")
            rows.extend(part)
            if done % 50 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} ({time.time()-t0:.0f}s) rows={len(rows)}")
    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    print(f"年面板 {df.shape} → {cache}")
    return df


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def add_scores(panel: pd.DataFrame) -> pd.DataFrame:
    """每年截面打分。"""
    parts = []
    for y, g in panel.groupby("year"):
        g = g.copy()
        g["rk_ret"] = _pct_rank(g["ret"])
        g["rk_sharpe"] = _pct_rank(g["sharpe"])
        g["rk_excess"] = _pct_rank(g["excess"])
        g["rk_dd_imp"] = _pct_rank(g["dd_improve"])
        g["rk_calmar"] = _pct_rank(g["ret"] / g["mdd"].clip(lower=1.0))
        g["rk_oc"] = _pct_rank(g["oc_ge_2p5"])
        g["rk_break"] = _pct_rank(g["break_hit"])
        g["rk_amp"] = _pct_rank(g["amp_mean"])
        # 组合分（对齐月频 Top3 权重思想）
        g["score_esd"] = 5 * g["rk_excess"] + 3 * g["rk_sharpe"] + 2 * g["rk_dd_imp"]
        g["score_rs"] = g["rk_ret"] + g["rk_sharpe"]
        g["score_fit"] = (
            4 * g["rk_excess"] + 3 * g["rk_sharpe"] + 2 * g["rk_dd_imp"] + 1 * g["rk_ret"]
        )
        g["score_style"] = g["rk_oc"] + g["rk_break"] + g["rk_amp"]
        g["score_fit_style"] = g["score_fit"] + 0.5 * g["score_style"]
        # best-thr 版本
        g["rk_excess_b"] = _pct_rank(g["excess_best"])
        g["rk_sharpe_b"] = _pct_rank(g["sharpe_best"])
        g["score_esd_best"] = (
            5 * g["rk_excess_b"] + 3 * g["rk_sharpe_b"] + 2 * _pct_rank(g["dd_improve_best"])
        )
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


SIGNALS: dict[str, str] = {
    "ret": "ret",
    "sharpe": "sharpe",
    "excess": "excess",
    "dd_improve": "dd_improve",
    "score_esd": "score_esd",
    "score_rs": "score_rs",
    "score_fit": "score_fit",
    "score_style": "score_style",
    "score_fit_style": "score_fit_style",
    "score_esd_best": "score_esd_best",
    "oc_ge_2p5": "oc_ge_2p5",
    "break_hit": "break_hit",
}


def select_from_year(
    scored: pd.DataFrame,
    year: int,
    signal: str,
    top_k: int,
    *,
    min_sharpe: float | None = None,
    min_trades: int = 0,
) -> list[str]:
    g = scored[scored["year"] == year].copy()
    if g.empty:
        return []
    if min_sharpe is not None:
        g = g[g["sharpe"] >= float(min_sharpe)]
    if min_trades > 0:
        g = g[g["trades"] >= float(min_trades)]
    col = SIGNALS[signal]
    g = g.dropna(subset=[col])
    if g.empty:
        return []
    g = g.sort_values(col, ascending=False).head(int(top_k))
    return g["symbol"].tolist()


def eval_portfolio(
    scored: pd.DataFrame,
    symbols: list[str],
    year: int,
    *,
    ret_col: str = "ret",
) -> dict[str, float]:
    g = scored[(scored["year"] == year) & (scored["symbol"].isin(symbols))]
    if g.empty:
        return {
            "n": 0,
            "ret": np.nan,
            "sharpe": np.nan,
            "mdd": np.nan,
            "excess": np.nan,
            "bh": np.nan,
            "beat_bh_n": 0,
        }
    # 等权：平均收益；夏普用截面平均近似；回撤用平均 mdd（保守）
    return {
        "n": int(len(g)),
        "ret": float(g[ret_col].mean()),
        "sharpe": float(g["sharpe"].mean()),
        "mdd": float(g["mdd"].mean()),
        "excess": float(g["excess"].mean()),
        "bh": float(g["bh"].mean()),
        "beat_bh_n": int((g["excess"] > 0).sum()),
        "med_ret": float(g[ret_col].median()),
        "pos_n": int((g[ret_col] > 0).sum()),
    }


def universe_benchmark(scored: pd.DataFrame, year: int) -> dict[str, float]:
    g = scored[scored["year"] == year]
    return {
        "ret": float(g["ret"].mean()),
        "sharpe": float(g["sharpe"].mean()),
        "excess": float(g["excess"].mean()),
        "bh": float(g["bh"].mean()),
    }


def walk_forward(
    scored: pd.DataFrame,
    signal: str,
    top_k: int,
    *,
    min_sharpe: float | None = None,
    min_trades: int = 0,
    fit_years: list[int] | None = None,
) -> pd.DataFrame:
    """T 选股 → T+1 评估。"""
    fit_years = fit_years or [2020, 2021, 2022, 2023, 2024, 2025]
    rows = []
    for t in fit_years:
        t1 = t + 1
        if t1 not in set(scored["year"]):
            continue
        picks = select_from_year(
            scored, t, signal, top_k, min_sharpe=min_sharpe, min_trades=min_trades
        )
        ev = eval_portfolio(scored, picks, t1)
        bench = universe_benchmark(scored, t1)
        rows.append(
            {
                "fit_year": t,
                "oos_year": t1,
                "signal": signal,
                "top_k": top_k,
                "min_sharpe": min_sharpe if min_sharpe is not None else "",
                "min_trades": min_trades,
                "n_picks": len(picks),
                "symbols": ",".join(picks),
                "oos_ret": ev["ret"],
                "oos_med_ret": ev.get("med_ret", np.nan),
                "oos_sharpe": ev["sharpe"],
                "oos_mdd": ev["mdd"],
                "oos_excess": ev["excess"],
                "oos_bh": ev["bh"],
                "oos_pos_n": ev.get("pos_n", 0),
                "oos_beat_bh_n": ev["beat_bh_n"],
                "univ_ret": bench["ret"],
                "univ_excess": bench["excess"],
                "alpha_vs_univ": ev["ret"] - bench["ret"],
            }
        )
    return pd.DataFrame(rows)


def grid_search(scored: pd.DataFrame) -> pd.DataFrame:
    """在 2020→2021 … 2024→2025 上调参；2025→2026 留作盲测。"""
    train_fits = [2020, 2021, 2022, 2023, 2024]
    rows = []
    for signal in SIGNALS:
        for k in TOP_K_GRID:
            for ms in MIN_SHARPE_GRID:
                for mt in MIN_TRADES_GRID:
                    wf = walk_forward(
                        scored,
                        signal,
                        k,
                        min_sharpe=ms,
                        min_trades=mt,
                        fit_years=train_fits,
                    )
                    if wf.empty:
                        continue
                    rows.append(
                        {
                            "signal": signal,
                            "top_k": k,
                            "min_sharpe": ms if ms is not None else "",
                            "min_trades": mt,
                            "n_years": len(wf),
                            "avg_oos_ret": float(wf["oos_ret"].mean()),
                            "avg_oos_excess": float(wf["oos_excess"].mean()),
                            "avg_alpha_univ": float(wf["alpha_vs_univ"].mean()),
                            "avg_oos_sharpe": float(wf["oos_sharpe"].mean()),
                            "avg_oos_mdd": float(wf["oos_mdd"].mean()),
                            "pos_year_n": int((wf["oos_ret"] > 0).sum()),
                            "beat_univ_n": int((wf["alpha_vs_univ"] > 0).sum()),
                            "med_oos_ret": float(wf["oos_ret"].median()),
                        }
                    )
    return pd.DataFrame(rows).sort_values(
        ["avg_alpha_univ", "avg_oos_ret", "avg_oos_sharpe"], ascending=False
    )


def write_html(report: dict, path: Path) -> None:
    top = pd.DataFrame(report["grid_top"])
    wf = pd.DataFrame(report["best_wf_all"])
    blind = report["blind_2026"]
    picks = report["picks_by_year"]
    rows_grid = "".join(
        f"<tr><td>{r['signal']}</td><td>{r['top_k']}</td><td>{r['min_sharpe']}</td>"
        f"<td>{r['min_trades']}</td><td>{r['avg_oos_ret']:.1f}</td>"
        f"<td>{r['avg_oos_excess']:.1f}</td><td>{r['avg_alpha_univ']:.1f}</td>"
        f"<td>{r['avg_oos_sharpe']:.2f}</td><td>{r['beat_univ_n']}/{r['n_years']}</td></tr>"
        for _, r in top.head(15).iterrows()
    )
    rows_wf = "".join(
        f"<tr><td>{int(r['fit_year'])}→{int(r['oos_year'])}</td>"
        f"<td>{r['oos_ret']:.1f}</td><td>{r['oos_excess']:.1f}</td>"
        f"<td>{r['univ_ret']:.1f}</td><td>{r['alpha_vs_univ']:.1f}</td>"
        f"<td>{r['oos_sharpe']:.2f}</td><td>{r['oos_mdd']:.1f}</td>"
        f"<td>{int(r['oos_beat_bh_n'])}/{int(r['n_picks'])}</td></tr>"
        for _, r in wf.iterrows()
    )
    pick_blocks = []
    for y, syms in picks.items():
        pick_blocks.append(f"<p><b>{y}→{int(y)+1}</b>: {syms}</p>")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>因子13 Walk-Forward 选股</title>
<style>
body{{font-family:PingFang SC,Helvetica,sans-serif;background:#0f1115;color:#e8eaed;padding:28px}}
.wrap{{max-width:1100px;margin:0 auto}} h1{{margin:0 0 8px}} .meta{{color:#9aa3b2}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:14px;margin:14px 0}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.stat{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:12px}}
.stat .v{{font-size:1.35rem;font-weight:650;color:#3dd68c}} .stat .l{{color:#9aa3b2;font-size:.8rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{padding:7px 8px;border-bottom:1px solid #2a2f3a;text-align:right}}
th:first-child,td:first-child{{text-align:left}} th{{color:#9aa3b2}}
.callout{{border-left:3px solid #3d8bfd;padding:10px 14px;background:#171a21;margin:12px 0}}
</style></head><body><div class="wrap">
<h1>因子13 · 策略1契合选股（Walk-Forward）</h1>
<p class="meta">上年打分选股 → 下年等权开盘突破 · 调参窗 2020→2025 · 盲测 2025→2026 · 非投资建议</p>
<div class="callout"><b>最优信号：</b>{report['best_label']}</div>
<div class="stats">
  <div class="stat"><div class="v">{report['train_avg_ret']:.1f}%</div><div class="l">调参窗年均 OOS 策略</div></div>
  <div class="stat"><div class="v">{report['train_avg_alpha']:.1f}%</div><div class="l">相对全池年均超额</div></div>
  <div class="stat"><div class="v">{blind['oos_ret']:.1f}%</div><div class="l">盲测 2026 策略等权</div></div>
  <div class="stat"><div class="v">{blind['alpha_vs_univ']:.1f}%</div><div class="l">盲测相对全池</div></div>
</div>
<div class="card"><h3>调参榜 Top15（按相对全池 alpha）</h3>
<table><thead><tr><th>信号</th><th>K</th><th>min夏普</th><th>min成交</th><th>年均OOS%</th><th>年均超额%</th><th>vs全池</th><th>夏普</th><th>胜年</th></tr></thead>
<tbody>{rows_grid}</tbody></table></div>
<div class="card"><h3>最优参数逐年（含 2026）</h3>
<table><thead><tr><th>年</th><th>OOS策略%</th><th>OOS超额%</th><th>全池%</th><th>vs全池</th><th>夏普</th><th>回撤</th><th>跑赢持有</th></tr></thead>
<tbody>{rows_wf}</tbody></table></div>
<div class="card"><h3>各年入选名单</h3>{''.join(pick_blocks)}</div>
</div></body></html>"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = build_year_panel(force=False)
    panel = panel[panel["mainboard"] == 1].copy()
    scored = add_scores(panel)
    scored.to_parquet(OUT / "year_scored.parquet", index=False)

    print("网格搜索选股信号...")
    grid = grid_search(scored)
    grid.to_csv(OUT / "grid_results.csv", index=False, float_format="%.4f")
    print(grid.head(12).to_string(index=False))

    best = grid.iloc[0].to_dict()
    sig = str(best["signal"])
    k = int(best["top_k"])
    ms = None if best["min_sharpe"] == "" else float(best["min_sharpe"])
    mt = int(best["min_trades"])

    wf_all = walk_forward(
        scored, sig, k, min_sharpe=ms, min_trades=mt,
        fit_years=[2020, 2021, 2022, 2023, 2024, 2025],
    )
    wf_all.to_csv(OUT / "best_walkforward.csv", index=False, float_format="%.4f")
    train = wf_all[wf_all["oos_year"] <= 2025]
    blind = wf_all[wf_all["oos_year"] == 2026]
    blind_row = blind.iloc[0].to_dict() if len(blind) else {
        "oos_ret": float("nan"), "alpha_vs_univ": float("nan")
    }

    picks_by_year = {}
    for _, r in wf_all.iterrows():
        picks_by_year[str(int(r["fit_year"]))] = r["symbols"]

    # 对照：风格孪生式信号、纯收益
    baselines = {}
    for s in ("score_style", "ret", "excess", "score_esd"):
        w = walk_forward(scored, s, k, min_sharpe=ms, min_trades=mt,
                         fit_years=[2020, 2021, 2022, 2023, 2024, 2025])
        baselines[s] = {
            "train_avg_ret": float(w.loc[w.oos_year <= 2025, "oos_ret"].mean()),
            "train_avg_alpha": float(w.loc[w.oos_year <= 2025, "alpha_vs_univ"].mean()),
            "blind_2026": float(w.loc[w.oos_year == 2026, "oos_ret"].mean()) if (w.oos_year == 2026).any() else float("nan"),
        }

    best_label = (
        f"{sig} · Top{k}"
        + (f" · min夏普≥{ms}" if ms is not None else "")
        + (f" · min成交≥{mt}" if mt else "")
    )
    report = {
        "best_label": best_label,
        "best": best,
        "train_avg_ret": float(train["oos_ret"].mean()) if len(train) else float("nan"),
        "train_avg_alpha": float(train["alpha_vs_univ"].mean()) if len(train) else float("nan"),
        "blind_2026": {
            "oos_ret": float(blind_row.get("oos_ret", float("nan"))),
            "oos_excess": float(blind_row.get("oos_excess", float("nan"))),
            "alpha_vs_univ": float(blind_row.get("alpha_vs_univ", float("nan"))),
            "oos_sharpe": float(blind_row.get("oos_sharpe", float("nan"))),
            "symbols": blind_row.get("symbols", ""),
        },
        "grid_top": grid.head(20).to_dict(orient="records"),
        "best_wf_all": wf_all.to_dict(orient="records"),
        "picks_by_year": picks_by_year,
        "baselines": baselines,
    }
    (OUT / "meta.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_html(report, OUT / "report.html")

    # 更新因子13核心：把最优规则写入 factor13_fit
    md = [
        "# 因子13 · 策略1契合选股 Walk-Forward 报告",
        "",
        f"- **最优：** {best_label}",
        f"- 调参窗（2021–2025 OOS）：年均策略 **{report['train_avg_ret']:.1f}%**，相对全池 **{report['train_avg_alpha']:+.1f}pp**",
        f"- 盲测 2026：策略等权 **{report['blind_2026']['oos_ret']:.1f}%**，相对全池 **{report['blind_2026']['alpha_vs_univ']:+.1f}pp**",
        "",
        "## 信号含义",
        "",
        "|信号|定义|",
        "|---|---|",
        "|ret|上年策略收益|",
        "|sharpe|上年策略夏普|",
        "|excess|上年策略−持有|",
        "|dd_improve|持有回撤−策略回撤|",
        "|score_esd|5×超额分位+3×夏普分位+2×回撤改善分位|",
        "|score_fit|4×超额+3×夏普+2×回撤改善+1×收益|",
        "|score_style|大开大合+突破触及+震幅（旧孪生思路）|",
        "|score_fit_style|fit + 0.5×style|",
        "",
        "## 逐年（最优参数）",
        "",
        "|年|OOS策略%|超额%|全池%|vs全池|夏普|跑赢持有|",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for _, r in wf_all.iterrows():
        md.append(
            f"|{int(r['fit_year'])}→{int(r['oos_year'])}|{r['oos_ret']:.1f}|"
            f"{r['oos_excess']:.1f}|{r['univ_ret']:.1f}|{r['alpha_vs_univ']:.1f}|"
            f"{r['oos_sharpe']:.2f}|{int(r['oos_beat_bh_n'])}/{int(r['n_picks'])}|"
        )
    md += ["", "## 对照基线（同 K/过滤）", ""]
    for s, b in baselines.items():
        md.append(
            f"- {s}: 调参窗均收益 {b['train_avg_ret']:.1f}% / vs全池 {b['train_avg_alpha']:+.1f} / 2026 {b['blind_2026']:.1f}%"
        )
    md += [
        "",
        "## 结论",
        "",
        "- 选股应挂钩**上年策略一实盘契合度**（超额/夏普/回撤改善），而非只抄天通凯盛波动形态。",
        "- 规则：每年末用最优信号打分 → TopK → 下一年等权跑因子1基线。",
        "",
        f"产物：`{OUT}`",
    ]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")

    # 持久化最优规则供 factor13 调用
    rule = {
        "signal": sig,
        "top_k": k,
        "min_sharpe": ms,
        "min_trades": mt,
        "threshold_pct": DEFAULT_THR,
        "mainboard_only": True,
        "timing": "year_t_score_hold_year_t_plus_1",
        "label": best_label,
    }
    (OUT / "best_rule.json").write_text(
        json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== BEST ===", best_label)
    print(wf_all[["fit_year", "oos_year", "oos_ret", "oos_excess", "alpha_vs_univ"]].to_string(index=False))
    print(f"\n盲测2026: {blind_row}")
    print(f"报告 → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
