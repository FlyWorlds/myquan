"""为策略四补算滚动 2/3/6 月评分指标，并对比多周期回测。

评分窗（指标在评分月末截断、窗内从空仓重放因子1）:
  month / roll2 / roll3 / roll6 / roll12 / cum2020

输出:
  backtest/strategy4_out/metrics_roll_windows.parquet
  backtest/strategy4_out/score_window_compare.csv
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.factor1_monthly_top3 import (  # noqa: E402
    MIN_BARS_MONTH,
    MIN_BARS_ROLL,
    ORIGIN,
    OUT_DIR as F1_DIR,
    THRESHOLDS,
    _metrics_from_equity,
    simulate_open_break,
)
from backtest.strategy4_backtest import (  # noqa: E402
    INITIAL_CASH,
    MAX_POS,
    OUT,
    run_backtest,
)

PATHS = F1_DIR / "paths"
BASE_METRICS = F1_DIR / "month_symbol_threshold_metrics.parquet"
ROLL_MONTHS = (2, 3, 6)
WORKERS = 8


def _thr_key(thr: float) -> str:
    return str(thr).replace(".", "_")


def _month_ends(dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(1, index=dates)
    return [pd.Timestamp(x).normalize() for x in s.groupby(dates.to_period("M")).apply(lambda g: g.index.max()).tolist()]


def process_symbol_rolls(symbol: str) -> list[dict]:
    p = PATHS / f"{symbol}.npz"
    if not p.exists():
        return []
    z = np.load(p, allow_pickle=True)
    dates = pd.DatetimeIndex(pd.to_datetime(z["dates"]))
    # paths 已从 2020 截断；滚动需要更长历史时用 daily_cache
    # 这里 paths 自 2020 起：roll12 在 2020 年内会偏短，与原 roll12 一致用 pad
    rows: list[dict] = []
    month_ends = _month_ends(dates[dates >= ORIGIN] if dates[0] < ORIGIN else dates)
    if not month_ends:
        month_ends = _month_ends(dates)

    for thr in THRESHOLDS:
        k = _thr_key(thr)
        try:
            o = z[f"open_{k}"].astype(float)
            h = z[f"high_{k}"].astype(float)
            l = z[f"low_{k}"].astype(float)
            c = z[f"close_{k}"].astype(float)
        except KeyError:
            continue

        for me in month_ends:
            i_end = int(dates.get_indexer([me], method="pad")[0])
            if i_end < 1:
                continue
            period = str(me.to_period("M"))
            row: dict = {
                "symbol": symbol,
                "threshold_pct": float(thr),
                "score_month": period,
                "month_end": str(me.date()),
            }
            for n_m in ROLL_MONTHS:
                # 含月末往前 n_m 个自然月
                r_start = (me - pd.DateOffset(months=n_m) + pd.Timedelta(days=1)).normalize()
                if r_start < dates[0]:
                    r_start = dates[0]
                i_r0 = int(dates.get_indexer([r_start], method="bfill")[0])
                min_bars = max(MIN_BARS_MONTH, min(40, n_m * 15))
                prefix = f"roll{n_m}"
                if i_r0 < 0 or i_end - i_r0 + 1 < min_bars:
                    row[f"{prefix}_ok"] = 0
                    continue
                eq_r, _ = simulate_open_break(
                    o[i_r0 : i_end + 1],
                    h[i_r0 : i_end + 1],
                    l[i_r0 : i_end + 1],
                    c[i_r0 : i_end + 1],
                    thr=float(thr),
                )
                met = _metrics_from_equity(eq_r, c[i_r0 : i_end + 1])
                row[f"{prefix}_ok"] = 1
                for mk, mv in met.items():
                    row[f"{prefix}_{mk}"] = mv
            rows.append(row)
    return rows


def build_roll_metrics(force: bool = False) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "metrics_roll_windows.parquet"
    if out_path.exists() and not force:
        print(f"加载已有 {out_path}")
        return out_path

    base = pd.read_parquet(BASE_METRICS)
    symbols = sorted({p.stem for p in PATHS.glob("*.npz")})
    print(f"补算 roll2/3/6：{len(symbols)} 票…")
    t0 = time.time()
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_symbol_rolls, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            done += 1
            rows.extend(fut.result())
            if done % 50 == 0 or done == len(symbols):
                print(f"  {done}/{len(symbols)} ({time.time()-t0:.0f}s) rows={len(rows)}")

    roll = pd.DataFrame(rows)
    # 合并：以 symbol+threshold+score_month 对齐
    keys = ["symbol", "threshold_pct", "score_month"]
    merged = base.merge(roll, on=keys, how="left", suffixes=("", "_y"))
    # 清理 merge 产生的重复 month_end
    if "month_end_y" in merged.columns:
        merged = merged.drop(columns=["month_end_y"])
    for n_m in ROLL_MONTHS:
        ok = f"roll{n_m}_ok"
        if ok in merged.columns:
            merged[ok] = merged[ok].fillna(0).astype(int)
    merged.to_parquet(out_path, index=False)
    print(f"写入 {out_path} shape={merged.shape}")
    return out_path


def main() -> None:
    metrics_path = build_roll_metrics(force=False)
    modes = ["month", "roll2", "roll3", "roll6", "roll12", "cum2020"]
    # 临时替换 strategy4_backtest 的 METRICS 路径：通过改 run 前 monkeypatch
    import backtest.strategy4_backtest as s4b

    s4b.METRICS = metrics_path
    # build_monthly_ranks 读 METRICS 全局
    compare = []
    for mode in modes:
        print(f"\n######## 评分窗 {mode} ########")
        # 清 ranks 缓存
        if hasattr(s4b._run_window, "_ranks"):
            delattr(s4b._run_window, "_ranks")
        try:
            eq, tr, sm = s4b.run_backtest(score_mode=mode, slip=0.001)
        except Exception as e:
            print(f"FAIL {mode}: {e}")
            continue
        yearly = sm.pop("yearly")
        row = {
            "score_mode": mode,
            "ret_pct": sm["total_return_pct"],
            "sharpe": sm["sharpe"],
            "dd_pct": sm["max_drawdown_pct"],
            "n_buys": sm["n_buys"],
            "end_equity": sm["end_equity"],
        }
        for _, yr in yearly.iterrows():
            row[f"y{int(yr['year'])}"] = float(yr["return_pct"])
        compare.append(row)
        eq.to_csv(OUT / f"equity_{mode}.csv", index=False, encoding="utf-8-sig")
        yearly.to_csv(OUT / f"yearly_{mode}.csv", index=False, encoding="utf-8-sig")
        print(
            f"  {mode}: ret={sm['total_return_pct']:.1f}% sharpe={sm['sharpe']:.2f} "
            f"dd={sm['max_drawdown_pct']:.1f}% buys={sm['n_buys']}"
        )

    cdf = pd.DataFrame(compare).sort_values("sharpe", ascending=False)
    cdf.to_csv(OUT / "score_window_compare.csv", index=False, encoding="utf-8-sig")
    print("\n===== 评分周期对比 =====")
    print(cdf.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print(f"\n产物目录 {OUT}")


if __name__ == "__main__":
    main()
