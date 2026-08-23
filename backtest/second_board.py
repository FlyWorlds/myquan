"""二板策略回测：昨日首板 → 次日开盘突破买入（不设前阳限制）。

规则:
  · 宇宙: 中证1000（含创业/科创，涨停幅度 10%/20%）
  · 首板: 当日收盘涨停，且前一日未收盘涨停
  · 次日: 按个股「当前最优阈值」{2%,2.5%,3%} 做开盘突破买入；
          不限制前日阴/小阳（因前日为涨停）；一字涨停开盘买不进则放弃
  · 最优阈值: 截至首板日，过去 120 个交易日、无前阳过滤的开盘突破回测，
          评分 5×超额分位 + 3×夏普 + 2×回撤改善（票内三阈值择优）
  · 止损两模式:
      t1   — 买入次日(T+1)若触开盘止损则止损，否则收盘清仓
      cont — 延续持有，每日按开盘×(1-thr) 止损，直至卖出

组合: 初始 100 万，最多 10 仓，新开仓按 净值/10 分配；2020→最新。
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.open_break import (  # noqa: E402
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    stop_trigger_price,
)
from strategy.data import fetch_daily  # noqa: E402
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE, CSINDEX_CONS_URL, _to_symbol  # noqa: E402

OUT = Path(__file__).resolve().parent / "second_board"
THRESHOLDS = (0.02, 0.025, 0.03)
LOOKBACK = 120
W_EX, W_SH, W_DD = 5.0, 3.0, 2.0
INITIAL = 1_000_000.0
MAX_POS = 10
TARGET_PCT = 0.95
LOT = 100
WORKERS = 8
ORIGIN = pd.Timestamp("2020-01-01")
LU_TOL = 0.012  # 相对涨停幅度容忍


def load_zz1000() -> pd.DataFrame:
    url = CSINDEX_CONS_URL.format(code="000852")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))
    code_col = next(
        c for c in df.columns if "成份券代码" in str(c) or "Constituent Code" in str(c)
    )
    name_col = next(
        c
        for c in df.columns
        if ("成份券名称" in str(c) or "Constituent Name" in str(c)) and "Eng" not in str(c)
    )
    rows = []
    for _, row in df.iterrows():
        c = str(row[code_col]).zfill(6)
        if c.startswith(("8", "4")):  # 北交
            continue
        name = str(row[name_col]).strip()
        if "ST" in name.upper():
            continue
        rows.append({"code": c, "name": name, "symbol": _to_symbol(c)})
    return pd.DataFrame(rows).drop_duplicates("code")


def limit_ratio(code: str) -> float:
    c = str(code).zfill(6)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def ensure_daily(univ: pd.DataFrame) -> None:
    UNIV_CACHE.mkdir(parents=True, exist_ok=True)
    missing = []
    for _, r in univ.iterrows():
        p = UNIV_CACHE / f"{r['symbol']}_daily_qfq.parquet"
        if not p.exists():
            missing.append(r)
    print(f"缺日线: {len(missing)} / {len(univ)}")
    for i, r in enumerate(missing, 1):
        try:
            fetch_daily(
                r["symbol"],
                "20190101",
                pd.Timestamp.today().strftime("%Y%m%d"),
                cache_path=UNIV_CACHE / f"{r['symbol']}_daily_qfq.parquet",
            )
        except Exception as e:
            print(f"  fail {r['symbol']}: {e}")
        if i % 20 == 0:
            print(f"  拉取进度 {i}/{len(missing)}")


def load_bars(symbol: str) -> pd.DataFrame | None:
    p = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[d["date"] >= pd.Timestamp("2019-01-01")].reset_index(drop=True)
    return d if len(d) > LOOKBACK else None


def is_limit_up_series(prev_close: np.ndarray, close: np.ndarray, high: np.ndarray, lim: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = close / prev_close - 1.0
    sealed = close >= high * 0.995
    return (pct >= lim - LU_TOL) & sealed & np.isfinite(pct)


def simulate_nofilter_path(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, thr: float, cash0: float = 1e5
) -> np.ndarray:
    """无前阳过滤的开盘突破权益曲线（用于阈值择优）。"""
    n = len(o)
    eq = np.empty(n)
    cash = cash0
    shares = 0.0
    buy_i = -1
    for i in range(n):
        oi, hi, li, ci = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        if oi <= 0 or ci <= 0:
            eq[i] = cash + shares * max(ci, 0)
            continue
        buy_px = entry_trigger_price(oi, entry_pct=thr)
        stop_px = stop_trigger_price(oi, stop_pct=thr)
        if shares > 0:
            if i > buy_i and li <= stop_px + 1e-12:
                prev_c = float(c[i - 1]) if i else ci
                lims = limit_down_state(
                    prev_close=prev_c, open_px=oi, high_px=hi, low_px=li, close_px=ci,
                    limit_down_pct=0.10, tick=TICK_SIZE,
                )
                if not bool(lims["locked"]):
                    sp = float(lims["limit_px"] if bool(lims["opened"]) else stop_px) * (1 - SLIP)
                    proceeds = shares * sp
                    cash += proceeds - proceeds * (COMMISSION + STAMP)
                    shares = 0.0
                    buy_i = -1
        else:
            if hi + 1e-12 >= buy_px:
                px = buy_px * (1 + SLIP)
                raw = math.floor(cash * TARGET_PCT / (px * LOT)) * LOT
                if raw >= LOT:
                    cost = raw * px
                    fee = cost * COMMISSION
                    if cost + fee <= cash:
                        cash -= cost + fee
                        shares = float(raw)
                        buy_i = i
        eq[i] = cash + shares * ci
    return eq


def _window_score(eq: np.ndarray, close: np.ndarray) -> tuple[float, float, float]:
    if len(eq) < 20 or eq[0] <= 0:
        return np.nan, np.nan, np.nan
    strat = (eq[-1] / eq[0] - 1.0) * 100
    peak = np.maximum.accumulate(eq)
    dd = float(-(eq / peak - 1.0).min()) * 100
    rets = np.diff(eq) / eq[:-1]
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(242))
        if len(rets) >= 10 and np.std(rets, ddof=1) > 1e-12
        else 0.0
    )
    bh = (float(close[-1]) / float(close[0]) - 1.0) * 100 if close[0] > 0 else np.nan
    cpeak = np.maximum.accumulate(close.astype(float))
    bh_dd = float(-(close / cpeak - 1.0).min()) * 100
    return strat - bh, sharpe, bh_dd - dd


def pick_best_thr(o, h, l, c, end_i: int) -> float:
    start = max(0, end_i - LOOKBACK + 1)
    if end_i - start + 1 < 40:
        return 0.025
    scores = []
    for thr in THRESHOLDS:
        eq = simulate_nofilter_path(o[start : end_i + 1], h[start : end_i + 1], l[start : end_i + 1], c[start : end_i + 1], thr)
        ex, sh, dd = _window_score(eq, c[start : end_i + 1])
        scores.append((thr, ex, sh, dd))
    # 票内 min-max 加权
    arr = np.array([[s[1], s[2], s[3]] for s in scores], dtype=float)
    if not np.isfinite(arr).all():
        return 0.025
    norm = np.zeros_like(arr)
    for j in range(3):
        col = arr[:, j]
        if col.max() - col.min() < 1e-12:
            norm[:, j] = 0.5
        else:
            norm[:, j] = (col - col.min()) / (col.max() - col.min())
    best_i = int(np.argmax(W_EX * norm[:, 0] + W_SH * norm[:, 1] + W_DD * norm[:, 2]))
    return float(scores[best_i][0])


def process_symbol(task: dict) -> dict:
    symbol, code, name = task["symbol"], task["code"], task["name"]
    out = {"symbol": symbol, "code": code, "name": name, "signals": [], "ok": 0, "error": ""}
    daily = load_bars(symbol)
    if daily is None:
        out["error"] = "no_daily"
        return out
    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    prev = np.roll(c, 1)
    prev[0] = np.nan
    lim = limit_ratio(code)
    lu = is_limit_up_series(prev, c, h, lim)
    first_board = np.zeros(len(c), dtype=bool)
    first_board[1:] = lu[1:] & (~lu[:-1])

    # 三条全样本无过滤路径，首板日用滚动窗评分择优（快）
    eq_by_thr = {
        thr: simulate_nofilter_path(o, h, l, c, thr) for thr in THRESHOLDS
    }

    for i in range(1, len(c) - 1):
        if not first_board[i]:
            continue
        j = i + 1
        if dates[j] < ORIGIN:
            continue
        start = max(0, i - LOOKBACK + 1)
        if i - start + 1 < 40:
            thr = 0.025
        else:
            scores = []
            for t in THRESHOLDS:
                ex, sh, dd = _window_score(
                    eq_by_thr[t][start : i + 1], c[start : i + 1]
                )
                scores.append((t, ex, sh, dd))
            arr = np.array([[s[1], s[2], s[3]] for s in scores], dtype=float)
            if not np.isfinite(arr).all():
                thr = 0.025
            else:
                norm = np.zeros_like(arr)
                for col_i in range(3):
                    col = arr[:, col_i]
                    if col.max() - col.min() < 1e-12:
                        norm[:, col_i] = 0.5
                    else:
                        norm[:, col_i] = (col - col.min()) / (col.max() - col.min())
                thr = float(
                    scores[
                        int(np.argmax(W_EX * norm[:, 0] + W_SH * norm[:, 1] + W_DD * norm[:, 2]))
                    ][0]
                )

        oj, hj = float(o[j]), float(h[j])
        if oj <= 0:
            continue
        if prev[j] > 0 and (oj / float(prev[j]) - 1.0) >= lim - LU_TOL:
            out["signals"].append(
                {
                    "first_board_date": str(dates[i].date()),
                    "trade_date": str(dates[j].date()),
                    "symbol": symbol,
                    "code": code,
                    "name": name,
                    "thr": thr,
                    "entry": False,
                    "reason": "一字涨停开盘",
                    "buy_px": np.nan,
                    "buy_i": j,
                    "fb_i": i,
                }
            )
            continue
        buy_px = entry_trigger_price(oj, entry_pct=thr)
        if hj + 1e-12 < buy_px:
            out["signals"].append(
                {
                    "first_board_date": str(dates[i].date()),
                    "trade_date": str(dates[j].date()),
                    "symbol": symbol,
                    "code": code,
                    "name": name,
                    "thr": thr,
                    "entry": False,
                    "reason": "未触买点",
                    "buy_px": buy_px,
                    "buy_i": j,
                    "fb_i": i,
                }
            )
            continue
        out["signals"].append(
            {
                "first_board_date": str(dates[i].date()),
                "trade_date": str(dates[j].date()),
                "symbol": symbol,
                "code": code,
                "name": name,
                "thr": thr,
                "entry": True,
                "reason": "买入",
                "buy_px": float(buy_px),
                "buy_i": j,
                "fb_i": i,
            }
        )
    # 存 bars 供组合（压缩）
    npz_path = OUT / "bars" / f"{symbol}.npz"
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        npz_path,
        dates=np.array([str(x.date()) for x in dates]),
        open=o,
        high=h,
        low=l,
        close=c,
        prev_close=prev,
        lim=np.array([lim]),
    )
    out["ok"] = 1
    return out


@dataclass
class Pos:
    symbol: str
    code: str
    name: str
    thr: float
    shares: float
    entry_px: float
    buy_date: pd.Timestamp
    buy_i: int
    mode: str  # t1 | cont
    cash_used: float


def run_portfolio(signals: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """mode: t1 | cont"""
    # 日历
    sample = next((OUT / "bars").glob("*.npz"))
    cal = pd.to_datetime(np.load(sample)["dates"])
    cal = cal[cal >= ORIGIN]

    bar_cache: dict[str, dict] = {}

    def bars(sym: str):
        if sym not in bar_cache:
            z = np.load(OUT / "bars" / f"{sym}.npz", allow_pickle=True)
            dates = pd.to_datetime(z["dates"])
            bar_cache[sym] = {
                "dates": dates,
                "idx": {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)},
                "open": z["open"],
                "high": z["high"],
                "low": z["low"],
                "close": z["close"],
                "prev": z["prev_close"],
                "lim": float(z["lim"][0]),
            }
        return bar_cache[sym]

    # 按交易日聚合可买入信号
    entries = signals[signals["entry"] == True].copy()  # noqa: E712
    by_day: dict[str, pd.DataFrame] = {
        d: g for d, g in entries.groupby("trade_date")
    }

    cash = INITIAL
    positions: list[Pos] = []
    equity_rows = []
    trades = []

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        ds = str(dt.date())

        # --- exits ---
        still: list[Pos] = []
        for p in positions:
            b = bars(p.symbol)
            j = b["idx"].get(dt)
            if j is None:
                still.append(p)
                continue
            oi, hi, li, ci = float(b["open"][j]), float(b["high"][j]), float(b["low"][j]), float(b["close"][j])
            stop_px = stop_trigger_price(oi, stop_pct=p.thr)
            sold = False
            sell_px = None
            reason = ""

            if mode == "t1":
                # 仅在买入后第一个交易日处理
                if j > p.buy_i:
                    # 这是 T+1 或更后；t1 模式应只在 buy_i+1 那天退出
                    # 找到买入后的下一交易日
                    buy_dates = [d for d in b["idx"] if d > p.buy_date]
                    if not buy_dates:
                        still.append(p)
                        continue
                    t1_date = min(buy_dates)
                    if dt == t1_date:
                        if li <= stop_px + 1e-12:
                            prev_c = float(b["prev"][j]) if np.isfinite(b["prev"][j]) else ci
                            lims = limit_down_state(
                                prev_close=prev_c, open_px=oi, high_px=hi, low_px=li, close_px=ci,
                                limit_down_pct=0.10, tick=TICK_SIZE,
                            )
                            if bool(lims["locked"]):
                                still.append(p)
                                continue
                            sell_px = float(lims["limit_px"] if bool(lims["opened"]) else stop_px) * (1 - SLIP)
                            reason = "T+1止损"
                        else:
                            sell_px = ci * (1 - SLIP)
                            reason = "T+1收盘清仓"
                        sold = True
                    elif dt > t1_date:
                        # 理论不应残留；强制收盘清
                        sell_px = ci * (1 - SLIP)
                        reason = "逾期清仓"
                        sold = True
                    else:
                        still.append(p)
                        continue
            else:  # cont
                if j > p.buy_i and li <= stop_px + 1e-12:
                    prev_c = float(b["prev"][j]) if np.isfinite(b["prev"][j]) else ci
                    lims = limit_down_state(
                        prev_close=prev_c, open_px=oi, high_px=hi, low_px=li, close_px=ci,
                        limit_down_pct=0.10, tick=TICK_SIZE,
                    )
                    if not bool(lims["locked"]):
                        sell_px = float(lims["limit_px"] if bool(lims["opened"]) else stop_px) * (1 - SLIP)
                        reason = "延续止损"
                        sold = True

            if sold and sell_px is not None:
                proceeds = p.shares * sell_px
                fee = proceeds * (COMMISSION + STAMP)
                cash += proceeds - fee
                trades.append(
                    {
                        "mode": mode,
                        "symbol": p.symbol,
                        "code": p.code,
                        "name": p.name,
                        "thr": p.thr,
                        "buy_date": str(p.buy_date.date()),
                        "sell_date": ds,
                        "buy_px": p.entry_px,
                        "sell_px": sell_px,
                        "ret_pct": (sell_px / p.entry_px - 1.0) * 100,
                        "reason": reason,
                    }
                )
            else:
                still.append(p)
        positions = still

        # --- entries ---
        free_slots = MAX_POS - len(positions)
        if free_slots > 0 and ds in by_day:
            cands = by_day[ds]
            # 已持仓去重
            held = {p.symbol for p in positions}
            cands = cands[~cands["symbol"].isin(held)]
            # 按 thr 稳定性 / 名称排序稳定
            cands = cands.sort_values(["thr", "symbol"])
            nav = cash + sum(
                p.shares * float(bars(p.symbol)["close"][bars(p.symbol)["idx"][dt]])
                if dt in bars(p.symbol)["idx"]
                else p.shares * p.entry_px
                for p in positions
            )
            alloc = nav / MAX_POS
            for _, row in cands.iterrows():
                if free_slots <= 0 or cash < alloc * 0.5:
                    break
                sym = row["symbol"]
                b = bars(sym)
                j = b["idx"].get(dt)
                if j is None:
                    continue
                thr = float(row["thr"])
                buy_px = float(row["buy_px"]) * (1 + SLIP)
                budget = min(cash * TARGET_PCT, alloc * TARGET_PCT)
                raw = math.floor(budget / (buy_px * LOT)) * LOT
                if raw < LOT:
                    continue
                cost = raw * buy_px
                fee = cost * COMMISSION
                if cost + fee > cash:
                    continue
                cash -= cost + fee
                positions.append(
                    Pos(
                        symbol=sym,
                        code=row["code"],
                        name=row["name"],
                        thr=thr,
                        shares=float(raw),
                        entry_px=buy_px,
                        buy_date=dt,
                        buy_i=j,
                        mode=mode,
                        cash_used=cost + fee,
                    )
                )
                free_slots -= 1

        # mark nav
        nav = cash
        for p in positions:
            b = bars(p.symbol)
            j = b["idx"].get(dt)
            if j is not None:
                nav += p.shares * float(b["close"][j])
            else:
                nav += p.shares * p.entry_px
        equity_rows.append({"date": ds, "mode": mode, "equity": nav, "n_pos": len(positions), "cash": cash})

    eq = pd.DataFrame(equity_rows)
    eq["date"] = pd.to_datetime(eq["date"])
    e0, e1 = float(eq.equity.iloc[0]), float(eq.equity.iloc[-1])
    rets = eq.equity.pct_change().dropna()
    peak = eq.equity.cummax()
    max_dd = float(-(eq.equity / peak - 1).min()) * 100
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * math.sqrt(242))
        if len(rets) > 5 and rets.std(ddof=1) > 0
        else 0.0
    )
    tr = pd.DataFrame(trades)
    summary = {
        "mode": mode,
        "start": str(eq.date.iloc[0].date()),
        "end": str(eq.date.iloc[-1].date()),
        "total_return_pct": (e1 / e0 - 1) * 100,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "end_equity": e1,
        "n_trades": len(tr),
        "win_rate": float((tr.ret_pct > 0).mean()) if len(tr) else np.nan,
        "avg_trade_ret": float(tr.ret_pct.mean()) if len(tr) else np.nan,
        "avg_pos": float(eq.n_pos.mean()),
    }
    return eq, summary, tr


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("加载中证1000…")
    univ = load_zz1000()
    print(f"成分 {len(univ)} (已剔 ST/北交)")
    ensure_daily(univ)
    univ = univ[univ["symbol"].apply(lambda s: (UNIV_CACHE / f"{s}_daily_qfq.parquet").exists())].reset_index(drop=True)
    print(f"有日线 {len(univ)}")

    sig_cache = OUT / "signals.parquet"
    if sig_cache.exists():
        print(f"加载信号缓存 {sig_cache}")
        signals = pd.read_parquet(sig_cache)
    else:
        tasks = univ.to_dict(orient="records")
        rows = []
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(process_symbol, t): t for t in tasks}
            done = 0
            for fut in as_completed(futs):
                done += 1
                res = fut.result()
                rows.extend(res.get("signals") or [])
                if done % 20 == 0 or done == len(tasks):
                    print(f"  信号 {done}/{len(tasks)} (+{len(rows)}行, {time.time()-t0:.0f}s)")
        signals = pd.DataFrame(rows)
        signals.to_parquet(sig_cache, index=False)
        print(f"信号表 {len(signals)} → {sig_cache}")

    print(
        f"首板次日信号: {len(signals)}  "
        f"可买入 {(signals['entry']==True).sum() if len(signals) else 0}  "  # noqa: E712
        f"一字板 {(signals['reason']=='一字涨停开盘').sum() if len(signals) else 0}  "
        f"未触买点 {(signals['reason']=='未触买点').sum() if len(signals) else 0}"
    )

    summaries = []
    for mode in ("t1", "cont"):
        print(f"组合回测 mode={mode}")
        eq, summary, tr = run_portfolio(signals, mode)
        eq.to_csv(OUT / f"equity_{mode}.csv", index=False, encoding="utf-8-sig")
        tr.to_csv(OUT / f"trades_{mode}.csv", index=False, encoding="utf-8-sig")
        summaries.append(summary)
        print(
            f"  收益 {summary['total_return_pct']:.1f}%  回撤 {summary['max_drawdown_pct']:.1f}%  "
            f"夏普 {summary['sharpe_ratio']:.2f}  胜率 {summary['win_rate']*100:.1f}%  "
            f"笔数 {summary['n_trades']}"
        )

    sum_df = pd.DataFrame(summaries)
    sum_df.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=====")
    print(sum_df.to_string(index=False))


if __name__ == "__main__":
    main()
