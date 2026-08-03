"""沪深300+中证500（剔科创/创业）A/B/C 策略批量对比。

A: 今日开盘算买点，阴/小阳后可买
B: 前日小阳时用前日开盘算买点
C: 今日开盘，小阳次日不买（仅阴后买）

日线 + 945 proxy_open（不拉分钟，便于全市场扫描）。
结果可断点续跑。
"""

from __future__ import annotations

import io
import logging
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import BacktestConfig, run_open_break_backtest
from strategy.data import fetch_daily
from strategy.open_break import build_gap_down_945_proxy_map

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "universe_abc"
CACHE_DIR = OUT_DIR / "daily_cache"
RESULT_CSV = OUT_DIR / "results.csv"
SUMMARY_CSV = OUT_DIR / "summary.csv"

VARIANTS = [
    ("A", "today_open", "yin_or_small_yang"),
    ("B", "prev_open_on_small_yang", "yin_or_small_yang"),
    ("C", "today_open", "yin_only"),
]

START = "20200101"
# 进程池：akquant 策略用类属性，线程不安全
WORKERS = 4


def _is_mainboard(code: str) -> bool:
    c = str(code).zfill(6)
    # 创业板 300/301/302；科创板 688/689；北交所 8/4
    if c.startswith(("300", "301", "302", "688", "689", "8", "4")):
        return False
    return True


def _to_sina(code: str, exchange: str = "") -> str:
    c = str(code).zfill(6)
    ex = str(exchange)
    if "上海" in ex or "Shanghai" in ex:
        return f"sh{c}"
    if "深圳" in ex or "Shenzhen" in ex:
        return f"sz{c}"
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    return f"sz{c}"


def load_universe() -> pd.DataFrame:
    rows = []
    for idx_code, idx_name in (("000300", "沪深300"), ("000905", "中证500")):
        url = (
            "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
            f"file/autofile/cons/{idx_code}cons.xls"
        )
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        df = pd.read_excel(io.BytesIO(r.content))
        code_col = [c for c in df.columns if "Constituent Code" in c or "成份券代码" in c][0]
        name_col = [
            c
            for c in df.columns
            if ("Constituent Name" in c or "成份券名称" in c) and "Eng" not in c
        ][0]
        ex_col = [c for c in df.columns if str(c).startswith("交易所Exchange")][0]
        part = pd.DataFrame(
            {
                "code": df[code_col].astype(str).str.zfill(6),
                "name": df[name_col].astype(str),
                "exchange": df[ex_col].astype(str),
                "index": idx_name,
            }
        )
        rows.append(part)
    uni = pd.concat(rows, ignore_index=True)
    uni = uni[uni["code"].map(_is_mainboard)].copy()
    # 同时在两指数极少见；保留首次出现的指数标签
    uni = uni.drop_duplicates(subset=["code"], keep="first")
    uni["symbol"] = [
        _to_sina(c, e) for c, e in zip(uni["code"], uni["exchange"], strict=False)
    ]
    return uni.reset_index(drop=True)


def _metrics(result) -> dict[str, float]:
    m = result.metrics_df
    out: dict[str, float] = {}
    for k in (
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "profit_factor",
        "calmar_ratio",
        "end_market_value",
    ):
        if k in m.index:
            out[k] = float(m.loc[k].iloc[0])
    return out


def load_daily_cached(symbol: str, start: str, end: str) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        # 缓存过期：末行日期早于 end-7 天则刷新
        try:
            last = pd.to_datetime(df["date"]).max()
            if last.tzinfo is not None:
                last = last.tz_convert(None)
            end_ts = pd.to_datetime(end)
            if (end_ts - last).days <= 10:
                return df
        except Exception:
            pass
    df = fetch_daily(symbol, start, end)
    df.to_parquet(path, index=False)
    return df


def backtest_one(row: dict, end: str) -> list[dict]:
    symbol = row["symbol"]
    name = row["name"]
    code = row["code"]
    index = row["index"]
    out_rows: list[dict] = []
    daily = load_daily_cached(symbol, START, end)
    if daily is None or len(daily) < 60:
        raise RuntimeError(f"日线过少: {symbol}")
    gap_map = build_gap_down_945_proxy_map(daily, None, proxy="open")
    for key, entry_ref, prev_mode in VARIANTS:
        cfg = BacktestConfig(
            symbol=symbol,
            symbol_name=name,
            em_symbol=code,
            threshold_pct=0.025,
            start_date=START,
            end_date=end,
            enable_gap945=True,
            gap945_use_proxy=True,
            gap945_proxy="open",
            entry_ref=entry_ref,
            prev_entry_mode=prev_mode,
            report_path=None,
        )
        result = run_open_break_backtest(cfg, daily, gap_map=gap_map)
        met = _metrics(result)
        out_rows.append(
            {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "variant": key,
                **met,
                "ok": 1,
                "error": "",
            }
        )
    return out_rows


def _done_codes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str)
    if df.empty or "code" not in df.columns:
        return set()
    # 三变体都成功才算完成
    ok = df[df.get("ok", "1").astype(str).isin(["1", "1.0"])]
    counts = ok.groupby("code")["variant"].nunique()
    return set(counts[counts >= 3].index.astype(str).str.zfill(6))


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    header = not path.exists()
    df.to_csv(path, mode="a", header=header, index=False, encoding="utf-8-sig")


def summarize(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["ok"].astype(str).isin(["1", "1.0"])].copy()
    for c in (
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate",
        "closed_trade_count",
        "profit_factor",
        "calmar_ratio",
        "end_market_value",
    ):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    wide = df.pivot_table(
        index=["code", "name", "index"],
        columns="variant",
        values="total_return_pct",
        aggfunc="first",
    ).reset_index()
    for v in ("A", "B", "C"):
        if v not in wide.columns:
            wide[v] = float("nan")
    wide["best_ret"] = wide[["A", "B", "C"]].idxmax(axis=1)
    wide["A_minus_B"] = wide["A"] - wide["B"]
    wide["A_minus_C"] = wide["A"] - wide["C"]

    lines = []
    lines.append("=" * 72)
    lines.append(f"样本数(成功股票)={wide['code'].nunique()}  区间={START}→今  945=proxy_open")
    lines.append("=" * 72)

    # 聚合
    agg_rows = []
    for v in ("A", "B", "C"):
        sub = df[df["variant"] == v]
        agg_rows.append(
            {
                "variant": v,
                "n": len(sub),
                "median_ret": float(sub["total_return_pct"].median()),
                "mean_ret": float(sub["total_return_pct"].mean()),
                "median_sharpe": float(sub["sharpe_ratio"].median()),
                "mean_sharpe": float(sub["sharpe_ratio"].mean()),
                "median_dd": float(sub["max_drawdown_pct"].median()),
                "pct_positive": float((sub["total_return_pct"] > 0).mean() * 100),
                "median_trades": float(sub["closed_trade_count"].median()),
            }
        )
    agg = pd.DataFrame(agg_rows)
    print("\n【截面中位数/均值】")
    print(agg.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print("\n【按收益谁最好（股票数）】")
    print(wide["best_ret"].value_counts().to_string())

    # pairwise
    def beat(a: str, b: str) -> tuple[int, int, int]:
        aa, bb = wide[a], wide[b]
        mask = aa.notna() & bb.notna()
        aw = int((aa[mask] > bb[mask]).sum())
        bw = int((aa[mask] < bb[mask]).sum())
        eq = int((aa[mask] == bb[mask]).sum())
        return aw, bw, eq

    print("\n【收益两两胜场】")
    for a, b in (("A", "B"), ("A", "C"), ("B", "C")):
        aw, bw, eq = beat(a, b)
        print(f"  {a} vs {b}: {a}胜{aw} / {b}胜{bw} / 平{eq}")

    # sharpe best
    sh = df.pivot_table(
        index="code", columns="variant", values="sharpe_ratio", aggfunc="first"
    )
    sh["best"] = sh[["A", "B", "C"]].idxmax(axis=1)
    print("\n【按夏普谁最好】")
    print(sh["best"].value_counts().to_string())

    # by index
    print("\n【分指数：收益中位数】")
    for idx in sorted(wide["index"].dropna().unique()):
        w = wide[wide["index"] == idx]
        print(
            f"  {idx} n={len(w)}  "
            f"A={w['A'].median():.2f}%  B={w['B'].median():.2f}%  C={w['C'].median():.2f}%  "
            f"best={w['best_ret'].value_counts().to_dict()}"
        )

    # overall winner by median ret then median sharpe
    best_med = agg.sort_values(["median_ret", "median_sharpe"], ascending=False).iloc[0]
    print("\n" + "=" * 72)
    print(
        f"结论倾向: {best_med['variant']} "
        f"(收益中位数 {best_med['median_ret']:.2f}%, 夏普中位数 {best_med['median_sharpe']:.3f})"
    )
    print("=" * 72)

    agg.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")
    wide.to_csv(OUT_DIR / "per_stock_returns.csv", index=False, encoding="utf-8-sig")
    print(f"\n明细: {RESULT_CSV}")
    print(f"汇总: {SUMMARY_CSV}")
    print(f"每股收益宽表: {OUT_DIR / 'per_stock_returns.csv'}")
    return agg


def main() -> None:
    import datetime as dt

    end = dt.date.today().strftime("%Y%m%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    uni = load_universe()
    print(f"成分合计(剔科创/创业/北交): {len(uni)}")
    print(uni["index"].value_counts().to_string())

    done = _done_codes(RESULT_CSV)
    todo = uni[~uni["code"].isin(done)].to_dict("records")
    print(f"已完成 {len(done)}，待跑 {len(todo)}，workers={WORKERS}")

    t0 = time.time()
    ok_n = fail_n = 0
    if todo:
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(backtest_one, row, end): row for row in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                row = futs[fut]
                try:
                    rows = fut.result()
                    append_rows(RESULT_CSV, rows)
                    ok_n += 1
                except Exception as e:
                    fail_n += 1
                    append_rows(
                        RESULT_CSV,
                        [
                            {
                                "code": row["code"],
                                "name": row["name"],
                                "symbol": row["symbol"],
                                "index": row["index"],
                                "variant": "A",
                                "ok": 0,
                                "error": f"{type(e).__name__}: {e}",
                            }
                        ],
                    )
                    print(f"FAIL {row['code']} {row['name']}: {e}")
                if i % 10 == 0 or i == len(todo):
                    elapsed = time.time() - t0
                    rate = i / max(elapsed, 1)
                    eta = (len(todo) - i) / max(rate, 1e-6) / 60
                    print(
                        f"进度 {i}/{len(todo)} ok={ok_n} fail={fail_n} "
                        f"用时{elapsed/60:.1f}m ETA~{eta:.1f}m",
                        flush=True,
                    )

    print(f"\n跑批结束 ok={ok_n} fail={fail_n} 总用时{(time.time()-t0)/60:.1f}m")
    if RESULT_CSV.exists():
        summarize(RESULT_CSV)


if __name__ == "__main__":
    main()
