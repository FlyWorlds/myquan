"""中证500+中证1000 因子1 多阈值回测：±2% / ±2.5% / ±3%。

- 剔除科创板（688/689）、创业板（300/301）、北交所
- 每只股票拉一次日线，三个阈值同跑
- 有超额（策略收益 > 买入持有）的纳入候选；每只取超额最大的阈值
- 盯盘池默认再要求夏普≥1（与历史口径一致）；全量超额名单另存

用法：
  cd backtest
  python universe_zz500_1000_multi_pct.py
  python universe_zz500_1000_multi_pct.py --workers 6
  python universe_zz500_1000_multi_pct.py --apply-watch   # 写回 watch_config
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import BacktestConfig, run_open_break_backtest
from strategy.backtest import metric
from strategy.data import fetch_daily

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "universe_zz500_1000"
CACHE_DIR = OUT_DIR / "daily_cache"
DETAIL_CSV = OUT_DIR / "multi_pct_detail.csv"
BEST_CSV = OUT_DIR / "multi_pct_best.csv"
EXCESS_CSV = OUT_DIR / "multi_pct_excess.csv"
FIT_CSV = OUT_DIR / "fit_sharpe1_excess.csv"
SUMMARY_TXT = OUT_DIR / "multi_pct_summary.txt"
WATCH_CONFIG = ROOT.parent / "holdingStocks" / "watch_config.py"

START_DATE = "20200101"
INITIAL_CASH = 100_000.0
SHARPE_MIN = 1.0
THRESHOLDS = (0.02, 0.025, 0.03)

INDEXES = [
    ("000905", "中证500"),
    ("000852", "中证1000"),
]

CSINDEX_CONS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/{code}cons.xls"
)


def _is_mainboard(code: str) -> bool:
    c = str(code).zfill(6)
    if c.startswith(("688", "689", "300", "301")):
        return False
    if c.startswith(("8", "4")):
        return False
    return True


def _to_symbol(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("5", "6")):
        return f"sh{c}"
    return f"sz{c}"


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


def load_universe(*, drop_non_mainboard: bool = True) -> pd.DataFrame:
    rows: list[dict] = []
    seen: set[str] = set()
    for code, index_name in INDEXES:
        url = CSINDEX_CONS_URL.format(code=code)
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        df = pd.read_excel(io.BytesIO(r.content))
        code_col = next(
            c
            for c in df.columns
            if "Constituent Code" in str(c) or "成份券代码" in str(c)
        )
        name_col = next(
            c
            for c in df.columns
            if ("Constituent Name" in str(c) or "成份券名称" in str(c))
            and "Eng" not in str(c)
        )
        for _, row in df.iterrows():
            c = str(row[code_col]).zfill(6)
            if c in seen:
                continue
            if drop_non_mainboard and not _is_mainboard(c):
                continue
            seen.add(c)
            rows.append(
                {
                    "code": c,
                    "name": str(row[name_col]).strip(),
                    "symbol": _to_symbol(c),
                    "index": index_name,
                }
            )
    out = pd.DataFrame(rows)
    print(f"成分合计(剔科创/创业/北交): {len(out)}")
    print(out["index"].value_counts().to_string())
    if drop_non_mainboard:
        print("(已剔除科创板、创业板、北交所)")
    return out


def backtest_stock_all_pct(row: dict, end_date: str) -> list[dict]:
    """一只股票：一次日线 + 三个阈值。"""
    code = row["code"]
    name = row["name"]
    symbol = row["symbol"]
    index_name = row["index"]
    cache_path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    out: list[dict] = []

    try:
        daily = fetch_daily(
            symbol,
            START_DATE,
            end_date,
            cache_path=cache_path,
        )
    except Exception as e:  # noqa: BLE001
        for pct in THRESHOLDS:
            out.append(
                {
                    "code": code,
                    "name": name,
                    "symbol": symbol,
                    "index": index_name,
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
                    "index": index_name,
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
            "index": index_name,
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
        # 一只股票三个阈值都齐才算完成
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
    """每只股票在 ok 结果中取超额最大；并列取夏普更高。"""
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


def write_outputs(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    best = pick_best(detail)
    excess = best[best["有超额"]].copy()
    fit = best[best["拟合_夏普1"]].copy()

    best.to_csv(BEST_CSV, index=False, encoding="utf-8-sig")
    excess.to_csv(EXCESS_CSV, index=False, encoding="utf-8-sig")
    # 兼容旧路径：夏普≥1 且超额>0
    fit_out = fit.rename(
        columns={
            "total_return_pct": "total_return_pct",
            "excess_return_pct": "excess_return_pct",
        }
    )
    fit_out.to_csv(FIT_CSV, index=False, encoding="utf-8-sig")

    lines = [
        f"生成时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        "策略: 策略一·因子1（开盘突破仅止损）",
        f"阈值网格: {[f'±{p*100:.1f}%' for p in THRESHOLDS]}",
        f"区间: {START_DATE} → 今",
        "池子: 中证500+中证1000，剔除科创板",
        f"明细行: {len(detail)}  股票最佳: {len(best)}",
        f"有超额(策略>持有): {len(excess)}",
        f"拟合(夏普≥{SHARPE_MIN} 且超额>0): {len(fit)}",
        "",
        "=== 拟合名单（夏普降序）===",
    ]
    if fit.empty:
        lines.append("(无)")
    else:
        for _, r in fit.iterrows():
            lines.append(
                f"{r['code']} {r['name']} [{r['index']}] ±{r['阈值%']}% "
                f"夏普={float(r['sharpe_ratio']):.3f} "
                f"策略={float(r['total_return_pct']):.1f}% "
                f"持有={float(r['bh_return_pct']):.1f}% "
                f"超额={float(r['excess_return_pct']):.1f}% "
                f"回撤={float(r['max_drawdown_pct']):.1f}%"
            )
    lines.append("")
    lines.append("=== 有超额但夏普<1（按超额降序，前 30）===")
    weak = excess[~excess["拟合_夏普1"]].sort_values(
        "excess_return_pct", ascending=False
    )
    if weak.empty:
        lines.append("(无)")
    else:
        for _, r in weak.head(30).iterrows():
            lines.append(
                f"{r['code']} {r['name']} ±{r['阈值%']}% "
                f"夏普={float(r['sharpe_ratio']):.3f} "
                f"超额={float(r['excess_return_pct']):.1f}%"
            )

    SUMMARY_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nDETAIL: {DETAIL_CSV}")
    print(f"BEST:   {BEST_CSV}")
    print(f"EXCESS: {EXCESS_CSV}")
    print(f"FIT:    {FIT_CSV}")
    print(f"SUMMARY:{SUMMARY_TXT}")
    return best, excess, fit


def apply_watch(fit: pd.DataFrame, *, also_excess_only: bool = False) -> None:
    """把拟合名单写回 holdingStocks/watch_config.py。

    also_excess_only=True：纳入全部有超额（含夏普<1）；默认只用夏普≥1且超额>0。
    """
    src = fit if not also_excess_only else fit  # caller passes the right frame
    if src.empty:
        print("无标的可写入 watch_config")
        return

    # 排序：夏普降序
    src = src.sort_values("sharpe_ratio", ascending=False)
    pairs: list[tuple[str, str]] = []
    pct_map: dict[str, float] = {}
    for _, r in src.iterrows():
        code = str(r["code"]).zfill(6)
        name = str(r["name"]).strip()
        pairs.append((code, name))
        pct = float(r["threshold_pct"])
        # 默认 2.5% 不写进覆盖表；其它写入
        if abs(pct - 0.025) > 1e-9:
            pct_map[code] = pct

    fit_block_lines = ["_FIT_WATCH: list[tuple[str, str]] = ["]
    for code, name in pairs:
        fit_block_lines.append(f'    ("{code}", "{name}"),')
    fit_block_lines.append("]")
    fit_block = "\n".join(fit_block_lines)

    pct_lines = ["_WATCH_PCT: dict[str, float] = {"]
    for code, pct in sorted(pct_map.items(), key=lambda x: (-x[1], x[0])):
        pct_lines.append(f'    "{code}": {pct},  # ±{pct*100:.1f}%')
    pct_lines.append("}")
    pct_block = "\n".join(pct_lines)

    text = WATCH_CONFIG.read_text(encoding="utf-8")
    text2, n1 = re.subn(
        r"_FIT_WATCH: list\[tuple\[str, str\]\] = \[[\s\S]*?\]",
        fit_block,
        text,
        count=1,
    )
    text3, n2 = re.subn(
        r"_WATCH_PCT: dict\[str, float\] = \{[\s\S]*?\}",
        pct_block,
        text2,
        count=1,
    )
    if n1 != 1 or n2 != 1:
        raise RuntimeError(f"watch_config 替换失败 n_fit={n1} n_pct={n2}")
    # 更新注释
    text3 = re.sub(
        r"# 中证500\+1000 契合池.*",
        f"# 中证500+1000 契合池（夏普≥{SHARPE_MIN} 且超额>0，剔科创/创业；多阈值优选，按夏普降序）",
        text3,
        count=1,
    )
    text3 = re.sub(
        r"# 明细：.*",
        "# 明细：../backtest/universe_zz500_1000/fit_sharpe1_excess.csv / multi_pct_excess.csv",
        text3,
        count=1,
    )
    WATCH_CONFIG.write_text(text3, encoding="utf-8")
    print(f"已写入 {WATCH_CONFIG}：{len(pairs)} 只，阈值覆盖 {len(pct_map)} 只")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--apply-watch",
        action="store_true",
        help="把夏普≥1且超额>0 的名单写回 watch_config",
    )
    ap.add_argument(
        "--apply-all-excess",
        action="store_true",
        help="把全部有超额的名单写回 watch_config（含夏普<1）",
    )
    ap.add_argument(
        "--filter-only",
        action="store_true",
        help="不回测，仅根据已有 multi_pct_detail.csv 重筛",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    end_date = dt.date.today().strftime("%Y%m%d")

    if not args.filter_only:
        universe = load_universe(drop_non_mainboard=True)
        done = _load_done_codes()
        todo = [
            row.to_dict()
            for _, row in universe.iterrows()
            if row["code"] not in done
        ]
        print(
            f"阈值 {list(THRESHOLDS)} | 已完成股票 {len(done)} | "
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
                                "index": row["index"],
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

                    if i % 10 == 0 or i == len(todo):
                        elapsed = (time.time() - t0) / 60.0
                        rate = i / max(elapsed, 1e-6)
                        eta = (len(todo) - i) / max(rate, 1e-6)
                        print(
                            f"进度 {i}/{len(todo)} ok股={ok_n} fail股={fail_n} "
                            f"用时{elapsed:.1f}m ETA~{eta:.1f}m",
                            flush=True,
                        )

            if batch:
                _append_detail(batch)

    if not DETAIL_CSV.exists():
        print("无 multi_pct_detail.csv")
        return

    detail = pd.read_csv(DETAIL_CSV, dtype={"code": str})
    detail["code"] = detail["code"].astype(str).str.zfill(6)
    _, excess, fit = write_outputs(detail)

    if args.apply_all_excess:
        apply_watch(excess, also_excess_only=True)
    elif args.apply_watch:
        apply_watch(fit)


if __name__ == "__main__":
    main()
