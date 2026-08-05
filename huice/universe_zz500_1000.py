"""中证500+中证1000（剔科创/创业/北交）OpenBreak3 A 策略批量回测。

策略锁定 A：今日开盘算买点，阴/小阳后可买，仅 −2.5% 止损。
对比买入持有收益与最大回撤；结果可断点续跑。
"""

from __future__ import annotations

import datetime as dt
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

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "universe_zz500_1000"
CACHE_DIR = OUT_DIR / "daily_cache"
RESULT_CSV = OUT_DIR / "results.csv"
FIT_CSV = OUT_DIR / "fit_sharpe1_excess.csv"
TOP50_CSV = OUT_DIR / "top50_excess.csv"
SUMMARY_TXT = OUT_DIR / "summary.txt"

# 进程池：akquant 策略用类属性，线程不安全
WORKERS = 4
START_DATE = "20200101"
THRESHOLD_PCT = 0.025
INITIAL_CASH = 100_000.0
SHARPE_MIN = 1.0

INDEXES = [
    ("000905", "中证500"),
    ("000852", "中证1000"),
]

CSINDEX_CONS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/{code}cons.xls"
)

METRIC_KEYS = [
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "win_rate",
    "closed_trade_count",
    "profit_factor",
    "calmar_ratio",
    "end_market_value",
]

RESULT_COLS = [
    "code",
    "name",
    "symbol",
    "index",
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "win_rate",
    "closed_trade_count",
    "profit_factor",
    "calmar_ratio",
    "end_market_value",
    "bh_return_pct",
    "bh_max_drawdown_pct",
    "excess_return_pct",
    "dd_improve_pct",
    "n_bars",
    "ok",
    "error",
]


def _is_mainboard(code: str) -> bool:
    c = str(code).zfill(6)
    if c.startswith(("688", "689")):  # 科创板
        return False
    if c.startswith(("300", "301")):  # 创业板
        return False
    if c.startswith(("8", "4")):  # 北交所
        return False
    return True


def _to_symbol(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("5", "6")):
        return f"sh{c}"
    return f"sz{c}"


def _metric(m: pd.DataFrame, key: str) -> float | None:
    if key not in m.index:
        return None
    try:
        return float(m.loc[key].iloc[0])
    except Exception:
        return None


def _bh_stats(daily: pd.DataFrame) -> tuple[float | None, float | None]:
    """买入持有累计收益% 与收盘价最大回撤%。"""
    if daily is None or daily.empty or "close" not in daily.columns:
        return None, None
    closes = pd.to_numeric(daily["close"], errors="coerce").dropna()
    if closes.empty:
        return None, None
    c0 = float(closes.iloc[0])
    c1 = float(closes.iloc[-1])
    if c0 <= 0:
        return None, None
    bh_ret = (c1 / c0 - 1.0) * 100.0
    peak = closes.cummax()
    dd = (closes / peak - 1.0) * 100.0
    bh_dd = float(-dd.min()) if not dd.empty else None  # 正数百分比
    return bh_ret, bh_dd


def load_universe() -> pd.DataFrame:
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
            if c in seen or not _is_mainboard(c):
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
    return out


def backtest_one(row: dict, end_date: str) -> dict:
    code = row["code"]
    name = row["name"]
    symbol = row["symbol"]
    index_name = row["index"]
    base = {
        "code": code,
        "name": name,
        "symbol": symbol,
        "index": index_name,
        "ok": 0,
        "error": "",
        "n_bars": 0,
    }
    for k in METRIC_KEYS:
        base[k] = None
    base["bh_return_pct"] = None
    base["bh_max_drawdown_pct"] = None
    base["excess_return_pct"] = None
    base["dd_improve_pct"] = None

    try:
        cache_path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
        cfg = BacktestConfig(
            symbol=symbol,
            symbol_name=name,
            em_symbol=code,
            threshold_pct=THRESHOLD_PCT,
            start_date=START_DATE,
            end_date=end_date,
            initial_cash=INITIAL_CASH,
            entry_ref="today_open",
            prev_entry_mode="yin_or_small_yang",
            daily_cache=cache_path,
            report_path=None,
        )
        daily = fetch_daily(
            cfg.symbol,
            cfg.start_date,
            cfg.end_date,
            cache_path=cfg.daily_cache,
        )
        if daily is None or daily.empty or len(daily) < 60:
            base["error"] = f"日线不足({0 if daily is None else len(daily)})"
            return base

        result = run_open_break_backtest(cfg, daily)
        m = result.metrics_df
        for k in METRIC_KEYS:
            base[k] = _metric(m, k)

        bh_ret, bh_dd = _bh_stats(daily)
        base["bh_return_pct"] = bh_ret
        base["bh_max_drawdown_pct"] = bh_dd
        strat_ret = base["total_return_pct"]
        strat_dd = base["max_drawdown_pct"]
        if strat_ret is not None and bh_ret is not None:
            base["excess_return_pct"] = float(strat_ret) - float(bh_ret)
        if strat_dd is not None and bh_dd is not None:
            # 正数 = 策略回撤更小
            base["dd_improve_pct"] = float(bh_dd) - float(strat_dd)

        base["n_bars"] = int(len(daily))
        base["ok"] = 1
        return base
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {e}"
        base["traceback"] = traceback.format_exc()[-800:]
        return base


def _load_done_codes() -> set[str]:
    if not RESULT_CSV.exists():
        return set()
    try:
        df = pd.read_csv(RESULT_CSV, dtype={"code": str})
        if "code" not in df.columns:
            return set()
        # 成功或已明确失败（有 error）都跳过；仅 ok 断点亦可，这里按 code 去重续跑
        return set(df["code"].astype(str).str.zfill(6))
    except Exception:
        return set()


def _append_results(rows: list[dict]) -> None:
    if not rows:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    for c in RESULT_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[RESULT_COLS]
    header = not RESULT_CSV.exists()
    df.to_csv(RESULT_CSV, mode="a", index=False, header=header, encoding="utf-8-sig")


def write_filters() -> pd.DataFrame:
    if not RESULT_CSV.exists():
        print("无 results.csv，跳过筛选")
        return pd.DataFrame()
    df = pd.read_csv(RESULT_CSV, dtype={"code": str})
    df["code"] = df["code"].astype(str).str.zfill(6)
    ok = df[df["ok"] == 1].copy()

    fit = ok[
        (ok["sharpe_ratio"] >= SHARPE_MIN) & (ok["excess_return_pct"] > 0)
    ].sort_values("sharpe_ratio", ascending=False)
    fit.to_csv(FIT_CSV, index=False, encoding="utf-8-sig")

    top50 = ok.sort_values("excess_return_pct", ascending=False).head(50)
    top50.to_csv(TOP50_CSV, index=False, encoding="utf-8-sig")

    lines = [
        f"生成时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"策略: OpenBreak3 A ±{THRESHOLD_PCT*100:.1f}% 仅止损卖",
        f"区间: {START_DATE} → 今",
        f"初始资金: {INITIAL_CASH:.0f}",
        f"全量行数: {len(df)}  ok={int((df['ok']==1).sum())}  fail={int((df['ok']!=1).sum())}",
        f"夏普>={SHARPE_MIN} 且超额>0: {len(fit)}",
        "",
        "=== 契合名单（夏普降序，前 40）===",
    ]
    show = fit.head(40)
    if show.empty:
        lines.append("(无)")
    else:
        for _, r in show.iterrows():
            lines.append(
                f"{r['code']} {r['name']} [{r['index']}] "
                f"夏普={r['sharpe_ratio']:.3f} "
                f"策略={r['total_return_pct']:.1f}% "
                f"持有={r['bh_return_pct']:.1f}% "
                f"超额={r['excess_return_pct']:.1f}% "
                f"策略回撤={r['max_drawdown_pct']:.1f}% "
                f"持有回撤={r['bh_max_drawdown_pct']:.1f}%"
            )
    SUMMARY_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nFIT: {FIT_CSV}")
    print(f"TOP50: {TOP50_CSV}")
    print(f"SUMMARY: {SUMMARY_TXT}")
    return fit


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    end_date = dt.date.today().strftime("%Y%m%d")

    universe = load_universe()
    done = _load_done_codes()
    todo = [
        row.to_dict()
        for _, row in universe.iterrows()
        if row["code"] not in done
    ]
    print(f"已完成 {len(done)}，待跑 {len(todo)}，workers={WORKERS}")

    t0 = time.time()
    ok_n = fail_n = 0
    batch: list[dict] = []

    if todo:
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(backtest_one, row, end_date): row for row in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                row = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    res = {
                        "code": row["code"],
                        "name": row["name"],
                        "symbol": row["symbol"],
                        "index": row["index"],
                        "ok": 0,
                        "error": f"FutureError: {e}",
                    }
                    for k in METRIC_KEYS + [
                        "bh_return_pct",
                        "bh_max_drawdown_pct",
                        "excess_return_pct",
                        "dd_improve_pct",
                        "n_bars",
                    ]:
                        res.setdefault(k, None)

                if res.get("ok") == 1:
                    ok_n += 1
                else:
                    fail_n += 1
                    err = res.get("error", "")
                    print(f"FAIL {res.get('code')} {res.get('name')}: {err}")

                batch.append(res)
                if len(batch) >= 10:
                    _append_results(batch)
                    batch.clear()

                if i % 10 == 0 or i == len(todo):
                    elapsed = (time.time() - t0) / 60.0
                    rate = i / max(elapsed, 1e-6)
                    eta = (len(todo) - i) / max(rate, 1e-6)
                    print(
                        f"进度 {i}/{len(todo)} ok={ok_n} fail={fail_n} "
                        f"用时{elapsed:.1f}m ETA~{eta:.1f}m"
                    )

        if batch:
            _append_results(batch)

    write_filters()
    print(f"\n完成。结果: {RESULT_CSV}")


if __name__ == "__main__":
    main()
