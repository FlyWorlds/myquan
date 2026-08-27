"""因子3×因子1 组合回测：Top10 / 2025YTD。

用法：
  python backtest/run_f3_f1_2025_top10.py
  python backtest/run_f3_f1_2025_top10.py --workers 12 --refresh
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.data import fetch_daily  # noqa: E402
from strategy.f3_f1_combo import run_f3_f1_combo  # noqa: E402
from backtest import zz1000_momentum_select as zz  # noqa: E402

OUT = Path(__file__).resolve().parent / "f3_f1_combo_2025_top10"
PANEL = zz.OUT_DIR / "panel_ohlc_zz500_1000_2024warm.parquet"


def _one(sym: str, warm: str, end: str, refresh: bool) -> tuple[str, pd.DataFrame | None]:
    cache = zz.CACHE_DIR / f"{sym}_daily_qfq.parquet"
    try:
        d = fetch_daily(sym, warm, end, cache_path=cache, force_refresh=refresh)
    except Exception:
        return sym, None
    if d is None or d.empty or len(d) < 40:
        return sym, None
    return sym, d


def build_panel(
    symbols: list[str],
    *,
    warm_start: str,
    end: str,
    refresh: bool,
    workers: int,
    panel_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if panel_path.exists() and not refresh:
        wide = pd.read_parquet(panel_path)
        print(f"载入面板缓存 {panel_path} {wide['close'].shape}")
        return wide["open"], wide["high"], wide["low"], wide["close"]

    opens: dict[str, pd.Series] = {}
    highs: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    t0 = time.time()
    done = 0
    ok = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(_one, s, warm_start, end, refresh) for s in symbols]
        for fut in as_completed(futs):
            sym, d = fut.result()
            done += 1
            if d is not None:
                dd = d.copy()
                dd["d"] = (
                    pd.to_datetime(dd["date"]).dt.tz_convert("Asia/Shanghai").dt.normalize()
                )
                dd = dd.set_index("d")
                opens[sym] = dd["open"].astype(float)
                highs[sym] = dd["high"].astype(float)
                lows[sym] = dd["low"].astype(float)
                closes[sym] = dd["close"].astype(float)
                ok += 1
            if done % 50 == 0 or done == len(symbols):
                print(
                    f"  panel {done}/{len(symbols)} valid={ok} ({time.time()-t0:.1f}s)",
                    flush=True,
                )

    op = pd.DataFrame(opens).sort_index()
    hi = pd.DataFrame(highs).sort_index()
    lo = pd.DataFrame(lows).sort_index()
    cl = pd.DataFrame(closes).sort_index()
    cols = sorted(set(op.columns) & set(hi.columns) & set(lo.columns) & set(cl.columns))
    op, hi, lo, cl = op[cols], hi[cols], lo[cols], cl[cols]
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat({"open": op, "high": hi, "low": lo, "close": cl}, axis=1).to_parquet(panel_path)
    print(f"写入面板 {panel_path} {cl.shape}", flush=True)
    return op, hi, lo, cl


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="20250101")
    p.add_argument("--end", default=None)
    p.add_argument("--warm-start", default="20240101")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--hold-days", type=int, default=None)
    p.add_argument(
        "--tp-levels",
        type=str,
        default="0.05,0.08,0.10",
        help="分档止盈涨幅，逗号分隔；空字符串关闭",
    )
    p.add_argument("--tp-reduce", type=float, default=0.20)
    p.add_argument("--no-tp", action="store_true", help="关闭分档止盈（仅止损）")
    args = p.parse_args()

    end = args.end or pd.Timestamp.today().strftime("%Y%m%d")
    OUT.mkdir(parents=True, exist_ok=True)

    if args.no_tp or not str(args.tp_levels).strip():
        tp_levels: tuple[float, ...] = ()
    else:
        tp_levels = tuple(
            float(x.strip()) for x in str(args.tp_levels).split(",") if x.strip()
        )

    univ = zz.load_zz500_1000_mainboard()
    symbols = univ["symbol"].tolist()
    print(
        f"[build] warm={args.warm_start} end={end} n_sym={len(symbols)} "
        f"workers={args.workers}",
        flush=True,
    )
    opens, highs, lows, closes = build_panel(
        symbols,
        warm_start=args.warm_start,
        end=end,
        refresh=args.refresh,
        workers=args.workers,
        panel_path=PANEL,
    )

    # 把刚建好的面板挂到默认路径旁，供 run_f3_f1_combo 复用：临时 monkey 路径
    # 直接调用内部流程更稳：复用 run 但覆盖 panel 读取
    # 最简单：把 PANEL 拷/链到 PANEL_PATH_ZZ500_1000（若尚未存在或需刷新）
    target = zz.PANEL_PATH_ZZ500_1000
    if (not target.exists()) or args.refresh or target.resolve() != PANEL.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        try:
            target.symlink_to(PANEL.resolve())
        except OSError:
            # 部分环境禁止 symlink：直接复制引用路径写入由 build 完成即可
            wide = pd.read_parquet(PANEL)
            wide.to_parquet(target)

    print(
        f"[backtest] f3×f1 Top{args.top_k} {args.start}→{end} precond=on "
        f"tp={tp_levels or 'off'}",
        flush=True,
    )
    res = run_f3_f1_combo(
        top_k=int(args.top_k),
        start=str(args.start),
        end=end,
        warm_start=str(args.warm_start),
        hold_days=args.hold_days,
        require_f1_precond=True,
        refresh=False,
        verbose=True,
        take_profit_levels=tp_levels,
        take_profit_reduce=float(args.tp_reduce),
    )

    # 去掉 stats 里的 DataFrame 再落盘
    stats = {k: v for k, v in res.stats.items() if k != "picks"}
    res.equity.to_csv(OUT / "equity.csv", index=False, encoding="utf-8-sig")
    res.trades.to_csv(OUT / "trades.csv", index=False, encoding="utf-8-sig")
    res.picks.to_csv(OUT / "picks.csv", index=False, encoding="utf-8-sig")
    res.yearly.to_csv(OUT / "yearly.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (OUT / "config.json").write_text(
        json.dumps(res.config, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n========== 结果 ==========")
    for k in (
        "start",
        "end",
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "n_buys",
        "n_tp_exits",
        "n_stop_exits",
        "n_time_exits",
        "n_breakout_miss",
        "end_equity",
        "top_k",
        "take_profit_levels",
    ):
        print(f"{k}: {stats.get(k)}")
    if not res.yearly.empty:
        print("\n分年:")
        print(res.yearly.to_string(index=False))
    print(f"\n产物目录: {OUT}")


if __name__ == "__main__":
    main()
