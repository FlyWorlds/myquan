"""证券板块 · 因子1 多阈值回测：±2% / ±2.5% / ±3%（对称 entry=stop，基线策略）。

- 成分：通达信行业「证券」（sectors/cache/tdx_members_index.json）
- 每只股票拉一次日线，三个阈值同跑
- 每只取超额（策略收益 − 买入持有）最大的阈值；并列取夏普更高
- 默认区间 2020-01-01 至今

用法：
  cd backtest
  python securities_factor1_threshold_sweep.py
  python securities_factor1_threshold_sweep.py --workers 6
  python securities_factor1_threshold_sweep.py --filter-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import BacktestConfig, run_open_break_backtest
from strategy.backtest import metric
from strategy.data import fetch_daily

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "securities_factor1_threshold"
CACHE_DIR = OUT_DIR / "daily_cache"
DETAIL_CSV = OUT_DIR / "multi_pct_detail.csv"
BEST_CSV = OUT_DIR / "multi_pct_best.csv"
EXCESS_CSV = OUT_DIR / "multi_pct_excess.csv"
SUMMARY_TXT = OUT_DIR / "multi_pct_summary.txt"
REPORT_MD = OUT_DIR / "REPORT.md"

TDX_MEMBERS = ROOT.parent / "sectors" / "cache" / "tdx_members_index.json"
SECTOR_KEY = "证券"

START_DATE = "20200101"
INITIAL_CASH = 100_000.0
SHARPE_MIN = 1.0
THRESHOLDS = (0.02, 0.025, 0.03)
BASELINE_PCT = 0.025

# akshare / 历史回测未覆盖时的券商简称兜底
BROKER_NAME_FALLBACK: dict[str, str] = {
    "000686": "东北证券",
    "000712": "锦龙股份",
    "300059": "东方财富",
    "600155": "华创云信",
    "600369": "西南证券",
    "600621": "华鑫股份",
    "600864": "哈投股份",
    "601375": "中原证券",
}


def _to_symbol(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("5", "6")):
        return f"sh{c}"
    return f"sz{c}"


def _load_name_map() -> dict[str, str]:
    """A 股代码 → 简称（本地缓存优先，akshare 补充）。"""
    name_map: dict[str, str] = {}
    abc_csv = ROOT / "universe_abc" / "results.csv"
    if abc_csv.exists():
        df = pd.read_csv(abc_csv, dtype={"code": str})
        for _, r in df.drop_duplicates("code").iterrows():
            name_map[str(r["code"]).zfill(6)] = str(r["name"]).strip()
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        code_col = "code" if "code" in df.columns else df.columns[0]
        name_col = "name" if "name" in df.columns else df.columns[1]
        for _, r in df.iterrows():
            code = str(r[code_col]).zfill(6)
            name_map.setdefault(code, str(r[name_col]).strip())
    except Exception:
        pass
    for code, name in BROKER_NAME_FALLBACK.items():
        name_map.setdefault(code, name)
    return name_map


def load_universe() -> pd.DataFrame:
    if not TDX_MEMBERS.exists():
        raise FileNotFoundError(f"缺少成分缓存: {TDX_MEMBERS}")
    data = json.loads(TDX_MEMBERS.read_text(encoding="utf-8"))
    codes = data.get("行业", {}).get(SECTOR_KEY)
    if not codes:
        raise KeyError(f"tdx_members_index 中无行业「{SECTOR_KEY}」")
    name_map = _load_name_map()
    rows: list[dict] = []
    for c in codes:
        code = str(c).zfill(6)
        rows.append(
            {
                "code": code,
                "name": name_map.get(code, code),
                "symbol": _to_symbol(code),
                "sector": SECTOR_KEY,
            }
        )
    out = pd.DataFrame(rows).drop_duplicates(subset=["code"]).sort_values("code")
    print(f"证券板块成分: {len(out)} 只")
    return out


def _bh_stats(daily: pd.DataFrame) -> tuple[float | None, float | None]:
    if daily is None or daily.empty or "close" not in daily.columns:
        return None, None
    closes = pd.to_numeric(daily["close"], errors="coerce").dropna()
    if closes.empty:
        return None, None
    c0, c1 = float(closes.iloc[0]), float(closes.iloc[-1])
    if c0 <= 0:
        return None, None
    bh_ret = (c1 / c0 - 1.0) * 100.0
    peak = closes.cummax()
    dd = (closes / peak - 1.0) * 100.0
    bh_dd = float(-dd.min()) if not dd.empty else None
    return bh_ret, bh_dd


def backtest_stock_all_pct(row: dict, end_date: str) -> list[dict]:
    code = row["code"]
    name = row["name"]
    symbol = row["symbol"]
    sector = row["sector"]
    cache_path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    out: list[dict] = []

    try:
        daily = fetch_daily(symbol, START_DATE, end_date, cache_path=cache_path)
    except Exception as e:  # noqa: BLE001
        for pct in THRESHOLDS:
            out.append(
                {
                    "code": code,
                    "name": name,
                    "symbol": symbol,
                    "sector": sector,
                    "threshold_pct": pct,
                    "阈值%": round(pct * 100, 1),
                    "ok": 0,
                    "error": f"fetch: {type(e).__name__}: {e}",
                }
            )
        return out

    if daily is None or daily.empty or len(daily) < 60:
        err = f"日线不足({0 if daily is None else len(daily)})"
        for pct in THRESHOLDS:
            out.append(
                {
                    "code": code,
                    "name": name,
                    "symbol": symbol,
                    "sector": sector,
                    "threshold_pct": pct,
                    "阈值%": round(pct * 100, 1),
                    "ok": 0,
                    "error": err,
                    "n_bars": 0 if daily is None else int(len(daily)),
                }
            )
        return out

    bh_ret, bh_dd = _bh_stats(daily)
    n_bars = int(len(daily))

    for pct in THRESHOLDS:
        base: dict = {
            "code": code,
            "name": name,
            "symbol": symbol,
            "sector": sector,
            "threshold_pct": pct,
            "阈值%": round(pct * 100, 1),
            "ok": 0,
            "error": "",
            "n_bars": n_bars,
            "bh_return_pct": bh_ret,
            "bh_max_drawdown_pct": bh_dd,
        }
        try:
            cfg = BacktestConfig(
                symbol=symbol,
                symbol_name=name,
                em_symbol=code,
                threshold_pct=pct,
                start_date=START_DATE,
                end_date=end_date,
                initial_cash=INITIAL_CASH,
                entry_ref="today_open",
                prev_entry_mode="yin_or_small_yang",
                daily_cache=cache_path,
                report_path=None,
            )
            result = run_open_break_backtest(cfg, daily)
            m = result.metrics_df
            strat = float(metric(m, "total_return_pct"))
            dd = float(metric(m, "max_drawdown_pct"))
            sharpe = float(metric(m, "sharpe_ratio"))
            win = float(metric(m, "win_rate"))
            n_tr = int(metric(m, "closed_trade_count"))
            pf = float(metric(m, "profit_factor"))
            excess = None if bh_ret is None else strat - float(bh_ret)
            base.update(
                {
                    "total_return_pct": strat,
                    "max_drawdown_pct": dd,
                    "sharpe_ratio": sharpe,
                    "win_rate": win,
                    "closed_trade_count": n_tr,
                    "profit_factor": pf,
                    "excess_return_pct": excess,
                    "ok": 1,
                }
            )
        except Exception as e:  # noqa: BLE001
            base["error"] = f"{type(e).__name__}: {e}"
            base["traceback"] = traceback.format_exc()[-500:]
        out.append(base)
    return out


def _load_done_codes() -> set[str]:
    if not DETAIL_CSV.exists():
        return set()
    try:
        df = pd.read_csv(DETAIL_CSV, dtype={"code": str})
        if df.empty or "code" not in df.columns:
            return set()
        g = df.groupby(df["code"].astype(str).str.zfill(6))["threshold_pct"].nunique()
        return set(g[g >= len(THRESHOLDS)].index.astype(str))
    except Exception:
        return set()


def _append_detail(rows: list[dict]) -> None:
    if not rows:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    header = not DETAIL_CSV.exists()
    df.to_csv(DETAIL_CSV, mode="a", index=False, header=header, encoding="utf-8-sig")


def pick_best(detail: pd.DataFrame) -> pd.DataFrame:
    ok = detail[detail["ok"] == 1].copy()
    if ok.empty:
        return ok
    ok["code"] = ok["code"].astype(str).str.zfill(6)
    ok["excess_return_pct"] = pd.to_numeric(ok["excess_return_pct"], errors="coerce")
    ok["sharpe_ratio"] = pd.to_numeric(ok["sharpe_ratio"], errors="coerce")
    ok = ok.sort_values(
        ["code", "excess_return_pct", "sharpe_ratio"],
        ascending=[True, False, False],
        na_position="last",
    )
    best = ok.groupby("code", as_index=False).head(1).copy()
    best["有超额"] = best["excess_return_pct"].fillna(-1e18) > 0
    best["拟合_夏普1"] = (best["sharpe_ratio"].fillna(-1) >= SHARPE_MIN) & best["有超额"]
    return best.sort_values(
        ["拟合_夏普1", "sharpe_ratio", "excess_return_pct"],
        ascending=[False, False, False],
        na_position="last",
    )


def _baseline_row(detail: pd.DataFrame, code: str) -> pd.Series | None:
    sub = detail[
        (detail["code"].astype(str).str.zfill(6) == code)
        & (detail["ok"] == 1)
        & (pd.to_numeric(detail["threshold_pct"], errors="coerce") == BASELINE_PCT)
    ]
    if sub.empty:
        return None
    return sub.iloc[0]


def write_outputs(detail: pd.DataFrame) -> pd.DataFrame:
    best = pick_best(detail)
    excess = best[best["有超额"]].copy()

    best.to_csv(BEST_CSV, index=False, encoding="utf-8-sig")
    excess.to_csv(EXCESS_CSV, index=False, encoding="utf-8-sig")

    # 阈值分布
    pct_counts = best["阈值%"].value_counts().sort_index()
    fit = best[best["拟合_夏普1"]]

    lines = [
        f"生成时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        "策略: 因子1（开盘±阈值突破，仅止损，止损当日禁买）",
        f"阈值网格: {[f'±{p*100:.1f}%' for p in THRESHOLDS]}",
        f"区间: {START_DATE} → 今",
        f"板块: 通达信行业·{SECTOR_KEY}（{len(best)} 只有效）",
        f"有超额(策略>持有): {len(excess)} / {len(best)}",
        f"拟合(夏普≥{SHARPE_MIN} 且超额>0): {len(fit)}",
        "",
        "=== 最优阈值分布（按超额最大）===",
    ]
    for pct, n in pct_counts.items():
        lines.append(f"  ±{pct}%: {n} 只")

    lines.append("")
    lines.append("=== 拟合名单（夏普降序）===")
    if fit.empty:
        lines.append("(无)")
    else:
        for _, r in fit.iterrows():
            lines.append(
                f"{r['code']} {r['name']} ±{r['阈值%']}% "
                f"夏普={float(r['sharpe_ratio']):.3f} "
                f"策略={float(r['total_return_pct']):.1f}% "
                f"持有={float(r['bh_return_pct']):.1f}% "
                f"超额={float(r['excess_return_pct']):.1f}% "
                f"回撤={float(r['max_drawdown_pct']):.1f}%"
            )

    lines.append("")
    lines.append("=== 全板块明细（最优阈值，按超额降序）===")
    for _, r in best.sort_values("excess_return_pct", ascending=False).iterrows():
        bl = _baseline_row(detail, str(r["code"]).zfill(6))
        delta = ""
        if bl is not None and float(r["threshold_pct"]) != BASELINE_PCT:
            d_ex = float(r["excess_return_pct"]) - float(bl["excess_return_pct"])
            delta = f" vs±2.5%超额{d_ex:+.1f}%"
        lines.append(
            f"{r['code']} {r['name']} ±{r['阈值%']}% "
            f"夏普={float(r['sharpe_ratio']):.3f} "
            f"策略={float(r['total_return_pct']):.1f}% "
            f"超额={float(r['excess_return_pct']):+.1f}%{delta}"
        )

    SUMMARY_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_report_md(detail, best, excess, fit, pct_counts)
    print("\n".join(lines))
    print(f"\nDETAIL: {DETAIL_CSV}")
    print(f"BEST:   {BEST_CSV}")
    print(f"REPORT: {REPORT_MD}")
    return best


def _write_report_md(
    detail: pd.DataFrame,
    best: pd.DataFrame,
    excess: pd.DataFrame,
    fit: pd.DataFrame,
    pct_counts: pd.Series,
) -> None:
    n_ok = len(best)
    n_excess = len(excess)
    avg_excess = float(best["excess_return_pct"].mean()) if n_ok else 0.0
    avg_sharpe = float(best["sharpe_ratio"].mean()) if n_ok else 0.0

    bl_ok = detail[
        (detail["ok"] == 1)
        & (pd.to_numeric(detail["threshold_pct"], errors="coerce") == BASELINE_PCT)
    ]
    bl_avg_excess = (
        float(bl_ok["excess_return_pct"].mean()) if not bl_ok.empty else None
    )

    md: list[str] = [
        "# 证券板块 · 因子1 阈值扫描报告",
        "",
        f"> 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}  ",
        "> **研究口径，不构成投资建议。**",
        "",
        "## 设定",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 策略 | 因子1：开盘 ± 阈值突破，对称止损，止损当日禁买 |",
        f"| 回测区间 | {START_DATE[:4]}-{START_DATE[4:6]}-{START_DATE[6:]} 至今 |",
        f"| 成分 | 通达信「{SECTOR_KEY}」共 {n_ok} 只有效 |",
        f"| 阈值网格 | ±2.0% / ±2.5% / ±3.0% |",
        f"| 优选规则 | 每票取超额最大；并列取夏普更高 |",
        "",
        "## 板块汇总",
        "",
        f"- 跑赢买入持有：**{n_excess}/{n_ok}**（{100*n_excess/max(n_ok,1):.0f}%）",
        f"- 夏普≥1 且超额>0：**{len(fit)}** 只",
        f"- 优选阈值后板块平均超额：**{avg_excess:+.1f}%**（平均夏普 {avg_sharpe:.2f}）",
    ]
    if bl_avg_excess is not None:
        md.append(
            f"- 若全板块统一用 ±2.5%：平均超额 **{bl_avg_excess:+.1f}%**"
            f"（调阈值后 {'改善' if avg_excess > bl_avg_excess else '未改善'} "
            f"{avg_excess - bl_avg_excess:+.1f} 个百分点）"
        )

    md.extend(["", "### 最优阈值分布", ""])
    for pct, n in pct_counts.items():
        md.append(f"- ±{pct}%：**{n}** 只")
    md.extend(
        [
            "",
            "## 个股表现（优选阈值）",
            "",
            "| 代码 | 名称 | 最优阈值 | 策略收益% | 持有收益% | 超额% | 夏普 | 回撤% | vs±2.5%超额 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for _, r in best.sort_values("excess_return_pct", ascending=False).iterrows():
        code = str(r["code"]).zfill(6)
        bl = _baseline_row(detail, code)
        vs = "—"
        if bl is not None:
            if float(r["threshold_pct"]) == BASELINE_PCT:
                vs = "基线"
            else:
                vs = f"{float(r['excess_return_pct']) - float(bl['excess_return_pct']):+.1f}"
        md.append(
            f"| {code} | {r['name']} | ±{r['阈值%']}% "
            f"| {float(r['total_return_pct']):.1f} "
            f"| {float(r['bh_return_pct']):.1f} "
            f"| {float(r['excess_return_pct']):+.1f} "
            f"| {float(r['sharpe_ratio']):.2f} "
            f"| {float(r['max_drawdown_pct']):.1f} "
            f"| {vs} |"
        )

    md.extend(
        [
            "",
            "## 读法提示",
            "",
            "- **超额** = 策略累计收益 − 同期买入持有；正值表示因子1跑赢了简单持有。",
            "- 证券股波动大、β 高，阈值过窄易频繁止损，过宽则信号稀疏；本扫描用于找「相对持有」更合适的对称阈值。",
            "- 样本为 2020 至今，含牛熊切换；单票结论不宜外推到其它板块。",
            "",
            "*免责声明：以上内容仅供量化研究，不构成任何投资建议。*",
        ]
    )
    REPORT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--filter-only",
        action="store_true",
        help="不回测，仅根据已有 multi_pct_detail.csv 重筛",
    )
    ap.add_argument("--fresh", action="store_true", help="删除旧结果后重跑")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    end_date = dt.date.today().strftime("%Y%m%d")

    if args.fresh:
        for p in (DETAIL_CSV, BEST_CSV, EXCESS_CSV, SUMMARY_TXT, REPORT_MD):
            if p.exists():
                p.unlink()

    if not args.filter_only:
        universe = load_universe()
        done = _load_done_codes()
        todo = [
            row.to_dict()
            for _, row in universe.iterrows()
            if row["code"] not in done
        ]
        print(
            f"阈值 {list(THRESHOLDS)} | 已完成 {len(done)} | "
            f"待跑 {len(todo)} | workers={args.workers}"
        )

        t0 = time.time()
        ok_n = fail_n = 0
        batch: list[dict] = []

        if todo:
            with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
                futs = {
                    ex.submit(backtest_stock_all_pct, row, end_date): row
                    for row in todo
                }
                for i, fut in enumerate(as_completed(futs), 1):
                    row = futs[fut]
                    try:
                        res_list = fut.result()
                    except Exception as e:  # noqa: BLE001
                        res_list = [
                            {
                                "code": row["code"],
                                "name": row["name"],
                                "symbol": row["symbol"],
                                "sector": row["sector"],
                                "threshold_pct": pct,
                                "阈值%": round(pct * 100, 1),
                                "ok": 0,
                                "error": f"FutureError: {e}",
                            }
                            for pct in THRESHOLDS
                        ]

                    stock_ok = any(int(r.get("ok") or 0) == 1 for r in res_list)
                    if stock_ok:
                        ok_n += 1
                    else:
                        fail_n += 1
                        err = res_list[0].get("error", "") if res_list else ""
                        print(f"FAIL {row['code']} {row['name']}: {err}")

                    batch.extend(res_list)
                    if len(batch) >= 30:
                        _append_detail(batch)
                        batch.clear()

                    if i % 5 == 0 or i == len(futs):
                        elapsed = time.time() - t0
                        print(
                            f"[{i}/{len(futs)}] ok={ok_n} fail={fail_n} "
                            f"elapsed={elapsed:.0f}s"
                        )

            if batch:
                _append_detail(batch)

        print(f"回测完成 ok={ok_n} fail={fail_n} 用时 {time.time()-t0:.0f}s")

    if not DETAIL_CSV.exists():
        print("无明细文件，退出")
        return

    detail = pd.read_csv(DETAIL_CSV, dtype={"code": str})
    write_outputs(detail)


if __name__ == "__main__":
    main()
