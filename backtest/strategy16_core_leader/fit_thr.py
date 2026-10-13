"""策略十六 · 个股开盘阈值：2026 至今日线开盘突破 {2%, 2.5%, 3%} 夏普择优。

买/止损拟合用同一 thr（因子1 口径）；盯盘与近 7 日 1m 只用该 thr 做**开盘买入**，
卖出仍走因子26（硬保护 2.5% 等）。

用法：
  PYTHONPATH=. python backtest/strategy16_core_leader/fit_thr.py
  PYTHONPATH=. python backtest/strategy1_pool_1m/run.py --pool strategy16 --days 7 --fit-thr

研究用途，非投资建议。拟合窗含评价周时近 7 日 1m 有样本内重叠。
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import (  # noqa: E402
    code_key,
    load_core_leader_payload,
)
from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)

OUT_DIR = Path(__file__).resolve().parent
THR_PATH = OUT_DIR / "thr_2026.json"
CANDIDATES = (0.02, 0.025, 0.03)
FIT_START = "20260101"
DEFAULT_THR = float(DEFAULT_PCT)
TARGET_PCT = 0.95
LOT = 100


def simulate_open_break(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    *,
    thr: float,
    initial_cash: float = 100_000.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Local lightweight open-break replay for threshold fitting.

    Kept local so this script can run without importing backtest.factor1_monthly_top3,
    which pulls the whole strategy package during module initialization.
    """
    n = len(o)
    equity = np.empty(n, dtype=np.float64)
    holding_arr = np.zeros(n, dtype=np.int8)
    cash = float(initial_cash)
    shares = 0.0
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
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                    sell_px *= 1.0 - SLIP
                    proceeds = shares * sell_px
                    cash += proceeds - proceeds * COMMISSION - proceeds * STAMP
                    shares = 0.0
                    buy_i = -1
        elif i >= 1:
            po, pc = float(o[i - 1]), float(c[i - 1])
            allows = prev_day_allows_entry(
                po,
                pc,
                prev_small_yang_pct=thr,
                prev_entry_mode="yin_or_small_yang",
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
                raw = math.floor((cash * TARGET_PCT) / (px * LOT)) * LOT
                if raw >= LOT:
                    cost = raw * px
                    fee = cost * COMMISSION
                    if cost + fee <= cash:
                        cash -= cost + fee
                        shares = float(raw)
                        buy_i = i

        equity[i] = cash + shares * ci
        holding_arr[i] = 1 if shares > 0 else 0
    return equity, holding_arr


def _metrics_from_equity(equity: np.ndarray, close: np.ndarray) -> dict[str, float]:
    if len(equity) < 2 or equity[0] <= 0:
        return {
            "total_return_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "sharpe_ratio": np.nan,
            "bh_return_pct": np.nan,
            "bh_max_drawdown_pct": np.nan,
            "excess_return_pct": np.nan,
        }
    ret = equity[-1] / equity[0] - 1.0
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    max_dd = float(-dd.min()) * 100.0
    rets = np.diff(equity) / equity[:-1]
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(242))
        if len(rets) >= 5 and float(np.std(rets, ddof=1)) > 1e-12
        else 0.0
    )
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
    }


def _sina(code: str) -> str:
    c = str(code).zfill(6)
    return f"sh{c}" if c.startswith(("5", "6", "9")) else f"sz{c}"


def _n_trades(holding: np.ndarray) -> int:
    if holding is None or len(holding) < 2:
        return 0
    h = np.asarray(holding, dtype=int)
    return int(np.sum((h[1:] == 1) & (h[:-1] == 0)))


def load_fitted_thr_payload() -> dict[str, Any]:
    if not THR_PATH.is_file():
        return {}
    try:
        raw = json.loads(THR_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_fitted_thr_map() -> dict[str, float]:
    """code -> 开盘买入阈值。"""
    out: dict[str, float] = {}
    for code, rec in (load_fitted_thr_payload().get("thrs") or {}).items():
        c = code_key(str(code))
        if not c:
            continue
        if isinstance(rec, dict):
            thr = rec.get("thr")
        else:
            thr = rec
        try:
            out[c] = float(thr)
        except (TypeError, ValueError):
            continue
    return out


def _eval_thr(daily: pd.DataFrame, thr: float) -> dict[str, Any]:
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    equity, holding = simulate_open_break(o, h, l, c, thr=float(thr))
    m = _metrics_from_equity(equity, c)
    sharpe = m.get("sharpe_ratio")
    ret = m.get("total_return_pct")
    n_tr = _n_trades(holding)
    ok = n_tr > 0 and sharpe is not None and math.isfinite(float(sharpe))
    return {
        "thr": float(thr),
        "ok": bool(ok),
        "n_trades": int(n_tr),
        "sharpe": None if sharpe is None or not math.isfinite(float(sharpe)) else round(float(sharpe), 4),
        "ret_pct": None if ret is None or not math.isfinite(float(ret)) else round(float(ret), 2),
        "mdd_pct": (
            None
            if m.get("max_drawdown_pct") is None
            or not math.isfinite(float(m.get("max_drawdown_pct")))
            else round(float(m["max_drawdown_pct"]), 2)
        ),
        "excess_pct": (
            None
            if m.get("excess_return_pct") is None
            or not math.isfinite(float(m.get("excess_return_pct")))
            else round(float(m["excess_return_pct"]), 2)
        ),
    }


def _pick_best(grid: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [g for g in grid if g.get("ok")]
    if not scored:
        return {
            "thr": DEFAULT_THR,
            "fallback": True,
            "reason": "无成交或夏普不可用，回退 ±2.5%",
            "grid": grid,
        }
    scored.sort(
        key=lambda g: (
            float(g["sharpe"]),
            float(g["ret_pct"] or -1e9),
            -abs(float(g["thr"]) - DEFAULT_THR),
        ),
        reverse=True,
    )
    best = dict(scored[0])
    best["fallback"] = False
    best["grid"] = grid
    return best


def fit_strategy16_thresholds(
    *,
    start: str = FIT_START,
    end: str | None = None,
) -> dict[str, Any]:
    end = str(end or datetime.now().strftime("%Y%m%d"))
    payload = load_core_leader_payload()
    picks = payload.get("picks") or []
    if not picks:
        raise SystemExit("策略十六池为空。请先: python strategy/run_core_leader_pool.py")

    thrs: dict[str, Any] = {}
    print(
        f"策略十六开盘阈值拟合：日线开盘突破 {start}–{end} · "
        f"候选 {[round(x * 100, 1) for x in CANDIDATES]}% · 夏普择优"
    )
    for it in picks:
        code = code_key(str(it.get("code") or it.get("symbol") or ""))
        if not code or code == "000000":
            continue
        name = str(it.get("name") or code)
        sina = _sina(code)
        try:
            daily = fetch_daily(sina, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"  {code} {name} 日线失败: {e} → ±{DEFAULT_THR*100:.1f}%")
            thrs[code] = {
                "name": name,
                "thr": DEFAULT_THR,
                "fallback": True,
                "reason": str(e),
                "grid": [],
            }
            continue
        daily = daily.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
        if daily is None or len(daily) < 40:
            print(f"  {code} {name} 日线不足 → ±{DEFAULT_THR*100:.1f}%")
            thrs[code] = {
                "name": name,
                "thr": DEFAULT_THR,
                "fallback": True,
                "reason": f"n_bars={0 if daily is None else len(daily)}",
                "grid": [],
            }
            continue
        grid = [_eval_thr(daily, thr) for thr in CANDIDATES]
        best = _pick_best(grid)
        best["name"] = name
        best["n_bars"] = int(len(daily))
        thrs[code] = best
        gtxt = " / ".join(
            f"{g['thr']*100:.1f}%:{g['sharpe'] if g['sharpe'] is not None else '—'}n{g['n_trades']}"
            for g in grid
        )
        flag = "（回退）" if best.get("fallback") else ""
        print(
            f"  {code} {name}  ±{float(best['thr'])*100:.1f}%{flag}  "
            f"Sharpe {best.get('sharpe')}  ret {best.get('ret_pct')}%  {gtxt}"
        )

    dist: dict[str, int] = {}
    for rec in thrs.values():
        key = f"{float(rec.get('thr') or DEFAULT_THR)*100:.1f}"
        dist[key] = dist.get(key, 0) + 1
    out = {
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "fit_start": f"{start[:4]}-{start[4:6]}-{start[6:8]}",
        "fit_end": f"{end[:4]}-{end[4:6]}-{end[6:8]}",
        "rule": "日线开盘突破；买/止损同 thr；{2%,2.5%,3%} 夏普最高，并列看收益，再靠近 2.5%",
        "candidates": list(CANDIDATES),
        "default_thr": DEFAULT_THR,
        "n_pool": len(thrs),
        "thr_dist": dist,
        "disclaimer": "研究用途，非投资建议；拟合窗含评价周则近 7 日 1m 有样本内重叠。",
        "thrs": thrs,
    }
    THR_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写入 {THR_PATH}  分布 {dist}")
    return out


def main() -> None:
    fit_strategy16_thresholds()


if __name__ == "__main__":
    main()
