"""CF1 研究：面板、指标、分割、调参与验证。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.cf1_liquidity_gated_reversal import (
    DEFAULT_PARAMS,
    compute_cf1,
)

_MYQUAN = Path(__file__).resolve().parents[2]
CACHE_DIR = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
OHLC_PANEL = _MYQUAN / "backtest" / "zz1000_momentum_select" / "panel_ohlc_zz500_1000.parquet"
OUT_DIR = Path(__file__).resolve().parent
PANEL_PATH = OUT_DIR / "panel_ohlcv.parquet"

DISCOVERY = ("2018-01-02", "2022-12-31")
VALIDATION = ("2023-01-01", "2024-12-31")
TEST = ("2025-01-01", None)
EMBARGO_BARS = 20
ONE_WAY_COST = 0.0015  # evaluation.md 单边 15bp
MIN_NAMES = 30


def load_ohlcv(*, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """OHLC 复用已有宽表，成交量从日线缓存对齐写入。"""
    if PANEL_PATH.exists() and not refresh:
        wide = pd.read_parquet(PANEL_PATH)
        return {f: wide[f] for f in ("open", "high", "low", "close", "volume")}

    if not OHLC_PANEL.exists():
        raise FileNotFoundError(f"缺少 OHLC 面板 {OHLC_PANEL}")
    wide = pd.read_parquet(OHLC_PANEL)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    volumes = pd.DataFrame(index=closes.index, columns=closes.columns, dtype=float)
    t0 = time.time()
    n = 0
    for i, sym in enumerate(closes.columns, 1):
        path = CACHE_DIR / f"{sym}_daily_qfq.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path, columns=["date", "volume"])
        d["d"] = pd.to_datetime(d["date"]).dt.tz_convert("Asia/Shanghai").dt.normalize()
        s = d.drop_duplicates("d").set_index("d")["volume"].astype(float)
        volumes[sym] = s.reindex(closes.index)
        n += 1
        if i % 200 == 0:
            print(f"  volume {i}/{closes.shape[1]} ok={n} ({time.time()-t0:.1f}s)", flush=True)
    out = pd.concat(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        axis=1,
    )
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(PANEL_PATH)
    print(f"写入 {PANEL_PATH} close={closes.shape} vol_ok={n}")
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}


def _tz(ts: str, idx: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def slice_dates(
    df: pd.DataFrame,
    start: str,
    end: str | None,
    *,
    embargo_after_start: int = 0,
) -> pd.DataFrame:
    idx = df.index
    a = _tz(start, idx)
    out = df.loc[df.index >= a]
    if embargo_after_start > 0 and len(out.index) > embargo_after_start:
        cut = out.index[embargo_after_start]
        out = out.loc[out.index >= cut]
    if end is not None:
        b = _tz(end, idx)
        out = out.loc[out.index <= b]
    return out


def split_mask(index: pd.DatetimeIndex, split: str) -> pd.Series:
    start, end = {"discovery": DISCOVERY, "validation": VALIDATION, "test": TEST}[split]
    a = _tz(start, index)
    m = index >= a
    if end is not None:
        m &= index <= _tz(end, index)
    if split == "validation":
        # 发现集结束后隔离 20 个交易日
        disc_end = _tz(DISCOVERY[1], index)
        after = index[index > disc_end]
        if len(after) >= EMBARGO_BARS:
            m &= index >= after[EMBARGO_BARS - 1]
    if split == "test":
        val_end = _tz(VALIDATION[1], index)
        after = index[index > val_end]
        if len(after) >= EMBARGO_BARS:
            m &= index >= after[EMBARGO_BARS - 1]
    return pd.Series(m, index=index)


def forward_open_return(opens: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """T 收盘信号 → 用 open[T+1+H]/open[T+1]-1。"""
    h = int(horizon)
    entry = opens.shift(-1)
    exit_px = opens.shift(-(1 + h))
    fwd = exit_px / entry - 1.0
    return fwd.replace([np.inf, -np.inf], np.nan)


def _xs_corr(x: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
    x = x.sub(x.mean(axis=1), axis=0)
    y = y.sub(y.mean(axis=1), axis=0)
    num = (x * y).sum(axis=1)
    den = np.sqrt((x ** 2).sum(axis=1) * (y ** 2).sum(axis=1))
    return num / den.replace(0, np.nan)


def both_ic(signal: pd.DataFrame, fwd: pd.DataFrame) -> dict[str, Any]:
    aligned = signal.reindex_like(fwd)
    n = aligned.notna().sum(axis=1)
    ok = n >= MIN_NAMES
    aligned = aligned.where(ok, np.nan)
    y = fwd.where(aligned.notna())
    rank_ic = _xs_corr(aligned.rank(axis=1), y.rank(axis=1))
    pearson_ic = _xs_corr(aligned, y)
    rank_ic = rank_ic.where(ok)
    pearson_ic = pearson_ic.where(ok)
    ric = rank_ic.dropna()
    pic = pearson_ic.dropna()
    ir = float(ric.mean() / ric.std(ddof=0) * np.sqrt(252)) if len(ric) > 5 and ric.std(ddof=0) else float("nan")
    return {
        "rank_ic_mean": float(ric.mean()) if len(ric) else float("nan"),
        "rank_ic_ir": ir,
        "pearson_ic_mean": float(pic.mean()) if len(pic) else float("nan"),
        "n_ic_days": int(len(ric)),
        "rank_ic": rank_ic,
        "pearson_ic": pearson_ic,
        "coverage": float(ok.mean()),
    }


def monotonicity(signal: pd.DataFrame, fwd: pd.DataFrame, n_groups: int = 5) -> float:
    rank = signal.rank(axis=1, pct=True)
    means = []
    for q in range(n_groups):
        lo, hi = q / n_groups, (q + 1) / n_groups
        mask = (rank > lo) & (rank <= hi)
        means.append(float(fwd.where(mask).mean(axis=1).mean()))
    if not np.isfinite(means).all():
        return float("nan")
    return float(np.corrcoef(np.arange(n_groups), means)[0, 1])


def group_returns(signal: pd.DataFrame, fwd: pd.DataFrame, n_groups: int = 5) -> list[float]:
    rank = signal.rank(axis=1, pct=True)
    out = []
    for q in range(n_groups):
        lo, hi = q / n_groups, (q + 1) / n_groups
        mask = (rank > lo) & (rank <= hi)
        out.append(float(fwd.where(mask).mean(axis=1).mean()))
    return out


def _long_sleeve_vectorized(
    signal: pd.DataFrame,
    opens: pd.DataFrame,
    h: int,
    top_frac: float,
    one_way_cost: float,
) -> dict[str, Any]:
    aligned = signal.reindex(opens.index)
    n_ok = aligned.notna().sum(axis=1)
    aligned = aligned.where(n_ok >= MIN_NAMES)
    rank = aligned.rank(axis=1, pct=True)
    long_m = rank >= (1.0 - float(top_frac))
    w = long_m.div(long_m.sum(axis=1).replace(0, np.nan), axis=0)
    w = w.fillna(0.0)

    entry = opens.shift(-1)
    exit_px = opens.shift(-(1 + h))
    stock_h = exit_px / entry - 1.0
    # 信号日 T 的权重，收益在 T+1 到 T+1+H；记到卖出日
    port_h = (w * stock_h).sum(axis=1)
    # 换手：相对 H 日前权重（同一袖套）
    w_prev_sleeve = w.shift(h)
    to_one_way = 0.5 * (w - w_prev_sleeve.fillna(0.0)).abs().sum(axis=1)
    to_one_way = to_one_way.where(w_prev_sleeve.sum(axis=1) > 0, w.sum(axis=1))
    net_h = port_h - to_one_way * float(one_way_cost) * 2.0 / max(h, 1)
    # 上式把双边摊到 H 日持有；更直接：每次换仓扣 one_way*(买+卖)
    trade_cost = to_one_way * float(one_way_cost) * 2.0
    net_h = port_h - trade_cost

    # 把 H 日收益放到卖出时点后，日收益近似 net_h / h 从 T+1 起
    daily = (1.0 + net_h) ** (1.0 / h) - 1.0
    daily = daily.shift(1)  # 成交从次日开始
    daily = daily.dropna()
    if daily.empty:
        return {
            "ann_ret": float("nan"),
            "sharpe": float("nan"),
            "max_dd": float("nan"),
            "ann_turnover": float("nan"),
            "n_days": 0,
            "daily": daily,
        }
    ann_ret = float((1.0 + daily).prod() ** (252.0 / len(daily)) - 1.0)
    vol = float(daily.std(ddof=0) * np.sqrt(252)) if daily.std(ddof=0) else float("nan")
    sharpe = float(ann_ret / vol) if vol and np.isfinite(vol) else float("nan")
    nav = (1.0 + daily).cumprod()
    max_dd = float((nav / nav.cummax() - 1.0).min())
    ann_to = float(to_one_way.reindex(daily.index).mean() * (252.0 / h))
    return {
        "ann_ret": ann_ret,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "ann_turnover": ann_to,
        "n_days": int(len(daily)),
        "daily": daily,
        "nav": nav,
        "gross_h_mean": float(port_h.mean()),
        "net_h_mean": float(net_h.mean()),
    }


def primary_score(
    rank_ic_ir: float,
    sharpe: float,
    ann_ret: float,
    max_dd: float,
    mono: float,
    ann_turnover: float,
) -> float:
    """evaluation.md / factor-evaluate v2。"""

    def clip(x: float, lo: float, hi: float) -> float:
        if not np.isfinite(x):
            return 0.0
        return max(lo, min(hi, x))

    ic_term = clip(rank_ic_ir / 3.0, -2, 2)
    shp_term = clip((sharpe + 0.5) / 1.0, -2, 2)
    ret_term = clip(ann_ret / 0.10, -2, 2)
    mdd_term = clip(1 + max_dd / 0.30, -2, 1)
    mono_term = clip(mono, -1, 1)
    turn_term = -clip(ann_turnover / 30.0 - 1.0, 0, 3)
    return float(
        0.20 * ic_term
        + 0.30 * shp_term
        + 0.30 * ret_term
        + 0.20 * mdd_term
        + 0.10 * mono_term
        + 0.10 * turn_term
    )


def evaluate_split(
    signal: pd.DataFrame,
    opens: pd.DataFrame,
    *,
    split: str,
    horizon: int,
    top_frac: float,
) -> dict[str, Any]:
    mask = split_mask(opens.index, split)
    sig = signal.loc[mask.values]
    op = opens.loc[mask.values]
    fwd = forward_open_return(op, horizon)
    mn = fwd.sub(fwd.mean(axis=1), axis=0)
    ic = both_ic(sig, mn)
    groups = group_returns(sig, mn, 5)
    mono = monotonicity(sig, mn, 5)
    port = _long_sleeve_vectorized(sig, op, horizon, top_frac, ONE_WAY_COST)
    score = primary_score(
        ic["rank_ic_ir"],
        port["sharpe"],
        port["ann_ret"],
        port["max_dd"],
        mono,
        port["ann_turnover"],
    )
    ls = float(groups[-1] - groups[0]) if groups and np.isfinite(groups).all() else float("nan")
    return {
        "split": split,
        "horizon": int(horizon),
        "rank_ic_mean": ic["rank_ic_mean"],
        "rank_ic_ir": ic["rank_ic_ir"],
        "pearson_ic_mean": ic["pearson_ic_mean"],
        "n_ic_days": ic["n_ic_days"],
        "coverage": ic["coverage"],
        "mono": mono,
        "ls_spread": ls,
        "g1": groups[0] if groups else float("nan"),
        "g5": groups[-1] if groups else float("nan"),
        "ann_ret": port["ann_ret"],
        "sharpe": port["sharpe"],
        "max_dd": port["max_dd"],
        "ann_turnover": port["ann_turnover"],
        "n_days": port["n_days"],
        "score": score,
        "rank_ic_series": ic["rank_ic"],
        "nav": port.get("nav"),
        "daily": port.get("daily"),
    }


def evaluate_params(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    opens: pd.DataFrame,
    params: dict[str, Any],
    *,
    split: str,
    high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **params}
    sig = compute_cf1(close, volume, high=high, low=low, params=p)
    ev = evaluate_split(
        sig,
        opens,
        split=split,
        horizon=int(p["horizon"]),
        top_frac=float(p["top_frac"]),
    )
    ev["params"] = p
    return ev


def metrics_row(ev: dict[str, Any], *, name: str) -> dict[str, Any]:
    p = ev.get("params") or {}
    return {
        "name": name,
        "split": ev["split"],
        "rev_n": p.get("rev_n"),
        "amihud_n": p.get("amihud_n"),
        "gate_lo": p.get("gate_lo"),
        "gate_mode": p.get("gate_mode"),
        "vol_scale": p.get("vol_scale"),
        "skip_days": p.get("skip_days"),
        "adv_floor": p.get("adv_floor"),
        "limit_gate": p.get("limit_gate"),
        "trend_gate": p.get("trend_gate"),
        "vol_gate": p.get("vol_gate"),
        "horizon": ev["horizon"],
        "rank_ic_mean": ev["rank_ic_mean"],
        "rank_ic_ir": ev["rank_ic_ir"],
        "pearson_ic_mean": ev["pearson_ic_mean"],
        "mono": ev["mono"],
        "ls_spread": ev["ls_spread"],
        "ann_ret": ev["ann_ret"],
        "sharpe": ev["sharpe"],
        "max_dd": ev["max_dd"],
        "ann_turnover": ev["ann_turnover"],
        "coverage": ev["coverage"],
        "n_ic_days": ev["n_ic_days"],
        "score": ev["score"],
    }


def dump_json(path: Path, obj: Any) -> None:
    def conv(x):
        if isinstance(x, (np.floating,)):
            return float(x)
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, pd.Timestamp):
            return str(x)
        return x

    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=conv), encoding="utf-8")
