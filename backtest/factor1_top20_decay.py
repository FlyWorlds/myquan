"""策略一·因子1 双口径 Top20 → 次年表现 / 年下滑。

两种选股评分口径（阈值 2%/2.5%/3% 票内择优；截面分位加权 5/3/2）:
  A. calendar（当年）: 仅用评分年 Y 的回测指标打分 → Top20
  B. cum2020（累计）: 用 2020-01-01 ~ Y-12-31 累计回测打分 → Top20

共同前向检验（评估窗口径必须与选股窗一致）:
  A. calendar：选股窗=自然年 Y → 评估窗=自然年 Y+1
  B. cum2020：选股窗=2020→Y → 评估窗=2020→(Y+1)（累计超额对累计超额）
  （2020→2021 … 2025→2026YTD）

输出目录: backtest/factor1_top20_decay/
"""

from __future__ import annotations

import io
import json
import logging
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

logging.disable(logging.CRITICAL)

from strategy import BacktestConfig  # noqa: E402
from strategy.backtest import _metric  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.runner import run_open_break_backtest  # noqa: E402

from backtest.universe_zz500_1000 import (  # noqa: E402
    CACHE_DIR as UNIV_CACHE,
    CSINDEX_CONS_URL,
    _bh_stats,
    _is_mainboard,
    _to_symbol,
)

OUT_DIR = Path(__file__).resolve().parent / "factor1_top20_decay"
CACHE_CAL = OUT_DIR / "year_symbol_threshold_metrics.parquet"
CACHE_CUM = OUT_DIR / "cum2020_symbol_threshold_metrics.parquet"

THRESHOLDS = (0.02, 0.025, 0.03)
YEARS = list(range(2020, 2027))
SELECT_YEARS = list(range(2020, 2026))  # 有次年可评
W_EXCESS = 5.0
W_SHARPE = 3.0
W_DD = 2.0
TOP_N = 20
WORKERS = 8
INITIAL_CASH = 100_000.0
MIN_BARS = 40
ORIGIN = 2020


def load_zz1000_mainboard() -> pd.DataFrame:
    url = CSINDEX_CONS_URL.format(code="000852")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))
    code_col = next(
        c for c in df.columns if "Constituent Code" in str(c) or "成份券代码" in str(c)
    )
    name_col = next(
        c
        for c in df.columns
        if ("Constituent Name" in str(c) or "成份券名称" in str(c)) and "Eng" not in str(c)
    )
    rows = []
    for _, row in df.iterrows():
        c = str(row[code_col]).zfill(6)
        if not _is_mainboard(c):
            continue
        rows.append(
            {"code": c, "name": str(row[name_col]).strip(), "symbol": _to_symbol(c)}
        )
    return pd.DataFrame(rows).drop_duplicates("code")


def _empty_row(
    symbol: str, code: str, name: str, year: int, thr: float, *, mode: str
) -> dict:
    return {
        "mode": mode,
        "symbol": symbol,
        "code": code,
        "name": name,
        "year": year,  # calendar=自然年；cum=累计窗口截止年=选股年
        "threshold_pct": thr,
        "ok": 0,
        "error": "",
        "n_bars": 0,
        "total_return_pct": np.nan,
        "max_drawdown_pct": np.nan,
        "sharpe_ratio": np.nan,
        "bh_return_pct": np.nan,
        "bh_max_drawdown_pct": np.nan,
        "excess_return_pct": np.nan,
        "dd_improve_pct": np.nan,
        "closed_trade_count": np.nan,
    }


def _fill_metrics(out: dict, d: pd.DataFrame, thr: float, code: str, name: str, symbol: str, start: str, end: str) -> dict:
    cfg = BacktestConfig(
        symbol=symbol,
        symbol_name=name,
        em_symbol=code,
        threshold_pct=thr,
        start_date=start,
        end_date=end,
        initial_cash=INITIAL_CASH,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        daily_cache=None,
        report_path=None,
    )
    result = run_open_break_backtest(cfg, d)
    m = result.metrics_df
    strat_ret = _metric(m, "total_return_pct")
    strat_dd = _metric(m, "max_drawdown_pct")
    sharpe = _metric(m, "sharpe_ratio")
    trades = _metric(m, "closed_trade_count")
    bh_ret, bh_dd = _bh_stats(d)
    out.update(
        {
            "ok": 1,
            "total_return_pct": strat_ret,
            "max_drawdown_pct": strat_dd,
            "sharpe_ratio": sharpe,
            "bh_return_pct": bh_ret,
            "bh_max_drawdown_pct": bh_dd,
            "closed_trade_count": trades,
        }
    )
    if strat_ret is not None and bh_ret is not None and not (
        isinstance(strat_ret, float) and np.isnan(strat_ret)
    ):
        out["excess_return_pct"] = float(strat_ret) - float(bh_ret)
    if strat_dd is not None and bh_dd is not None and not (
        isinstance(strat_dd, float) and np.isnan(strat_dd)
    ):
        out["dd_improve_pct"] = float(bh_dd) - float(strat_dd)
    return out


def _run_symbol_calendar(task: dict) -> list[dict]:
    """单票：自然年窗口 × 阈值。"""
    symbol, code, name = task["symbol"], task["code"], task["name"]
    pending = {(int(y), float(t)) for y, t in task["pending"]}
    rows: list[dict] = []
    try:
        cache = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
        daily = fetch_daily(
            symbol,
            "20190101",
            f"{max(y for y, _ in pending)}1231",
            cache_path=cache if cache.exists() else cache,
        )
        if daily is None or daily.empty:
            for y, thr in pending:
                r = _empty_row(symbol, code, name, y, thr, mode="calendar")
                r["error"] = "no_daily"
                rows.append(r)
            return rows
        d_all = daily.copy()
        d_all["d"] = pd.to_datetime(d_all["date"]).dt.tz_convert("Asia/Shanghai")
        for year, thr in sorted(pending):
            out = _empty_row(symbol, code, name, year, thr, mode="calendar")
            try:
                y0 = pd.Timestamp(f"{year}-01-01", tz="Asia/Shanghai")
                y1 = pd.Timestamp(f"{year + 1}-01-01", tz="Asia/Shanghai")
                d = d_all[(d_all["d"] >= y0) & (d_all["d"] < y1)].reset_index(drop=True)
                out["n_bars"] = int(len(d))
                if len(d) < MIN_BARS:
                    out["error"] = f"bars<{MIN_BARS}"
                    rows.append(out)
                    continue
                rows.append(
                    _fill_metrics(
                        out, d, thr, code, name, symbol, f"{year}0101", f"{year}1231"
                    )
                )
            except Exception as e:
                out["error"] = f"{type(e).__name__}: {e}"
                rows.append(out)
        return rows
    except Exception as e:
        for y, thr in pending:
            r = _empty_row(symbol, code, name, y, thr, mode="calendar")
            r["error"] = f"{type(e).__name__}: {e}"
            r["traceback"] = traceback.format_exc()[-400:]
            rows.append(r)
        return rows


def _run_symbol_cum(task: dict) -> list[dict]:
    """单票：2020→截止年 累计窗口 × 阈值。year=截止年=选股年。"""
    symbol, code, name = task["symbol"], task["code"], task["name"]
    pending = {(int(y), float(t)) for y, t in task["pending"]}
    rows: list[dict] = []
    try:
        cache = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
        end_max = max(y for y, _ in pending)
        daily = fetch_daily(
            symbol,
            "20190101",
            f"{end_max}1231",
            cache_path=cache if cache.exists() else cache,
        )
        if daily is None or daily.empty:
            for y, thr in pending:
                r = _empty_row(symbol, code, name, y, thr, mode="cum2020")
                r["error"] = "no_daily"
                rows.append(r)
            return rows
        d_all = daily.copy()
        d_all["d"] = pd.to_datetime(d_all["date"]).dt.tz_convert("Asia/Shanghai")
        origin = pd.Timestamp(f"{ORIGIN}-01-01", tz="Asia/Shanghai")
        for end_year, thr in sorted(pending):
            out = _empty_row(symbol, code, name, end_year, thr, mode="cum2020")
            try:
                y1 = pd.Timestamp(f"{end_year + 1}-01-01", tz="Asia/Shanghai")
                d = d_all[(d_all["d"] >= origin) & (d_all["d"] < y1)].reset_index(drop=True)
                out["n_bars"] = int(len(d))
                min_bars = MIN_BARS * max(1, end_year - ORIGIN + 1) // 2
                min_bars = max(MIN_BARS, min_bars)
                if len(d) < min_bars:
                    out["error"] = f"bars<{min_bars}"
                    rows.append(out)
                    continue
                rows.append(
                    _fill_metrics(
                        out,
                        d,
                        thr,
                        code,
                        name,
                        symbol,
                        f"{ORIGIN}0101",
                        f"{end_year}1231",
                    )
                )
            except Exception as e:
                out["error"] = f"{type(e).__name__}: {e}"
                rows.append(out)
        return rows
    except Exception as e:
        for y, thr in pending:
            r = _empty_row(symbol, code, name, y, thr, mode="cum2020")
            r["error"] = f"{type(e).__name__}: {e}"
            r["traceback"] = traceback.format_exc()[-400:]
            rows.append(r)
        return rows


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def build_selection_table(metrics: pd.DataFrame, mode: str) -> pd.DataFrame:
    """每年每票取最优阈值，再算截面评分。year=选股年。"""
    ok = metrics[metrics["ok"] == 1].copy()
    if ok.empty:
        return ok
    rows = []
    for (_, _), g in ok.groupby(["year", "symbol"]):
        g = g.copy()
        for col in ("excess_return_pct", "sharpe_ratio", "dd_improve_pct"):
            v = g[col].astype(float)
            if v.nunique() <= 1 or float(v.std(ddof=0) or 0) == 0:
                g[f"r_{col}"] = 0.5
            else:
                g[f"r_{col}"] = (v - v.min()) / (v.max() - v.min())
        g["thr_score"] = (
            W_EXCESS * g["r_excess_return_pct"]
            + W_SHARPE * g["r_sharpe_ratio"]
            + W_DD * g["r_dd_improve_pct"]
        )
        rows.append(g.loc[g["thr_score"].idxmax()])
    best_per = pd.DataFrame(rows)
    out_parts = []
    for _, g in best_per.groupby("year"):
        g = g.copy()
        g["pct_excess"] = _pct_rank(g["excess_return_pct"].astype(float))
        g["pct_sharpe"] = _pct_rank(g["sharpe_ratio"].astype(float))
        g["pct_dd"] = _pct_rank(g["dd_improve_pct"].astype(float))
        g["score"] = (
            W_EXCESS * g["pct_excess"]
            + W_SHARPE * g["pct_sharpe"]
            + W_DD * g["pct_dd"]
        )
        g = g.sort_values("score", ascending=False)
        g["rank"] = range(1, len(g) + 1)
        g["score_mode"] = mode
        out_parts.append(g)
    return pd.concat(out_parts, ignore_index=True)


def ensure_pool(
    univ: pd.DataFrame,
    years: list[int],
    cache_path: Path,
    worker,
    mode: str,
    force: bool = False,
) -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done: set[tuple] = set()
    existing = pd.DataFrame()
    if cache_path.exists() and not force:
        existing = pd.read_parquet(cache_path)
        for _, r in existing.iterrows():
            done.add((r["symbol"], int(r["year"]), float(r["threshold_pct"])))
        print(f"[{mode}] 已缓存: {len(done)}")

    pending_by_sym: dict[str, list[tuple[int, float]]] = {}
    meta: dict[str, dict] = {}
    for _, row in univ.iterrows():
        sym = row["symbol"]
        meta[sym] = {"code": row["code"], "name": row["name"], "symbol": sym}
        for y in years:
            for thr in THRESHOLDS:
                if (sym, y, float(thr)) in done:
                    continue
                pending_by_sym.setdefault(sym, []).append((y, float(thr)))

    tasks = [
        {**meta[sym], "pending": pending}
        for sym, pending in pending_by_sym.items()
    ]
    total = sum(len(t["pending"]) for t in tasks)
    print(f"[{mode}] 待跑股票 {len(tasks)} / 组合 {total}")
    if not tasks:
        return existing

    t0 = time.time()
    new_rows: list[dict] = []
    finished = 0
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(worker, t): t for t in tasks}
        for fut in as_completed(futs):
            finished += 1
            new_rows.extend(fut.result())
            if finished % 20 == 0 or finished == len(tasks):
                print(
                    f"  [{mode}] {finished}/{len(tasks)}  "
                    f"(+{len(new_rows)}行, {time.time()-t0:.0f}s)"
                )
                part = pd.DataFrame(new_rows)
                merged = (
                    pd.concat([existing, part], ignore_index=True)
                    if len(existing)
                    else part
                )
                merged = merged.drop_duplicates(
                    ["symbol", "year", "threshold_pct"], keep="last"
                )
                merged.to_parquet(cache_path, index=False)
                existing = merged
                new_rows = []
    if new_rows:
        part = pd.DataFrame(new_rows)
        existing = (
            pd.concat([existing, part], ignore_index=True) if len(existing) else part
        )
        existing = existing.drop_duplicates(
            ["symbol", "year", "threshold_pct"], keep="last"
        )
        existing.to_parquet(cache_path, index=False)
    print(f"[{mode}] 完成 {len(existing)} 行 → {cache_path}")
    return existing


def analyze_forward(
    selection: pd.DataFrame,
    eval_metrics: pd.DataFrame,
    mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top20「次年」表现：评估窗口径与选股窗一致。

    calendar → eval_metrics 为自然年表，取 year=Y+1
    cum2020  → eval_metrics 为累计表，取 year=Y+1 表示窗口 2020→(Y+1)
    """
    fwd_rows = []
    summary_rows = []
    for y in SELECT_YEARS:
        top = selection[(selection["year"] == y) & (selection["rank"] <= TOP_N)].copy()
        if top.empty:
            continue
        next_y = y + 1
        stock_fwd = []
        for _, r in top.iterrows():
            m = eval_metrics[
                (eval_metrics["symbol"] == r["symbol"])
                & (eval_metrics["year"] == next_y)
                & (np.isclose(eval_metrics["threshold_pct"], float(r["threshold_pct"])))
            ]
            row = {
                "score_mode": mode,
                "select_year": y,
                "eval_year": next_y,
                "select_window": f"{y}" if mode == "calendar" else f"2020-{y}",
                "eval_window": f"{next_y}" if mode == "calendar" else f"2020-{next_y}",
                "rank_select": int(r["rank"]),
                "symbol": r["symbol"],
                "code": r["code"],
                "name": r["name"],
                "threshold_pct": float(r["threshold_pct"]),
                "select_score": float(r["score"]),
                "select_excess": float(r["excess_return_pct"]),
                "select_sharpe": float(r["sharpe_ratio"]),
                "select_dd_improve": float(r["dd_improve_pct"]),
                "select_ret": float(r["total_return_pct"]),
            }
            if m.empty or int(m.iloc[0]["ok"]) != 1:
                row.update(
                    {
                        "ok": 0,
                        "fwd_ret": np.nan,
                        "fwd_sharpe": np.nan,
                        "fwd_excess": np.nan,
                        "fwd_dd_improve": np.nan,
                        "fwd_bh_ret": np.nan,
                        "fwd_dd": np.nan,
                    }
                )
            else:
                mm = m.iloc[0]
                row.update(
                    {
                        "ok": 1,
                        "fwd_ret": float(mm["total_return_pct"]),
                        "fwd_sharpe": float(mm["sharpe_ratio"]),
                        "fwd_excess": float(mm["excess_return_pct"]),
                        "fwd_dd_improve": float(mm["dd_improve_pct"]),
                        "fwd_bh_ret": float(mm["bh_return_pct"]),
                        "fwd_dd": float(mm["max_drawdown_pct"]),
                    }
                )
            stock_fwd.append(row)
            fwd_rows.append(row)

        dfy = pd.DataFrame(stock_fwd)
        ok = dfy[dfy["ok"] == 1]
        univ_next = eval_metrics[
            (eval_metrics["year"] == next_y) & (eval_metrics["ok"] == 1)
        ]
        univ25 = univ_next[np.isclose(univ_next["threshold_pct"], 0.025)]

        def _mean(s):
            return float(np.nanmean(s)) if len(s) else np.nan

        summary_rows.append(
            {
                "score_mode": mode,
                "select_year": y,
                "eval_year": next_y,
                "select_window": f"{y}" if mode == "calendar" else f"2020-{y}",
                "eval_window": f"{next_y}" if mode == "calendar" else f"2020-{next_y}",
                "n_top": len(dfy),
                "n_ok": int(ok["ok"].sum()) if len(ok) else 0,
                "top20_score_mean": _mean(dfy["select_score"]),
                "fwd_ret_mean": _mean(ok["fwd_ret"]),
                "fwd_sharpe_mean": _mean(ok["fwd_sharpe"]),
                "fwd_excess_mean": _mean(ok["fwd_excess"]),
                "fwd_dd_improve_mean": _mean(ok["fwd_dd_improve"]),
                "fwd_bh_mean": _mean(ok["fwd_bh_ret"]),
                "select_ret_mean": _mean(dfy["select_ret"]),
                "select_excess_mean": _mean(dfy["select_excess"]),
                "select_sharpe_mean": _mean(dfy["select_sharpe"]),
                "univ_ret_mean_2.5": _mean(univ25["total_return_pct"]),
                "univ_excess_mean_2.5": _mean(univ25["excess_return_pct"]),
                "univ_sharpe_mean_2.5": _mean(univ25["sharpe_ratio"]),
                "ret_decay": _mean(ok["fwd_ret"]) - _mean(dfy["select_ret"]),
                "excess_decay": _mean(ok["fwd_excess"]) - _mean(dfy["select_excess"]),
                "sharpe_decay": _mean(ok["fwd_sharpe"]) - _mean(dfy["select_sharpe"]),
                "beat_bh_ratio": float((ok["fwd_excess"] > 0).mean()) if len(ok) else np.nan,
                "overlap_next_top20": np.nan,
            }
        )

    return pd.DataFrame(fwd_rows), pd.DataFrame(summary_rows)


def fill_overlap(summary: pd.DataFrame, selection: pd.DataFrame) -> pd.DataFrame:
    s = summary.copy()
    overlaps = []
    for _, row in s.iterrows():
        y = int(row["select_year"])
        a = set(
            selection[(selection["year"] == y) & (selection["rank"] <= TOP_N)]["code"]
        )
        b = set(
            selection[(selection["year"] == y + 1) & (selection["rank"] <= TOP_N)]["code"]
        )
        overlaps.append(len(a & b) if b else np.nan)
    s["overlap_next_top20"] = overlaps
    return s


def main() -> None:
    print("加载中证1000主板…")
    univ = load_zz1000_mainboard()
    print(f"成分: {len(univ)}")

    # A: 自然年（含 2026，用于评估与当年榜）
    cal = ensure_pool(
        univ, YEARS, CACHE_CAL, _run_symbol_calendar, "calendar", force=False
    )
    # B: 累计到选股年（含 2026 榜）
    cum = ensure_pool(
        univ, YEARS, CACHE_CUM, _run_symbol_cum, "cum2020", force=False
    )

    sel_cal = build_selection_table(cal, "calendar")
    sel_cum = build_selection_table(cum, "cum2020")

    top_cal = sel_cal[sel_cal["rank"] <= TOP_N].copy()
    top_cum = sel_cum[sel_cum["rank"] <= TOP_N].copy()
    top_cal.to_csv(OUT_DIR / "top20_calendar_by_year.csv", index=False, encoding="utf-8-sig")
    top_cum.to_csv(OUT_DIR / "top20_cum2020_by_year.csv", index=False, encoding="utf-8-sig")
    # 兼容旧文件名 = 当年口径
    top_cal.to_csv(OUT_DIR / "top20_by_year.csv", index=False, encoding="utf-8-sig")

    # 评估窗口径与选股一致：当年→下一年；累计→拉长一年的累计窗
    fwd_cal, sum_cal = analyze_forward(sel_cal, cal, "calendar")
    fwd_cum, sum_cum = analyze_forward(sel_cum, cum, "cum2020")
    sum_cal = fill_overlap(sum_cal, sel_cal)
    sum_cum = fill_overlap(sum_cum, sel_cum)

    fwd = pd.concat([fwd_cal, fwd_cum], ignore_index=True)
    summary = pd.concat([sum_cal, sum_cum], ignore_index=True)
    fwd.to_csv(OUT_DIR / "forward_year_performance.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT_DIR / "decay_summary.csv", index=False, encoding="utf-8-sig")

    # 名单重叠：当年 vs 累计
    overlap_modes = []
    for y in YEARS:
        a = set(top_cal[top_cal["year"] == y]["code"])
        b = set(top_cum[top_cum["year"] == y]["code"])
        overlap_modes.append(
            {
                "year": y,
                "n_overlap_calendar_vs_cum": len(a & b),
                "codes": sorted(a & b),
            }
        )
    pd.DataFrame(overlap_modes).to_csv(
        OUT_DIR / "top20_mode_overlap.csv", index=False, encoding="utf-8-sig"
    )

    print("\n===== 当年口径 calendar：自然年Y → 自然年Y+1 =====")
    cols = [
        "select_year",
        "eval_year",
        "select_window",
        "eval_window",
        "select_excess_mean",
        "fwd_excess_mean",
        "excess_decay",
        "select_sharpe_mean",
        "fwd_sharpe_mean",
        "sharpe_decay",
        "beat_bh_ratio",
        "overlap_next_top20",
    ]
    print(sum_cal[cols].to_string(index=False))
    print("\n===== 累计口径 cum2020：2020→Y → 2020→(Y+1) =====")
    print(sum_cum[cols].to_string(index=False))
    print("\n===== 同年两种 Top20 名单重叠 =====")
    print(pd.DataFrame(overlap_modes)[["year", "n_overlap_calendar_vs_cum"]].to_string(index=False))

    payload = {
        "weights": {"excess_return": W_EXCESS, "sharpe": W_SHARPE, "dd_improve": W_DD},
        "thresholds": list(THRESHOLDS),
        "top_n": TOP_N,
        "universe_n": int(len(univ)),
        "modes": {
            "calendar": "仅用评分年自然年回测打分",
            "cum2020": "用 2020 至评分年累计回测打分",
        },
        "summary_calendar": sum_cal.to_dict(orient="records"),
        "summary_cum2020": sum_cum.to_dict(orient="records"),
        "mode_overlap": overlap_modes,
        "top20_calendar": {
            str(int(y)): g[
                [
                    "rank",
                    "code",
                    "name",
                    "threshold_pct",
                    "score",
                    "total_return_pct",
                    "excess_return_pct",
                    "sharpe_ratio",
                ]
            ].to_dict(orient="records")
            for y, g in top_cal.groupby("year")
        },
        "top20_cum2020": {
            str(int(y)): g[
                [
                    "rank",
                    "code",
                    "name",
                    "threshold_pct",
                    "score",
                    "total_return_pct",
                    "excess_return_pct",
                    "sharpe_ratio",
                ]
            ].to_dict(orient="records")
            for y, g in top_cum.groupby("year")
        },
    }
    (OUT_DIR / "decay_report_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n报告数据: {OUT_DIR / 'decay_report_data.json'}")


if __name__ == "__main__":
    main()
