"""AI应用池 · 策略1 / 策略11 三段分析（无因子13过门）。

调参 FIT : 2020-01-01 → 2023-12-31  （thr ∈ {2%, 2.5%, 3%} 逐票择优）
验证 VAL : 2023-01-01 → 2024-12-31  （冻结 FIT 阈值）
样本外 OOS: 2025-01-01 → 今

策略1：开盘突破权益曲线 → 盈亏比 / 超额 / 回撤
策略11：同套因子1成交 + 日线笔归因 → 盈亏比；超额/回撤沿用因子1权益

  python backtest/ai_s1_s11_periods.py --cache-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import _metrics_from_equity  # noqa: E402
from strategy.bi_pl_ratio import analyze_bi_pl_ratio  # noqa: E402
from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
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

OUT_DIR = _MYQUAN / "backtest" / "ai_s1_s11_periods"
CACHE_DIR = _MYQUAN / "data_cache" / "ai_concept"
DEFAULT_UNIVERSE = _MYQUAN / "backtest" / "ai_concept_f1_f13" / "universe_ai_app_em.csv"

FIT_START, FIT_END = "20200101", "20231231"
VAL_START, VAL_END = "20230101", "20241231"
OOS_START = "20250101"
FULL_START = "20200101"

THR_GRID = (0.02, 0.025, 0.03)
INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT = 100
MIN_BARS = 60
MIN_TRADES = 5
TOP_N = 20
ST_SKIP = True


def _today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def _to_symbol(code: str) -> str | None:
    c = str(code).zfill(6)
    if c.startswith(("8", "4", "9")):
        return None
    if c.startswith(("5", "6")):
        return f"sh{c}"
    return f"sz{c}"


def load_universe(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    code_col = "代码" if "代码" in df.columns else "code"
    name_col = "名称" if "名称" in df.columns else "name"
    out = pd.DataFrame(
        {
            "code": df[code_col].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6),
            "name": df[name_col].astype(str),
        }
    ).drop_duplicates("code")
    if ST_SKIP:
        out = out[~out["name"].str.upper().str.contains("ST", na=False)].copy()
    out["symbol"] = out["code"].map(_to_symbol)
    return out.dropna(subset=["symbol"]).reset_index(drop=True)


def _slice(daily: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    return d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(end))].reset_index(
        drop=True
    )


def simulate_with_trades(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    *,
    thr: float,
) -> tuple[np.ndarray, list[float]]:
    n = len(o)
    equity = np.empty(n, dtype=np.float64)
    cash = float(INITIAL_CASH)
    shares = 0.0
    entry_px = 0.0
    buy_i = -1
    tick = TICK_SIZE
    trade_rets: list[float] = []

    for i in range(n):
        oi, hi, li, ci = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        if oi <= 0 or ci <= 0:
            equity[i] = cash + shares * (ci if ci > 0 else 0.0)
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
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    cash += proceeds - fee
                    if entry_px > 0:
                        trade_rets.append(sell_px / entry_px - 1.0)
                    shares = 0.0
                    entry_px = 0.0
                    buy_i = -1
        else:
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
        equity[i] = cash + shares * ci
    return equity, trade_rets


def _trade_stats(trade_rets: list[float]) -> dict[str, float]:
    if not trade_rets:
        return {
            "n_trades": 0,
            "win_rate": np.nan,
            "profit_factor": np.nan,
            "pl_ratio": np.nan,
        }
    arr = np.asarray(trade_rets, float)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    sum_w = float(wins.sum()) if len(wins) else 0.0
    sum_l = float(-losses.sum()) if len(losses) else 0.0
    pf = (sum_w / sum_l) if sum_l > 1e-12 else (99.0 if sum_w > 0 else np.nan)
    aw = float(wins.mean()) if len(wins) else np.nan
    al = float(losses.mean()) if len(losses) else np.nan
    pl = abs(aw / al) if (al == al and al != 0) else np.nan
    return {
        "n_trades": len(arr),
        "win_rate": float(len(wins) / len(arr) * 100.0),
        "profit_factor": float(pf),
        "pl_ratio": pl,
    }


def eval_s1(daily: pd.DataFrame, start: str, end: str, thr: float) -> dict[str, float]:
    sub = _slice(daily, start, end)
    empty = {
        "ret": np.nan,
        "mdd": np.nan,
        "sharpe": np.nan,
        "bh_ret": np.nan,
        "bh_dd": np.nan,
        "excess": np.nan,
        "n_trades": 0,
        "win_rate": np.nan,
        "profit_factor": np.nan,
        "pl_ratio": np.nan,
        "n_bars": 0 if sub is None else len(sub),
    }
    if sub is None or len(sub) < MIN_BARS:
        return empty
    o = sub["open"].to_numpy(float)
    h = sub["high"].to_numpy(float)
    l = sub["low"].to_numpy(float)
    c = sub["close"].to_numpy(float)
    eq, trades = simulate_with_trades(o, h, l, c, thr=thr)
    m = _metrics_from_equity(eq, c)
    ts = _trade_stats(trades)
    return {
        "ret": m["total_return_pct"],
        "mdd": m["max_drawdown_pct"],
        "sharpe": m["sharpe_ratio"],
        "bh_ret": m["bh_return_pct"],
        "bh_dd": m["bh_max_drawdown_pct"],
        "excess": m["excess_return_pct"],
        **ts,
        "n_bars": len(sub),
    }


def eval_s11(daily: pd.DataFrame, start: str, end: str, thr: float, symbol: str, name: str) -> dict:
    sub = _slice(daily, start, end)
    out = {
        "pl_ratio": np.nan,
        "win_rate": np.nan,
        "n_trades": 0,
        "compound_net_pct": np.nan,
        "n_bis": 0,
        "error": "",
    }
    if sub is None or len(sub) < MIN_BARS:
        out["error"] = "bars_short"
        return out
    try:
        # analyze expects date/OHLC; strip tz
        d = sub.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
        r = analyze_bi_pl_ratio(
            d,
            symbol=symbol,
            symbol_name=name,
            entry_pct=thr,
            stop_pct=thr,
            out_dir=None,
        )
        s = r.summary
        wr = s.get("win_rate_net")
        if wr is not None and float(wr) <= 1.0:
            wr = float(wr) * 100.0
        out.update(
            {
                "pl_ratio": s.get("pl_ratio"),
                "win_rate": wr,
                "n_trades": int(s.get("n_trades") or 0),
                "compound_net_pct": s.get("factor1_compound_net_pct"),
                "n_bis": int(s.get("n_bis") or 0),
            }
        )
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def tune_thr(daily: pd.DataFrame) -> tuple[float, dict[str, float]]:
    """定参段择优：优先超额>0，再比盈亏比、夏普。"""
    best_thr = 0.025
    best: dict[str, float] | None = None
    best_key = (-1e18, -1e18, -1e18)

    for thr in THR_GRID:
        m = eval_s1(daily, FIT_START, FIT_END, thr)
        if int(m.get("n_bars") or 0) < MIN_BARS:
            continue
        excess = float(m["excess"]) if m["excess"] == m["excess"] else -1e9
        pl = float(m["pl_ratio"]) if m["pl_ratio"] == m["pl_ratio"] else -1e9
        sh = float(m["sharpe"]) if m["sharpe"] == m["sharpe"] else -1e9
        flag = 1.0 if excess > 0 else 0.0
        key = (flag, pl, excess, sh)
        if key > best_key:
            best_key = key
            best_thr = thr
            best = m
    return best_thr, best or eval_s1(daily, FIT_START, FIT_END, best_thr)


def load_daily(symbol: str) -> pd.DataFrame | None:
    p = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if getattr(df["date"].dt, "tz", None) is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    return df


def run_one(row: dict, oos_end: str, do_s11: bool) -> dict:
    symbol = str(row["symbol"])
    name = str(row["name"])
    code = str(row["code"]).zfill(6)
    out: dict = {
        "code": code,
        "name": name,
        "symbol": symbol,
        "ok": 0,
        "error": "",
        "thr": 0.025,
    }
    daily = load_daily(symbol)
    if daily is None:
        out["error"] = "no_cache"
        return out
    try:
        thr, fit_s1 = tune_thr(daily)
        out["thr"] = thr
        val_s1 = eval_s1(daily, VAL_START, VAL_END, thr)
        oos_s1 = eval_s1(daily, OOS_START, oos_end, thr)
        full_s1 = eval_s1(daily, FULL_START, oos_end, thr)

        for prefix, block in (
            ("fit_s1", fit_s1),
            ("val_s1", val_s1),
            ("oos_s1", oos_s1),
            ("full_s1", full_s1),
        ):
            for k, v in block.items():
                out[f"{prefix}_{k}"] = v

        if do_s11:
            for prefix, start, end in (
                ("fit_s11", FIT_START, FIT_END),
                ("val_s11", VAL_START, VAL_END),
                ("oos_s11", OOS_START, oos_end),
                ("full_s11", FULL_START, oos_end),
            ):
                s11 = eval_s11(daily, start, end, thr, symbol, name)
                for k, v in s11.items():
                    out[f"{prefix}_{k}"] = v

        out["ok"] = 1
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _fmt(v: object, nd: int = 2) -> str:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"
    if x != x or abs(x) > 1e12:
        return "-"
    return f"{x:.{nd}f}"


def build_report(df: pd.DataFrame, top_s1: pd.DataFrame, top_s11: pd.DataFrame, oos_end: str) -> str:
    thr_dist = (
        top_s1["thr"].value_counts().sort_index().to_dict() if "thr" in top_s1.columns else {}
    )
    lines = [
        "# AI应用 · 策略1 / 策略11 三段回测（无因子13过门）",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 股票池：东财 AI应用（剔 ST/北交），有效 {int(df['ok'].sum())}/{len(df)}",
        "- **不做因子13质量带过滤**；定参段只调开盘突破阈值 ±2% / 2.5% / 3%",
        "",
        "## 1. 区间与规则",
        "",
        "| 阶段 | 区间 | 用途 |",
        "|---|---|---|",
        f"| 调参 FIT | {FIT_START} → {FIT_END} | 逐票选 thr，冻结后用于后两段 |",
        f"| 验证 VAL | {VAL_START} → {VAL_END} | 2023–2025 验证窗（至2024末） |",
        f"| 样本外 OOS | {OOS_START} → {oos_end} | 2025 至今 |",
        "",
        "- 策略1：因子1 开盘突破权益；指标=盈亏比 / 超额(相对买入持有) / 最大回撤",
        "- 策略11：同因子1成交 + 日线笔归因盈亏比；超额/回撤沿用策略1权益口径",
        f"- Top20 定参阈值分布：{thr_dist}",
        "",
        "## 2. 策略1 · 样本外超额 Top20",
        "",
        "| 名次 | 代码 | 名称 | thr% | OOS盈亏比 | OOS超额% | OOS回撤% | "
        "VAL盈亏比 | VAL超额% | VAL回撤% | FIT盈亏比 | FIT超额% | FIT回撤% |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(top_s1.itertuples(index=False), 1):
        lines.append(
            f"| {i} | {str(r.code).zfill(6)} | {r.name} | {_fmt(float(r.thr)*100,1)} | "
            f"{_fmt(r.oos_s1_pl_ratio)} | {_fmt(r.oos_s1_excess)} | {_fmt(r.oos_s1_mdd)} | "
            f"{_fmt(r.val_s1_pl_ratio)} | {_fmt(r.val_s1_excess)} | {_fmt(r.val_s1_mdd)} | "
            f"{_fmt(r.fit_s1_pl_ratio)} | {_fmt(r.fit_s1_excess)} | {_fmt(r.fit_s1_mdd)} |"
        )

    lines += [
        "",
        "## 3. 策略11 · 样本外笔归因盈亏比 Top20",
        "",
        "| 名次 | 代码 | 名称 | thr% | OOS盈亏比 | OOS胜率% | OOS复合% | "
        "VAL盈亏比 | FIT盈亏比 | OOS超额%(S1) | OOS回撤%(S1) |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(top_s11.itertuples(index=False), 1):
        lines.append(
            f"| {i} | {str(r.code).zfill(6)} | {r.name} | {_fmt(float(r.thr)*100,1)} | "
            f"{_fmt(r.oos_s11_pl_ratio)} | {_fmt(r.oos_s11_win_rate)} | "
            f"{_fmt(r.oos_s11_compound_net_pct)} | {_fmt(r.val_s11_pl_ratio)} | "
            f"{_fmt(r.fit_s11_pl_ratio)} | {_fmt(r.oos_s1_excess)} | {_fmt(r.oos_s1_mdd)} |"
        )

    # 两策略交集
    s1_codes = set(top_s1["code"].astype(str).str.zfill(6))
    s11_codes = set(top_s11["code"].astype(str).str.zfill(6))
    both = sorted(s1_codes & s11_codes)
    lines += [
        "",
        "## 4. 两榜交集",
        "",
        f"- 策略1 OOS超额 Top20 ∩ 策略11 OOS盈亏比 Top20：**{len(both)}** 只",
        f"- {', '.join(both) if both else '无'}",
        "",
        "## 5. 池内汇总（全有效样本）",
        "",
    ]
    ok = df[df["ok"] == 1]
    if len(ok):
        lines.append(
            "| 策略/段 | 中位盈亏比 | 中位超额% | 中位回撤% | 超额>0占比 |"
        )
        lines.append("|---|---:|---:|---:|---:|")
        for label, pl, ex, dd in (
            ("S1 FIT", "fit_s1_pl_ratio", "fit_s1_excess", "fit_s1_mdd"),
            ("S1 VAL", "val_s1_pl_ratio", "val_s1_excess", "val_s1_mdd"),
            ("S1 OOS", "oos_s1_pl_ratio", "oos_s1_excess", "oos_s1_mdd"),
        ):
            plv = pd.to_numeric(ok[pl], errors="coerce")
            exv = pd.to_numeric(ok[ex], errors="coerce")
            ddv = pd.to_numeric(ok[dd], errors="coerce")
            lines.append(
                f"| {label} | {_fmt(plv.median())} | {_fmt(exv.median())} | "
                f"{_fmt(ddv.median())} | {_fmt((exv > 0).mean()*100,1)}% |"
            )
        if "oos_s11_pl_ratio" in ok.columns:
            for label, pl in (
                ("S11 FIT", "fit_s11_pl_ratio"),
                ("S11 VAL", "val_s11_pl_ratio"),
                ("S11 OOS", "oos_s11_pl_ratio"),
            ):
                plv = pd.to_numeric(ok[pl], errors="coerce")
                lines.append(f"| {label} | {_fmt(plv.median())} | - | - | - |")

    lines += [
        "",
        "## 6. 说明",
        "",
        "- 无因子13过门；排序不做质量带硬过滤。",
        "- 调参仅在 FIT 网格 {2%,2.5%,3%}；VAL/OOS 使用冻结 thr。",
        "- 验证窗与定参在 2023 年重叠（按你的区间要求）。",
        "- 当前概念成分回测历史存在幸存者偏差。",
        "",
        "本报告仅供研究参考，不构成任何投资建议。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    ap.add_argument("--top", type=int, default=TOP_N)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-s11", action="store_true", help="跳过策略11（更快）")
    ap.add_argument("--limit", type=int, default=0, help="调试用：只跑前 N 只")
    args = ap.parse_args()

    oos_end = _today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    univ = load_universe(args.universe)
    if args.limit > 0:
        univ = univ.head(args.limit)
    do_s11 = not args.no_s11
    print(
        f"宇宙 {len(univ)} | FIT {FIT_START}-{FIT_END} | VAL {VAL_START}-{VAL_END} | "
        f"OOS {OOS_START}-{oos_end} | s11={do_s11}"
    )

    rows: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [
            pool.submit(run_one, r._asdict() if hasattr(r, "_asdict") else {
                "code": r.code, "name": r.name, "symbol": r.symbol
            }, oos_end, do_s11)
            for r in univ.itertuples(index=False)
        ]
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            if i % 30 == 0 or i == len(futs):
                ok_n = sum(1 for x in rows if x.get("ok"))
                print(f"  progress {i}/{len(futs)} ok={ok_n} {time.time()-t0:.0f}s")

    df = pd.DataFrame(rows)
    for c in ("code",):
        if c in df.columns:
            df[c] = df[c].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)

    ok = df[df["ok"] == 1].copy()
    # 策略1 Top20：OOS 超额
    s1 = ok[ok["oos_s1_n_trades"].fillna(0) >= MIN_TRADES].copy()
    s1 = s1.sort_values(
        by=["oos_s1_excess", "oos_s1_pl_ratio", "val_s1_excess"],
        ascending=[False, False, False],
        na_position="last",
    )
    top_s1 = s1.head(args.top).reset_index(drop=True)

    if do_s11 and "oos_s11_pl_ratio" in ok.columns:
        s11 = ok[ok["oos_s11_n_trades"].fillna(0) >= MIN_TRADES].copy()
        s11 = s11.sort_values(
            by=["oos_s11_pl_ratio", "oos_s1_excess", "val_s11_pl_ratio"],
            ascending=[False, False, False],
            na_position="last",
        )
        top_s11 = s11.head(args.top).reset_index(drop=True)
    else:
        top_s11 = pd.DataFrame()

    all_csv = OUT_DIR / "all_metrics.csv"
    top_s1_csv = OUT_DIR / "top20_strategy1_oos_excess.csv"
    top_s11_csv = OUT_DIR / "top20_strategy11_oos_pl.csv"
    report_md = OUT_DIR / "report.md"
    meta = OUT_DIR / "run_meta.json"

    df.to_csv(all_csv, index=False, encoding="utf-8-sig")
    top_s1.to_csv(top_s1_csv, index=False, encoding="utf-8-sig")
    if len(top_s11):
        top_s11.to_csv(top_s11_csv, index=False, encoding="utf-8-sig")
    report = build_report(df, top_s1, top_s11 if len(top_s11) else top_s1.iloc[0:0], oos_end)
    report_md.write_text(report, encoding="utf-8")
    meta.write_text(
        json.dumps(
            {
                "fit": [FIT_START, FIT_END],
                "val": [VAL_START, VAL_END],
                "oos": [OOS_START, oos_end],
                "thr_grid": list(THR_GRID),
                "n_ok": int(ok.shape[0]),
                "no_f13_gate": True,
                "s11": do_s11,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(report)
    print(f"\n写入 {report_md}")


if __name__ == "__main__":
    main()
