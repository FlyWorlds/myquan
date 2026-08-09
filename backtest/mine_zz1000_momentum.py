"""中证1000 截面动量挖参：抬夏普、压回撤（2026YTD）。

先缓存 OHLCV 宽表，再向量化因子+袖套回测网格搜索。
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.zz1000_momentum_select import (  # noqa: E402
    CACHE_DIR,
    COMMISSION,
    INITIAL_CASH,
    LOT,
    OUT_DIR,
    SLIP,
    STAMP,
    load_zz1000_mainboard,
)
from strategy.data import fetch_daily  # noqa: E402

PANEL_PATH = OUT_DIR / "panel_ohlc.parquet"
BEST_PATH = OUT_DIR / "best_config.json"
WARM_START = "20250701"
BT_START = "20260101"


def build_or_load_panel(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if PANEL_PATH.exists() and not refresh:
        wide = pd.read_parquet(PANEL_PATH)
        # MultiIndex columns: field, symbol
        opens = wide["open"]
        highs = wide["high"]
        lows = wide["low"]
        closes = wide["close"]
        print(f"载入面板缓存 {PANEL_PATH}  {closes.shape}")
        return opens, highs, lows, closes

    univ = load_zz1000_mainboard()
    end = pd.Timestamp.today().strftime("%Y%m%d")
    opens = {}
    highs = {}
    lows = {}
    closes = {}
    t0 = time.time()
    for i, sym in enumerate(univ["symbol"], 1):
        cache = CACHE_DIR / f"{sym}_daily_qfq.parquet"
        try:
            d = fetch_daily(sym, WARM_START, end, cache_path=cache)
        except Exception:
            continue
        if d is None or d.empty or len(d) < 40:
            continue
        d = d.copy()
        d["d"] = pd.to_datetime(d["date"]).dt.tz_convert("Asia/Shanghai").dt.normalize()
        d = d.set_index("d")
        opens[sym] = d["open"].astype(float)
        highs[sym] = d["high"].astype(float)
        lows[sym] = d["low"].astype(float)
        closes[sym] = d["close"].astype(float)
        if i % 100 == 0:
            print(f"  panel {i}/{len(univ)} valid={len(closes)} ({time.time()-t0:.1f}s)")
    op = pd.DataFrame(opens).sort_index()
    hi = pd.DataFrame(highs).sort_index()
    lo = pd.DataFrame(lows).sort_index()
    cl = pd.DataFrame(closes).sort_index()
    cols = sorted(set(op.columns) & set(hi.columns) & set(lo.columns) & set(cl.columns))
    op, hi, lo, cl = op[cols], hi[cols], lo[cols], cl[cols]
    wide = pd.concat({"open": op, "high": hi, "low": lo, "close": cl}, axis=1)
    wide.to_parquet(PANEL_PATH)
    print(f"写入面板 {PANEL_PATH} shape={cl.shape}")
    return op, hi, lo, cl


def factor_matrix(
    opens: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    kind: str,
    n: int,
) -> pd.DataFrame:
    c = closes
    if kind == "roc":
        return c / c.shift(n) - 1.0
    if kind == "roc_vol":
        roc = c / c.shift(n) - 1.0
        vol = c.pct_change().rolling(n, min_periods=max(5, n // 2)).std()
        return roc / vol.replace(0, np.nan)
    if kind == "ma_gap":
        ma = c.rolling(n, min_periods=n).mean()
        return c / ma - 1.0
    if kind == "rev":  # 短期反转：做多最弱（负 roc 最大）
        return -(c / c.shift(n) - 1.0)
    if kind == "breakout":
        hh = highs.shift(1).rolling(n, min_periods=n).max()
        return c / hh - 1.0
    if kind == "dist_hl":
        # 向量化近似：距高/低的相对位置（非精确 argmin 天数，但同方向）
        hh = highs.rolling(n, min_periods=n).max()
        ll = lows.rolling(n, min_periods=n).min()
        mid = (hh + ll) / 2.0
        span = (hh - ll).replace(0, np.nan)
        return (c - mid) / span
    raise ValueError(kind)


def simulate_fast(
    factor: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    bt_start: pd.Timestamp,
    top_k: int,
    hold_days: int,
    min_score: float | None,
    require_above_ma: int | None,
    initial_cash: float = INITIAL_CASH,
) -> dict:
    """袖套轮动；信号日→次日开盘买→hold_days 后开盘卖。"""
    dates = list(closes.index)
    bt_dates = [d for d in dates if d >= bt_start]
    if len(bt_dates) < hold_days + 5:
        return {"sharpe": -9, "ret": -9, "dd": 9, "n_buys": 0}

    # 可选：均线过滤（因子日 close > MA）
    if require_above_ma and require_above_ma > 1:
        ma = closes.rolling(require_above_ma, min_periods=require_above_ma).mean()
        factor = factor.where(closes > ma)

    if min_score is not None:
        factor = factor.where(factor >= min_score)

    date_to_i = {d: i for i, d in enumerate(dates)}
    sleeve_cash = np.full(hold_days, initial_cash / hold_days, dtype=float)
    # entry_i, shares array per sleeve as list of tuples
    sleeve_pos: list[list[tuple[str, int, int]]] = [[] for _ in range(hold_days)]

    eq_list = []
    n_buys = 0

    for d in bt_dates:
        di = date_to_i[d]
        # sell
        for s in range(hold_days):
            keep = []
            for sym, shares, entry_i in sleeve_pos[s]:
                if di - entry_i >= hold_days:
                    px = opens.at[d, sym]
                    if pd.isna(px) or px <= 0:
                        keep.append((sym, shares, entry_i))
                        continue
                    px = float(px) * (1 - SLIP)
                    proceeds = shares * px
                    sleeve_cash[s] += proceeds * (1 - COMMISSION - STAMP)
                else:
                    keep.append((sym, shares, entry_i))
            sleeve_pos[s] = keep

        # buy from yesterday signal
        if di == 0:
            eq_list.append(float(sleeve_cash.sum()))
            continue
        prev = dates[di - 1]
        row = factor.loc[prev].dropna()
        if len(row) >= top_k:
            top = row.nlargest(top_k).index.tolist()
        else:
            top = []
        s = di % hold_days
        if top and not sleeve_pos[s] and sleeve_cash[s] > 0:
            budget = sleeve_cash[s] / len(top)
            for sym in top:
                px = opens.at[d, sym]
                if pd.isna(px) or px <= 0:
                    continue
                px = float(px) * (1 + SLIP)
                shares = int(budget // (px * LOT)) * LOT
                if shares <= 0:
                    continue
                cost = shares * px
                fee = cost * COMMISSION
                if cost + fee > sleeve_cash[s]:
                    continue
                sleeve_cash[s] -= cost + fee
                sleeve_pos[s].append((sym, shares, di))
                n_buys += 1

        eq = float(sleeve_cash.sum())
        for s in range(hold_days):
            for sym, shares, _ in sleeve_pos[s]:
                px = closes.at[d, sym]
                if not pd.isna(px):
                    eq += shares * float(px)
        eq_list.append(eq)

    eq = np.asarray(eq_list, dtype=float)
    if len(eq) < 5:
        return {"sharpe": -9, "ret": -9, "dd": 9, "n_buys": n_buys}
    rets = np.diff(eq) / np.where(eq[:-1] == 0, np.nan, eq[:-1])
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets) * np.sqrt(252))
        if len(rets) and np.std(rets) > 1e-12
        else 0.0
    )
    peak = np.maximum.accumulate(eq)
    dd = float(np.nanmax((peak - eq) / np.where(peak == 0, np.nan, peak)))
    return {
        "sharpe": sharpe,
        "ret": float(eq[-1] / initial_cash - 1.0),
        "dd": dd,
        "n_buys": n_buys,
        "end": float(eq[-1]),
    }


def main() -> None:
    opens, highs, lows, closes = build_or_load_panel(refresh=False)
    bt_start = pd.Timestamp(BT_START).tz_localize("Asia/Shanghai")

    kinds = ["roc", "roc_vol", "ma_gap", "breakout", "rev", "dist_hl"]
    ns = [3, 5, 8, 10, 15, 20, 30, 40, 60]
    top_ks = [2]
    hold_days_list = [3, 5, 8, 10]
    min_scores = [None, 0.0, 0.02, 0.05]
    ma_filters = [None, 20, 60]

    rows = []
    t0 = time.time()
    total = 0
    for kind, n in itertools.product(kinds, ns):
        try:
            fac = factor_matrix(opens, highs, lows, closes, kind=kind, n=n)
        except Exception as exc:
            print("factor fail", kind, n, exc)
            continue
        for top_k, hold, ms, maf in itertools.product(
            top_ks, hold_days_list, min_scores, ma_filters
        ):
            # 反转因子：min_score 语义相反，跳过正阈值过滤
            if kind == "rev" and ms is not None and ms > 0:
                continue
            m = simulate_fast(
                fac,
                opens,
                closes,
                bt_start=bt_start,
                top_k=top_k,
                hold_days=hold,
                min_score=ms if kind != "rev" else None,
                require_above_ma=maf,
            )
            rows.append(
                {
                    "kind": kind,
                    "n": n,
                    "top_k": top_k,
                    "hold_days": hold,
                    "min_score": ms,
                    "ma_filter": maf,
                    **m,
                }
            )
            total += 1
    print(f"评估 {total} 组 用时 {time.time()-t0:.1f}s")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "mine_grid_2026.csv", index=False, encoding="utf-8-sig")

    # 目标：夏普优先，回撤惩罚；至少要求 dd<=0.18 且 sharpe 尽量高
    df["score"] = df["sharpe"] - 1.5 * df["dd"] + 0.3 * df["ret"].clip(lower=-1, upper=2)
    # 硬约束候选
    hard = df[(df["dd"] <= 0.18) & (df["sharpe"] >= 0.8) & (df["n_buys"] >= 20)].copy()
    soft = df[(df["dd"] <= 0.22) & (df["sharpe"] >= 0.5)].copy()

    print("\n===== Top15 by score (全样本) =====")
    top = df.sort_values(["score", "sharpe"], ascending=False).head(15)
    print(
        top[
            ["kind", "n", "hold_days", "min_score", "ma_filter", "sharpe", "ret", "dd", "n_buys", "score"]
        ].to_string(index=False)
    )

    if not hard.empty:
        best = hard.sort_values(["sharpe", "score"], ascending=False).iloc[0]
        tag = "hard(dd<=18%,sharpe>=0.8)"
    elif not soft.empty:
        best = soft.sort_values(["sharpe", "score"], ascending=False).iloc[0]
        tag = "soft(dd<=22%,sharpe>=0.5)"
    else:
        best = df.sort_values(["score", "sharpe"], ascending=False).iloc[0]
        tag = "fallback(score)"

    print(f"\nBEST [{tag}]:")
    print(best.to_string())

    cfg = {
        "kind": str(best["kind"]),
        "n": int(best["n"]),
        "top_k": int(best["top_k"]),
        "hold_days": int(best["hold_days"]),
        "min_score": None if pd.isna(best["min_score"]) else float(best["min_score"]),
        "ma_filter": None if pd.isna(best["ma_filter"]) else int(best["ma_filter"]),
        "sharpe": float(best["sharpe"]),
        "ret": float(best["ret"]),
        "dd": float(best["dd"]),
        "n_buys": int(best["n_buys"]),
        "select_tag": tag,
    }
    BEST_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {BEST_PATH}")


if __name__ == "__main__":
    main()
