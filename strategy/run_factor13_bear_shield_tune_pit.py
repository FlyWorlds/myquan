"""熊盾 thr* Top3 调参（防过拟合）。

协议：
  · 验证集 VALID = 交易年 2023–2024（选参只用这两年均值收益，夏普次之）
  · 盲测 BLIND = 2025、2026（选参完全不可见）
  · 每个配置仍走 WF：交易年 T 的 thr*/名单只用 ≤T-1
  · 试验次数如实记录（n_trials）

  python strategy/run_factor13_bear_shield_tune_pit.py
"""

from __future__ import annotations

import itertools
import json
import logging
import sys
import warnings
from pathlib import Path
from typing import Any

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

from strategy.factor13_bear_shield import (  # noqa: E402
    DEFAULT_PARAMS,
    PIN_THR,
    _pct_rank,
    _soft_bull_mask,
    build_features,
    build_quarter_features,
    fit_symbol_thresholds,
)
from strategy.run_factor13_bear_shield_wf import (  # noqa: E402
    PANEL,
    Q_PANEL,
    TRADE_YEARS,
    _name_map,
    _nav_stats,
    equal_weight,
    sim_window,
    year_bounds,
)

OUT = _MYQUAN / "backtest" / "factor13_bear_shield_tune_pit"
VALID_YEARS = {2023, 2024}
BLIND_YEARS = {2025, 2026}

# (symbol, thr_rounded, trade_y) -> sim stats+nav
_SIM_CACHE: dict[tuple[str, float, int], dict] = {}


def cached_sim(sym: str, thr: float, trade_y: int) -> dict:
    key = (str(sym).lower(), round(float(thr), 4), int(trade_y))
    if key in _SIM_CACHE:
        return _SIM_CACHE[key]
    start, end = year_bounds(trade_y)
    res = sim_window(sym, thr, start, end)
    _SIM_CACHE[key] = res
    return res


def log(msg: str) -> None:
    print(msg, flush=True)


def grid_configs() -> list[dict[str, Any]]:
    """小网格：自由度可控，避免二次过拟合。"""
    keys = [
        "min_obear_ex",
        "min_obear_ex_floor",
        "min_obear_ret",
        "w_bull_score",
        "stability_pool",
        "stability_min_hits",
        "min_ret_mean",
    ]
    vals = [
        [0.0, 2.0, 5.0],
        [-15.0, -10.0, -5.0],
        [-10.0, -5.0],
        [0.5, 1.0],
        [10, 12, 15],
        [2],  # 保持稳定性，不放开到 1
        [0.0, 5.0],
    ]
    out = []
    for combo in itertools.product(*vals):
        out.append(dict(zip(keys, combo)))
    return out


def precompute_boards(
    panel: pd.DataFrame,
    q_panel: pd.DataFrame,
    fit_ends: list[int],
) -> dict[int, tuple[pd.DataFrame, dict[str, float]]]:
    """每个 fit_end：thr_map + 合并后的宽表（未过滤）。"""
    boards: dict[int, tuple[pd.DataFrame, dict[str, float]]] = {}
    base = {**DEFAULT_PARAMS, "use_per_stock_thr": True, "top_k": 3}
    for ye in fit_ends:
        thr_df = fit_symbol_thresholds(
            panel,
            fit_start_year=2020,
            fit_end_year=ye,
            pin=PIN_THR,
        )
        thr_map = dict(zip(thr_df["symbol"], thr_df["thr"]))
        feat = build_features(panel, fit_end_year=ye, params=base, thr_map=thr_map)
        qf = build_quarter_features(q_panel, fit_end_year=ye, params=base)
        r = feat.merge(qf, on="symbol", how="inner", suffixes=("", "_q"))
        if "name_q" in r.columns:
            r["name"] = r["name"].fillna(r["name_q"])
        boards[ye] = (r, thr_map)
        log(f"  board fit_end={ye}: n={len(r)}")
    return boards


def rank_board(board: pd.DataFrame, p: dict[str, Any], pool: int) -> pd.DataFrame:
    r = board.copy()
    r = r[
        (r["n_obear"] >= int(p["min_obear"]))
        & (r["obear_ret"] >= float(p["min_obear_ret"]))
        & (r["obear_ex"] >= float(p["min_obear_ex"]))
        & (r["obear_ex_min"] >= float(p["min_obear_ex_floor"]))
        & (r["q_n_obear"] >= int(p["min_q_obear"]))
        & (r["q_obear_ex"] >= float(p["min_q_ex"]))
        & _soft_bull_mask(r, p)
    ]
    if r.empty:
        return r
    bull_ret = r["obull_ret"].fillna(r["ret_mean"])
    w = float(p.get("w_bull_score", 0.5))
    r = r.copy()
    r["score"] = (
        3 * _pct_rank(r["obear_ex"])
        + 2 * _pct_rank(r["obear_ret"])
        + 2 * _pct_rank(r["q_obear_ex"])
        + 2 * _pct_rank(r["q_obear_hit"].fillna(0))
        + 2 * _pct_rank(r["obear_ex_min"])
        + w * _pct_rank(r["ret_mean"])
        + w * _pct_rank(bull_ret)
    )
    return r.sort_values("score", ascending=False).head(int(pool)).reset_index(drop=True)


def stable_picks(
    boards: dict[int, tuple[pd.DataFrame, dict[str, float]]],
    fit_end: int,
    p: dict[str, Any],
) -> pd.DataFrame:
    lookback = int(p.get("stability_lookback", 2))
    pool = int(p.get("stability_pool", 12))
    min_hits = int(p.get("stability_min_hits", 2))
    top_k = int(p.get("top_k", 3))
    ends = [y for y in range(fit_end - lookback + 1, fit_end + 1) if y in boards]
    if not ends:
        ends = [fit_end]
    hit: dict[str, int] = {}
    latest = None
    for ye in ends:
        board, _ = boards[ye]
        ranked = rank_board(board, p, pool)
        for s in ranked["symbol"].astype(str).str.lower():
            hit[s] = hit.get(s, 0) + 1
        if ye == fit_end:
            latest = ranked
    if latest is None or latest.empty:
        return pd.DataFrame()
    latest = latest.copy()
    latest["stab_hits"] = latest["symbol"].astype(str).str.lower().map(lambda s: hit.get(s, 0))
    kept = latest[latest["stab_hits"] >= min_hits]
    if kept.empty:
        kept = latest[latest["stab_hits"] >= 1]
    if kept.empty:
        kept = latest
    return kept.sort_values(["score", "stab_hits"], ascending=False).head(top_k).reset_index(drop=True)


def eval_year(
    picks: pd.DataFrame,
    thr_map: dict[str, float],
    trade_y: int,
    name_map: dict[str, str],
) -> tuple[dict, pd.DataFrame]:
    if picks.empty:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan, "n": 0}, pd.DataFrame()
    pin = {str(k).lower(): float(v) for k, v in PIN_THR.items()}
    navs, rows = {}, []
    for _, r in picks.iterrows():
        sym = str(r["symbol"]).lower()
        thr = float(pin[sym]) if sym in pin else float(thr_map.get(sym, 0.025))
        if "thr" in r.index and pd.notna(r["thr"]):
            thr = float(pin[sym]) if sym in pin else float(r["thr"])
        name = str(r.get("name") or name_map.get(sym, sym))
        res = cached_sim(sym, thr, trade_y)
        if not res.get("ok"):
            continue
        navs[sym] = res["nav"]
        rows.append({"symbol": sym, "name": name, "thr": thr, "ret": res["ret"], "mdd": res["mdd"]})
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    st = _nav_stats(port)
    st["n"] = len(rows)
    return st, pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL)
    q_panel = pd.read_parquet(Q_PANEL)
    name_map = _name_map()
    configs = grid_configs()
    n_trials = len(configs)
    log(f"网格 n_trials={n_trials} | VALID={sorted(VALID_YEARS)} | BLIND={sorted(BLIND_YEARS)}")
    log("预计算截面板…")
    fit_ends = sorted({y - 1 for y in TRADE_YEARS})
    boards = precompute_boards(panel, q_panel, fit_ends)

    # attach thr column onto each board from thr_map
    for ye, (b, tm) in list(boards.items()):
        b = b.copy()
        b["thr"] = b["symbol"].astype(str).str.lower().map(lambda s: PIN_THR.get(s, tm.get(s, 0.025)))
        boards[ye] = (b, tm)

    rows = []
    baseline = {**DEFAULT_PARAMS}
    for i, g in enumerate(configs):
        p = {**baseline, **g, "use_per_stock_thr": True, "top_k": 3, "stability_lookback": 2}
        year_rets = {}
        year_mdd = {}
        picks26 = None
        for trade_y in TRADE_YEARS:
            fit_end = trade_y - 1
            if fit_end not in boards:
                continue
            picks = stable_picks(boards, fit_end, p)
            _, thr_map = boards[fit_end]
            st, _ = eval_year(picks, thr_map, trade_y, name_map)
            year_rets[trade_y] = st["ret"]
            year_mdd[trade_y] = st["mdd"]
            if trade_y == 2026:
                picks26 = picks
        valid_rets = [year_rets[y] for y in VALID_YEARS if y in year_rets and pd.notna(year_rets[y])]
        valid_mdds = [year_mdd[y] for y in VALID_YEARS if y in year_mdd and pd.notna(year_mdd[y])]
        blind_rets = {y: year_rets.get(y, np.nan) for y in BLIND_YEARS}
        row = {
            **g,
            "valid_ret": float(np.mean(valid_rets)) if valid_rets else np.nan,
            "valid_mdd": float(np.mean(valid_mdds)) if valid_mdds else np.nan,
            "blind_2025": blind_rets.get(2025, np.nan),
            "blind_2026": blind_rets.get(2026, np.nan),
            "y2023": year_rets.get(2023, np.nan),
            "y2024": year_rets.get(2024, np.nan),
            "y2025": year_rets.get(2025, np.nan),
            "y2026": year_rets.get(2026, np.nan),
        }
        # 验证目标：收益为主，回撤惩罚
        if pd.notna(row["valid_ret"]) and pd.notna(row["valid_mdd"]):
            row["valid_score"] = float(row["valid_ret"]) - 0.25 * float(row["valid_mdd"])
        else:
            row["valid_score"] = np.nan
        rows.append(row)
        if (i + 1) % 20 == 0 or i == 0:
            log(f"  [{i+1}/{n_trials}] valid={row['valid_ret']:+.1f}% blind26={row['blind_2026']:+.1f}%")

    grid = pd.DataFrame(rows).sort_values("valid_score", ascending=False).reset_index(drop=True)
    grid.to_csv(OUT / "grid.csv", index=False, float_format="%.4f")

    best = grid.iloc[0].to_dict()
    # 当前默认在网格中的名次
    def match_default(r) -> bool:
        return (
            abs(float(r["min_obear_ex"]) - 2.0) < 1e-9
            and abs(float(r["min_obear_ex_floor"]) - (-10.0)) < 1e-9
            and abs(float(r["min_obear_ret"]) - (-5.0)) < 1e-9
            and abs(float(r["w_bull_score"]) - 0.5) < 1e-9
            and int(r["stability_pool"]) == 12
            and int(r["stability_min_hits"]) == 2
            and abs(float(r["min_ret_mean"]) - 5.0) < 1e-9
        )

    def_rows = grid[grid.apply(match_default, axis=1)]
    def_rank = int(def_rows.index[0]) + 1 if len(def_rows) else -1

    # 用 best 参数重跑 2026 名单
    best_p = {**DEFAULT_PARAMS, **{k: best[k] for k in grid_configs()[0].keys()}, "top_k": 3, "use_per_stock_thr": True}
    picks = stable_picks(boards, 2025, best_p)
    _, thr_map = boards[2025]
    st26, detail26 = eval_year(picks, thr_map, 2026, name_map)
    if len(picks):
        picks = picks.copy()
        picks["name"] = picks["symbol"].map(lambda s: name_map.get(str(s).lower(), str(s)))
        picks["thr"] = picks.apply(
            lambda r: PIN_THR.get(str(r["symbol"]).lower(), float(r.get("thr", thr_map.get(str(r["symbol"]).lower(), 0.025)))),
            axis=1,
        )
        picks.to_csv(OUT / "picks_best_2026.csv", index=False, float_format="%.4f")
    if len(detail26):
        detail26.to_csv(OUT / "oos_best_2026_detail.csv", index=False, float_format="%.4f")

    # 拼接 best：valid+blind 展示，但标注
    stitch_rets = []
    equity = 1.0
    frames = []
    for trade_y in TRADE_YEARS:
        pk = stable_picks(boards, trade_y - 1, best_p)
        st, _ = eval_year(pk, boards[trade_y - 1][1], trade_y, name_map)
        # need nav — re-sim
        start, end = year_bounds(trade_y)
        navs = {}
        for _, r in pk.iterrows():
            sym = str(r["symbol"]).lower()
            thr = PIN_THR.get(sym, float(r.get("thr", boards[trade_y - 1][1].get(sym, 0.025))))
            res = cached_sim(sym, thr, trade_y)
            if res.get("ok"):
                navs[sym] = res["nav"]
        if not navs:
            continue
        port = equal_weight(navs)
        p = port / float(port.iloc[0]) * equity
        frames.append(p)
        equity = float(p.iloc[-1])
        stitch_rets.append({"year": trade_y, **st})
    stitch_nav = pd.concat(frames) if frames else pd.Series(dtype=float)
    if len(stitch_nav):
        stitch_nav = stitch_nav[~stitch_nav.index.duplicated(keep="last")]
        stitch_st = _nav_stats(stitch_nav)
        stitch_nav.to_csv(OUT / "nav_best_stitch.csv")
    else:
        stitch_st = {}

    meta = {
        "protocol": {
            "valid_years": sorted(VALID_YEARS),
            "blind_years": sorted(BLIND_YEARS),
            "select_metric": "valid_ret - 0.25*valid_mdd",
            "n_trials": n_trials,
            "note": "盲测未参与选参；仍可能存在验证集过拟合，盲测为最终裁判",
        },
        "best_on_valid": {k: best[k] for k in list(grid_configs()[0].keys()) + ["valid_ret", "valid_mdd", "valid_score", "blind_2025", "blind_2026"]},
        "default_rank_on_valid": def_rank,
        "default_row": def_rows.iloc[0].to_dict() if len(def_rows) else {},
        "best_2026_port": st26,
        "stitch": stitch_st,
        "picks_2026": picks[["symbol", "name", "thr", "score"]].to_dict(orient="records") if len(picks) else [],
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # html
    top10 = grid.head(10).copy()
    for c in top10.select_dtypes(include=[float]).columns:
        top10[c] = top10[c].map(lambda x: f"{x:.1f}" if pd.notna(x) else "")
    html = f"""<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8/>
<title>熊盾 thr* Top3 调参（防过拟合）</title>
<style>
body{{font-family:-apple-system,PingFang SC,sans-serif;max-width:980px;margin:32px auto;background:#0f1115;color:#e8eaed;padding:0 16px;line-height:1.55}}
.muted{{color:#9aa3b2}} .good{{color:#3dd68c}} .warn{{color:#e6c07b}}
table{{border-collapse:collapse;width:100%;font-size:12px}} td,th{{border-bottom:1px solid #2a2f3a;padding:5px 6px;text-align:left}}
</style></head><body>
<h1>熊盾 thr* Top3 · 调参（防过拟合）</h1>
<p class=muted>VALID=2023–2024 选参 · BLIND=2025/2026 不参与 · n_trials={n_trials} · WF≤T-1</p>
<p>验证最优 valid={best['valid_ret']:+.1f}% → 盲测 2025 <b>{best['blind_2025']:+.1f}%</b> · 2026 <b class=good>{best['blind_2026']:+.1f}%</b></p>
<p>当前默认在验证榜第 {def_rank} 名；拼接(best) {stitch_st.get('ret', float('nan')):+.1f}%</p>
<p class=warn>若盲测明显差于验证，视为验证过拟合，保留默认或放宽结论。</p>
<h2>验证 Top10 配置</h2>
{top10.to_html(index=False, border=0)}
<h2>Best · 2026 名单</h2>
{(picks[['name','thr','score']].to_html(index=False, border=0) if len(picks) else '<p>空</p>')}
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")

    log("\n======== 结果 ========")
    log(f"n_trials={n_trials}")
    log(f"VALID最优: ret={best['valid_ret']:+.1f}% mdd={best['valid_mdd']:.1f}% score={best['valid_score']:+.1f}")
    log(f"  params: ex={best['min_obear_ex']} floor={best['min_obear_ex_floor']} "
        f"obret={best['min_obear_ret']} wbull={best['w_bull_score']} pool={best['stability_pool']} "
        f"ret_mean>={best['min_ret_mean']}")
    log(f"BLIND: 2025={best['blind_2025']:+.1f}%  2026={best['blind_2026']:+.1f}%")
    log(f"默认配置验证排名: #{def_rank}")
    if len(def_rows):
        d = def_rows.iloc[0]
        log(f"  默认 blind 2025={d['blind_2025']:+.1f}% 2026={d['blind_2026']:+.1f}%")
    log(f"Best拼接: {stitch_st.get('ret', float('nan')):+.1f}%")
    if len(picks):
        log("2026名单: " + "、".join(f"{r['name']}±{float(r['thr'])*100:.1f}%" for _, r in picks.iterrows()))
    log(f"→ {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
