"""策略一·因子1：每月 Top3 换股回测（三种评分窗）。

评分（票内阈值 2%/2.5%/3% 择优；截面 5×超额分位+3×夏普分位+2×回撤改善分位）:
  1) month   — 仅评分月
  2) roll12  — 评分月末往前滚动 12 个自然月（如去年8月–今年8月）
  3) cum2020 — 2020-01 至评分月累计

换股规则（无前瞻）:
  月末 M 打出 Top3 → 在月份 M+1 作为目标池；
  持仓中若策略未卖出，不强制换股；空仓槽位再接入当前目标 Top3。

回测: 2020-01 → 最新缓存日。轻量日线模拟（对齐开盘突破核心规则，含佣金/印花税/滑点近似）。
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

from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)
from backtest.universe_zz500_1000 import (  # noqa: E402
    CACHE_DIR as UNIV_CACHE,
    CSINDEX_CONS_URL,
    _is_mainboard,
    _to_symbol,
)

OUT_DIR = Path(__file__).resolve().parent / "factor1_monthly_top3"
THRESHOLDS = (0.02, 0.025, 0.03)
W_EXCESS, W_SHARPE, W_DD = 5.0, 3.0, 2.0
TOP_N = 3
N_SLOTS = 3
WORKERS = 8
INITIAL_CASH = 300_000.0  # 三槽合计
COMMISSION = 0.0000854
STAMP = 0.001
SLIP = 0.001
TARGET_PCT = 0.95
LOT = 100
MIN_BARS_MONTH = 8
MIN_BARS_ROLL = 60
ORIGIN = pd.Timestamp("2020-01-01")


# ---------- universe ----------
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


def load_daily(symbol: str) -> pd.DataFrame | None:
    cache = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not cache.exists():
        return None
    df = pd.read_parquet(cache)
    if df is None or df.empty:
        return None
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[d["date"] >= pd.Timestamp("2019-01-01")].reset_index(drop=True)
    return d if len(d) else None


# ---------- lightweight open-break ----------
def simulate_open_break(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    *,
    thr: float,
    initial_cash: float = 100_000.0,
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (每日权益, 每日是否持仓 0/1)。从空仓开始。"""
    n = len(o)
    equity = np.empty(n, dtype=np.float64)
    holding_arr = np.zeros(n, dtype=np.int8)
    cash = float(initial_cash)
    shares = 0.0
    entry_px = 0.0
    buy_i = -1
    tick = TICK_SIZE

    for i in range(n):
        oi, hi, li, ci = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        if oi <= 0 or ci <= 0:
            equity[i] = cash + shares * (ci if ci > 0 else 0.0)
            holding_arr[i] = 1 if shares > 0 else 0
            continue

        buy_px = entry_trigger_price(oi, entry_pct=thr, tick=tick)
        stop_px = stop_trigger_price(oi, stop_pct=thr, tick=tick)

        if shares > 0:
            # T+1
            if i > buy_i and li <= stop_px + 1e-12:
                prev_c = float(c[i - 1]) if i > 0 else ci
                lim = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=0.10,
                    tick=tick,
                )
                if not bool(lim["locked"]):
                    sell_px = float(
                        lim["limit_px"] if bool(lim["opened"]) else stop_px
                    )
                    sell_px *= 1.0 - SLIP
                    proceeds = shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    cash += proceeds - fee
                    shares = 0.0
                    entry_px = 0.0
                    buy_i = -1
        else:
            # 需要前日
            if i >= 1:
                po, pc = float(o[i - 1]), float(c[i - 1])
                allows = prev_day_allows_entry(
                    po, pc, prev_small_yang_pct=thr, prev_entry_mode="yin_or_small_yang"
                )
                blocked = False
                if i >= 2:
                    blocked = should_block_entry_by_yang(
                        float(o[i - 2]),
                        float(c[i - 2]),
                        po,
                        pc,
                        tick=tick,
                        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                    )
                if allows and (not blocked) and (hi + 1e-12 >= buy_px):
                    px = buy_px * (1.0 + SLIP)
                    budget = cash * TARGET_PCT
                    raw = math.floor(budget / (px * LOT)) * LOT
                    if raw >= LOT:
                        cost = raw * px
                        fee = cost * COMMISSION
                        if cost + fee <= cash:
                            cash -= cost + fee
                            shares = float(raw)
                            entry_px = px
                            buy_i = i

        mark = ci
        equity[i] = cash + shares * mark
        holding_arr[i] = 1 if shares > 0 else 0

    return equity, holding_arr


def _metrics_from_equity(
    equity: np.ndarray, close: np.ndarray
) -> dict[str, float]:
    if len(equity) < 2 or equity[0] <= 0:
        return {
            "total_return_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "sharpe_ratio": np.nan,
            "bh_return_pct": np.nan,
            "bh_max_drawdown_pct": np.nan,
            "excess_return_pct": np.nan,
            "dd_improve_pct": np.nan,
        }
    ret = equity[-1] / equity[0] - 1.0
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    max_dd = float(-dd.min()) * 100.0
    rets = np.diff(equity) / equity[:-1]
    rets = rets[np.isfinite(rets)]
    if len(rets) >= 5 and float(np.std(rets, ddof=1)) > 1e-12:
        sharpe = float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(242))
    else:
        sharpe = 0.0
    c0, c1 = float(close[0]), float(close[-1])
    bh = (c1 / c0 - 1.0) * 100.0 if c0 > 0 else np.nan
    cpeak = np.maximum.accumulate(close.astype(float))
    cdd = close / cpeak - 1.0
    bh_dd = float(-cdd.min()) * 100.0
    strat = ret * 100.0
    return {
        "total_return_pct": strat,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "bh_return_pct": bh,
        "bh_max_drawdown_pct": bh_dd,
        "excess_return_pct": strat - bh if np.isfinite(bh) else np.nan,
        "dd_improve_pct": bh_dd - max_dd if np.isfinite(bh_dd) else np.nan,
    }


def _month_ends(dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(np.arange(len(dates)), index=dates)
    return [pd.Timestamp(x) for x in s.groupby(dates.to_period("M")).apply(lambda x: x.index.max())]


def process_symbol(task: dict) -> dict:
    """单票：三种窗的月末指标 + 全区间逐日交易轨迹（各阈值）。"""
    symbol = task["symbol"]
    code = task["code"]
    name = task["name"]
    daily = load_daily(symbol)
    out = {
        "symbol": symbol,
        "code": code,
        "name": name,
        "month_rows": [],
        "paths": {},  # thr -> {dates, equity, holding, close}
        "ok": 0,
        "error": "",
    }
    if daily is None or daily.empty:
        out["error"] = "no_daily"
        return out

    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)

    # 交易/评分起点
    mask2020 = np.asarray(dates >= ORIGIN)
    if int(mask2020.sum()) < MIN_BARS_ROLL:
        out["error"] = "too_short"
        return out

    month_ends = _month_ends(dates[mask2020])
    # 需要 2019 数据做滚动，month_ends 从 2020 起

    for thr in THRESHOLDS:
        # 全样本模拟：供组合交易路径（自 2019 数据起，输出截 2020）
        eq_all, hold_all = simulate_open_break(
            o, h, l, c, thr=thr, initial_cash=100_000.0
        )
        idx0 = int(np.argmax(mask2020))
        out["paths"][str(thr)] = {
            "dates": [str(x.date()) for x in dates[idx0:]],
            "equity": eq_all[idx0:].astype(np.float64).tolist(),
            "holding": hold_all[idx0:].astype(int).tolist(),
            "close": c[idx0:].astype(np.float64).tolist(),
            "open": o[idx0:].astype(np.float64).tolist(),
            "high": h[idx0:].astype(np.float64).tolist(),
            "low": l[idx0:].astype(np.float64).tolist(),
        }

        # 累计：2020 起只模拟一次，按月末截断取指标
        i_c0 = int(dates.get_indexer([ORIGIN], method="bfill")[0])
        eq_cum, _ = simulate_open_break(
            o[i_c0:], h[i_c0:], l[i_c0:], c[i_c0:], thr=thr
        )
        dates_cum = dates[i_c0:]

        for me in month_ends:
            i_end = int(dates.get_indexer([me], method="pad")[0])
            if i_end < 1:
                continue
            period = me.to_period("M")

            # --- month window ---
            m_start = pd.Timestamp(period.start_time).normalize()
            i_m0 = int(dates.get_indexer([m_start], method="bfill")[0])
            if i_m0 < 0 or i_end - i_m0 + 1 < MIN_BARS_MONTH:
                m_ok, m_met = False, {}
            else:
                m_ok = True
                eq_m, _ = simulate_open_break(
                    o[i_m0 : i_end + 1],
                    h[i_m0 : i_end + 1],
                    l[i_m0 : i_end + 1],
                    c[i_m0 : i_end + 1],
                    thr=thr,
                )
                m_met = _metrics_from_equity(eq_m, c[i_m0 : i_end + 1])

            # --- roll12 ---
            r_start = (me - pd.DateOffset(years=1) + pd.Timedelta(days=1)).normalize()
            if r_start < dates[0]:
                r_start = dates[0]
            i_r0 = int(dates.get_indexer([r_start], method="bfill")[0])
            if i_r0 < 0 or i_end - i_r0 + 1 < MIN_BARS_ROLL:
                r_ok, r_met = False, {}
            else:
                r_ok = True
                eq_r, _ = simulate_open_break(
                    o[i_r0 : i_end + 1],
                    h[i_r0 : i_end + 1],
                    l[i_r0 : i_end + 1],
                    c[i_r0 : i_end + 1],
                    thr=thr,
                )
                r_met = _metrics_from_equity(eq_r, c[i_r0 : i_end + 1])

            # --- cum2020 ---
            i_rel = int(dates_cum.get_indexer([me], method="pad")[0])
            if i_rel < MIN_BARS_MONTH:
                c_ok, c_met = False, {}
            else:
                c_ok = True
                c_met = _metrics_from_equity(
                    eq_cum[: i_rel + 1], c[i_c0 : i_c0 + i_rel + 1]
                )

            row = {
                "symbol": symbol,
                "code": code,
                "name": name,
                "threshold_pct": thr,
                "score_month": str(period),
                "month_end": str(me.date()),
            }
            for prefix, ok, met in (
                ("month", m_ok, m_met),
                ("roll12", r_ok, r_met),
                ("cum2020", c_ok, c_met),
            ):
                row[f"{prefix}_ok"] = int(ok)
                for k, v in met.items():
                    row[f"{prefix}_{k}"] = v
            out["month_rows"].append(row)

    out["ok"] = 1
    return out


def run_metric_pool(univ: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = OUT_DIR / "month_symbol_threshold_metrics.parquet"
    if cache.exists() and not force:
        print(f"加载指标缓存 {cache}")
        return pd.read_parquet(cache)

    tasks = univ.to_dict(orient="records")
    rows = []
    path_dir = OUT_DIR / "paths"
    path_dir.mkdir(exist_ok=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_symbol, t): t for t in tasks}
        done = 0
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            if res.get("month_rows"):
                rows.extend(res["month_rows"])
            if res.get("ok") and res.get("paths"):
                # 路径较大，按票存
                np.savez_compressed(
                    path_dir / f"{res['symbol']}.npz",
                    **{
                        f"thr_{k.replace('.', '_')}": np.array(v["equity"], dtype=np.float64)
                        for k, v in res["paths"].items()
                    },
                    **{
                        f"hold_{k.replace('.', '_')}": np.array(v["holding"], dtype=np.int8)
                        for k, v in res["paths"].items()
                    },
                    **{
                        f"close_{k.replace('.', '_')}": np.array(v["close"], dtype=np.float64)
                        for k, v in res["paths"].items()
                    },
                    **{
                        f"open_{k.replace('.', '_')}": np.array(v["open"], dtype=np.float64)
                        for k, v in res["paths"].items()
                    },
                    **{
                        f"high_{k.replace('.', '_')}": np.array(v["high"], dtype=np.float64)
                        for k, v in res["paths"].items()
                    },
                    **{
                        f"low_{k.replace('.', '_')}": np.array(v["low"], dtype=np.float64)
                        for k, v in res["paths"].items()
                    },
                    dates=np.array(res["paths"][str(THRESHOLDS[0])]["dates"]),
                )
            if done % 20 == 0 or done == len(tasks):
                print(f"  指标进度 {done}/{len(tasks)} ({time.time()-t0:.0f}s) rows={len(rows)}")

    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    print(f"指标表 {len(df)} → {cache}")
    return df


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def build_monthly_top3(metrics: pd.DataFrame, mode: str) -> pd.DataFrame:
    """mode: month | roll12 | cum2020。每月每票择优阈值后截面评分取 Top3。"""
    ok_col = f"{mode}_ok"
    ex_col = f"{mode}_excess_return_pct"
    sh_col = f"{mode}_sharpe_ratio"
    dd_col = f"{mode}_dd_improve_pct"
    ret_col = f"{mode}_total_return_pct"
    sub = metrics[metrics[ok_col] == 1].copy()
    # 票×月 择优
    best_rows = []
    for (_, _), g in sub.groupby(["score_month", "symbol"]):
        g = g.copy()
        for col in (ex_col, sh_col, dd_col):
            v = g[col].astype(float)
            if v.nunique() <= 1 or float(v.std(ddof=0) or 0) == 0:
                g[f"r_{col}"] = 0.5
            else:
                g[f"r_{col}"] = (v - v.min()) / (v.max() - v.min())
        g["thr_score"] = (
            W_EXCESS * g[f"r_{ex_col}"]
            + W_SHARPE * g[f"r_{sh_col}"]
            + W_DD * g[f"r_{dd_col}"]
        )
        best_rows.append(g.loc[g["thr_score"].idxmax()])
    best = pd.DataFrame(best_rows)
    parts = []
    for month, g in best.groupby("score_month"):
        g = g.copy()
        g["pct_ex"] = _pct_rank(g[ex_col].astype(float))
        g["pct_sh"] = _pct_rank(g[sh_col].astype(float))
        g["pct_dd"] = _pct_rank(g[dd_col].astype(float))
        g["score"] = W_EXCESS * g["pct_ex"] + W_SHARPE * g["pct_sh"] + W_DD * g["pct_dd"]
        g = g.sort_values("score", ascending=False)
        g["rank"] = range(1, len(g) + 1)
        g["score_mode"] = mode
        top = g[g["rank"] <= TOP_N][
            [
                "score_mode",
                "score_month",
                "month_end",
                "rank",
                "symbol",
                "code",
                "name",
                "threshold_pct",
                "score",
                ret_col,
                ex_col,
                sh_col,
                dd_col,
            ]
        ].rename(
            columns={
                ret_col: "select_ret",
                ex_col: "select_excess",
                sh_col: "select_sharpe",
                dd_col: "select_dd_improve",
            }
        )
        parts.append(top)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------- portfolio: wait for strategy exit then rotate ----------
@dataclass
class Slot:
    cash: float
    symbol: str | None = None
    thr: float | None = None
    shares: float = 0.0
    buy_i: int = -1  # index in that symbol's path
    entry_px: float = 0.0


def _load_path(symbol: str, thr: float) -> dict | None:
    p = OUT_DIR / "paths" / f"{symbol}.npz"
    if not p.exists():
        return None
    z = np.load(p, allow_pickle=True)
    key = str(thr).replace(".", "_")
    dates = pd.to_datetime(z["dates"])
    return {
        "dates": dates,
        "date_to_i": {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)},
        "open": z[f"open_{key}"],
        "high": z[f"high_{key}"],
        "low": z[f"low_{key}"],
        "close": z[f"close_{key}"],
    }


def run_portfolio(top3: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """按「月末Top3 → 次月交易；持仓等策略卖出再换」回测。"""
    sample = next((OUT_DIR / "paths").glob("*.npz"))
    cal = pd.to_datetime(np.load(sample)["dates"])
    cal = cal[cal >= ORIGIN]

    by_score: dict[str, list] = {}
    for _, r in top3.iterrows():
        by_score.setdefault(r["score_month"], []).append(
            {
                "symbol": r["symbol"],
                "thr": float(r["threshold_pct"]),
                "rank": int(r["rank"]),
                "code": r["code"],
                "name": r["name"],
            }
        )
    for k in by_score:
        by_score[k] = sorted(by_score[k], key=lambda x: x["rank"])

    trade_targets: dict[str, list] = {}
    for sm in by_score:
        p = pd.Period(sm, freq="M")
        trade_targets[str(p + 1)] = by_score[sm]

    path_cache: dict[tuple[str, float], dict] = {}

    def get_path(sym: str, thr: float):
        key = (sym, float(thr))
        if key not in path_cache:
            path_cache[key] = _load_path(sym, float(thr))
        return path_cache[key]

    def bar(path: dict, dt: pd.Timestamp):
        j = path["date_to_i"].get(dt)
        if j is None:
            return None
        return j, float(path["open"][j]), float(path["high"][j]), float(path["low"][j]), float(path["close"][j])

    slot_cash0 = INITIAL_CASH / N_SLOTS
    slots = [Slot(cash=slot_cash0) for _ in range(N_SLOTS)]
    equity_rows = []
    events = []
    target: list[dict] = []
    prev_month = None

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        trade_m = str(dt.to_period("M"))
        if trade_m != prev_month:
            if trade_m in trade_targets:
                target = trade_targets[trade_m]
            prev_month = trade_m

        # 1) 止损
        for si, slot in enumerate(slots):
            if not slot.symbol or slot.shares <= 0:
                continue
            path = get_path(slot.symbol, slot.thr)
            if path is None:
                continue
            b = bar(path, dt)
            if b is None:
                continue
            j, oi, hi, li, ci = b
            thr = float(slot.thr)
            stop_px = stop_trigger_price(oi, stop_pct=thr)
            if j > slot.buy_i and li <= stop_px + 1e-12:
                # prev close
                prev_keys = [d for d in path["date_to_i"] if d < dt]
                prev_c = ci
                if prev_keys:
                    pj = path["date_to_i"][max(prev_keys)]
                    prev_c = float(path["close"][pj])
                lim = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=0.10,
                    tick=TICK_SIZE,
                )
                if not bool(lim["locked"]):
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                    sell_px *= 1.0 - SLIP
                    proceeds = slot.shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    events.append(
                        {
                            "date": str(dt.date()),
                            "mode": mode,
                            "slot": si,
                            "side": "sell",
                            "symbol": slot.symbol,
                            "thr": thr,
                            "px": sell_px,
                            "shares": slot.shares,
                        }
                    )
                    slot.shares = 0.0
                    slot.symbol = None
                    slot.thr = None
                    slot.buy_i = -1
                    slot.entry_px = 0.0

        held_syms = {s.symbol for s in slots if s.symbol and s.shares > 0}
        pending = {s.symbol for s in slots if s.symbol and s.shares <= 0}

        # 2) 空槽分配 + 买入
        if target:
            target_syms = {t["symbol"] for t in target}
            for slot in slots:
                if slot.shares <= 0 and slot.symbol and slot.symbol not in target_syms:
                    slot.symbol = None
                    slot.thr = None
            pending = {s.symbol for s in slots if s.symbol and s.shares <= 0}

            for si, slot in enumerate(slots):
                if slot.shares > 0:
                    continue
                if slot.symbol is None:
                    assign = None
                    for t in target:
                        if t["symbol"] in held_syms or t["symbol"] in pending:
                            continue
                        if any(s.symbol == t["symbol"] for s in slots if s is not slot):
                            continue
                        assign = t
                        break
                    if assign is None:
                        continue
                    slot.symbol = assign["symbol"]
                    slot.thr = assign["thr"]
                    pending.add(slot.symbol)
                    events.append(
                        {
                            "date": str(dt.date()),
                            "mode": mode,
                            "slot": si,
                            "side": "assign",
                            "symbol": slot.symbol,
                            "thr": slot.thr,
                            "px": np.nan,
                            "shares": 0,
                        }
                    )

                path = get_path(slot.symbol, float(slot.thr))
                if path is None:
                    continue
                b = bar(path, dt)
                if b is None:
                    continue
                j, oi, hi, li, ci = b
                thr = float(slot.thr)
                buy_px = entry_trigger_price(oi, entry_pct=thr)
                prev_dates = sorted(d for d in path["date_to_i"] if d < dt)
                if len(prev_dates) < 1:
                    continue
                j1 = path["date_to_i"][prev_dates[-1]]
                po, pc = float(path["open"][j1]), float(path["close"][j1])
                allows = prev_day_allows_entry(
                    po, pc, prev_small_yang_pct=thr, prev_entry_mode="yin_or_small_yang"
                )
                blocked = False
                if len(prev_dates) >= 2:
                    j2 = path["date_to_i"][prev_dates[-2]]
                    blocked = should_block_entry_by_yang(
                        float(path["open"][j2]),
                        float(path["close"][j2]),
                        po,
                        pc,
                        tick=TICK_SIZE,
                        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                    )
                if allows and (not blocked) and (hi + 1e-12 >= buy_px) and slot.cash > 0:
                    px = buy_px * (1.0 + SLIP)
                    budget = slot.cash * TARGET_PCT
                    raw = math.floor(budget / (px * LOT)) * LOT
                    if raw >= LOT:
                        cost = raw * px
                        fee = cost * COMMISSION
                        if cost + fee <= slot.cash:
                            slot.cash -= cost + fee
                            slot.shares = float(raw)
                            slot.entry_px = px
                            slot.buy_i = j
                            held_syms.add(slot.symbol)
                            events.append(
                                {
                                    "date": str(dt.date()),
                                    "mode": mode,
                                    "slot": si,
                                    "side": "buy",
                                    "symbol": slot.symbol,
                                    "thr": thr,
                                    "px": px,
                                    "shares": slot.shares,
                                }
                            )

        # 3) 盯市
        total = 0.0
        for slot in slots:
            if slot.symbol and slot.shares > 0:
                path = get_path(slot.symbol, float(slot.thr))
                b = bar(path, dt) if path else None
                if b is not None:
                    total += slot.cash + slot.shares * b[4]
                else:
                    total += slot.cash + slot.shares * slot.entry_px
            else:
                total += slot.cash
        equity_rows.append(
            {
                "date": str(dt.date()),
                "mode": mode,
                "equity": total,
                "n_held": sum(1 for s in slots if s.shares > 0),
            }
        )

    eq = pd.DataFrame(equity_rows)
    eq["date"] = pd.to_datetime(eq["date"])
    e0 = float(eq["equity"].iloc[0])
    e1 = float(eq["equity"].iloc[-1])
    rets = eq["equity"].pct_change().dropna()
    peak = eq["equity"].cummax()
    dd = eq["equity"] / peak - 1.0
    max_dd = float(-dd.min()) * 100.0
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * math.sqrt(242))
        if len(rets) > 5 and rets.std(ddof=1) > 0
        else 0.0
    )
    summary = {
        "mode": mode,
        "start": str(eq["date"].iloc[0].date()),
        "end": str(eq["date"].iloc[-1].date()),
        "total_return_pct": (e1 / e0 - 1.0) * 100.0,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "end_equity": e1,
        "n_events": len(events),
        "avg_held": float(eq["n_held"].mean()),
    }
    return eq, summary, pd.DataFrame(events)


def main() -> None:
    print("加载宇宙…")
    univ = load_zz1000_mainboard()
    # 只保留有缓存的
    univ = univ[
        univ["symbol"].apply(lambda s: (UNIV_CACHE / f"{s}_daily_qfq.parquet").exists())
    ].reset_index(drop=True)
    print(f"有日线缓存: {len(univ)}")

    metrics = run_metric_pool(univ, force=False)

    tops = {}
    for mode in ("month", "roll12", "cum2020"):
        print(f"构建 Top3: {mode}")
        top = build_monthly_top3(metrics, mode)
        top.to_csv(OUT_DIR / f"top3_{mode}.csv", index=False, encoding="utf-8-sig")
        tops[mode] = top
        print(f"  {len(top)} 行")

    summaries = []
    eq_all = []
    for mode, top in tops.items():
        print(f"组合回测: {mode}")
        eq, summary, events = run_portfolio(top, mode)
        eq.to_csv(OUT_DIR / f"equity_{mode}.csv", index=False, encoding="utf-8-sig")
        events.to_csv(OUT_DIR / f"events_{mode}.csv", index=False, encoding="utf-8-sig")
        summaries.append(summary)
        eq_all.append(eq)
        print(
            f"  收益 {summary['total_return_pct']:.1f}%  "
            f"回撤 {summary['max_drawdown_pct']:.1f}%  "
            f"夏普 {summary['sharpe_ratio']:.2f}"
        )

    sum_df = pd.DataFrame(summaries)
    sum_df.to_csv(OUT_DIR / "portfolio_summary.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "portfolio_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n===== 三种口径组合对比 =====")
    print(sum_df.to_string(index=False))


if __name__ == "__main__":
    main()
