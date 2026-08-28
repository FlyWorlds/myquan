"""AI应用概念池 · 策略1因子1 三段回测 + 因子13盈亏比 Top20 报告。

区间（半开边界，避免串段偷看）：
  · 定参 FIT : 2020-01-01 → 2023-12-31
  · 验证 VAL : 2024-01-01 → 2024-12-31
  · 样本外 OOS: 2025-01-01 → 今

流程：
  1) 东财「AI应用」成分（缺省读 /tmp/东财_AI应用.csv，可 --universe）
  2) 策略一·因子1（开盘±2.5%、阴/小阳、仅止损、T+1）逐票回测三段
  3) 用定参段指标按因子13质量带打分；整段(2020→今)算盈亏比
  4) 输出盈亏比前 20 名 Markdown 报告

  cd backtest && python ai_concept_f1_f13_report.py
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

from backtest.factor1_monthly_top3 import (  # noqa: E402
    _metrics_from_equity,
)
from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.factor13_fit import (  # noqa: E402
    enrich_cross_section_scores,
    load_best_rule,
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

OUT_DIR = _MYQUAN / "backtest" / "ai_concept_f1_f13"
CACHE_DIR = _MYQUAN / "data_cache" / "ai_concept"
DEFAULT_UNIVERSE = Path("/tmp/东财_AI应用.csv")

# 定参用满 2020–2023；验证 2023–2024（与定参在 2023 年重叠，报告中注明）；
# 样本外自 2025 起。
FIT_START, FIT_END = "20200101", "20231231"
VAL_START, VAL_END = "20230101", "20241231"
OOS_START = "20250101"
FULL_START = "20200101"

THR = 0.025
INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT = 100
MIN_BARS = 60
TOP_N = 20
FETCH_WORKERS = 10
ST_SKIP = True  # 跳过名称含 ST 的票


def _today_ymd() -> str:
    return dt.date.today().strftime("%Y%m%d")


def _to_symbol(code: str) -> str | None:
    c = str(code).zfill(6)
    if c.startswith(("8", "4", "9")):  # 北交所等，AkShare sh/sz 日线不覆盖
        return None
    if c.startswith(("5", "6")):
        return f"sh{c}"
    return f"sz{c}"


def _is_mainboard(code: str) -> bool:
    c = str(code).zfill(6)
    return not (
        c.startswith(("688", "689", "300", "301", "8", "4", "9"))
    )


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
    out = out.dropna(subset=["symbol"]).reset_index(drop=True)
    out["mainboard"] = out["code"].map(_is_mainboard).astype(int)
    return out


def simulate_with_trades(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    *,
    thr: float = THR,
    initial_cash: float = INITIAL_CASH,
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """开盘突破轻量模拟；返回权益、持仓标记、每笔闭环收益率(小数)。"""
    n = len(o)
    equity = np.empty(n, dtype=np.float64)
    holding_arr = np.zeros(n, dtype=np.int8)
    cash = float(initial_cash)
    shares = 0.0
    entry_px = 0.0
    buy_i = -1
    tick = TICK_SIZE
    trade_rets: list[float] = []

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
                    sell_px = float(
                        lim["limit_px"] if bool(lim["opened"]) else stop_px
                    )
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
        holding_arr[i] = 1 if shares > 0 else 0

    return equity, holding_arr, trade_rets


def _trade_stats(trade_rets: list[float]) -> dict[str, float]:
    if not trade_rets:
        return {
            "n_trades": 0,
            "win_rate": np.nan,
            "profit_factor": np.nan,
            "avg_win": np.nan,
            "avg_loss": np.nan,
            "pl_ratio": np.nan,
        }
    arr = np.asarray(trade_rets, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    n = len(arr)
    win_rate = float(len(wins) / n * 100.0)
    sum_w = float(wins.sum()) if len(wins) else 0.0
    sum_l = float(-losses.sum()) if len(losses) else 0.0
    pf = (sum_w / sum_l) if sum_l > 1e-12 else (np.inf if sum_w > 0 else np.nan)
    aw = float(wins.mean()) if len(wins) else np.nan
    al = float(losses.mean()) if len(losses) else np.nan
    pl = abs(aw / al) if (al == al and al != 0) else np.nan
    return {
        "n_trades": n,
        "win_rate": win_rate,
        "profit_factor": float(pf) if pf != np.inf else 99.0,
        "avg_win": aw * 100.0 if aw == aw else np.nan,
        "avg_loss": al * 100.0 if al == al else np.nan,
        "pl_ratio": pl,
    }


def _slice_daily(daily: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    return d[(d["date"] >= s) & (d["date"] <= e)].reset_index(drop=True)


def eval_window(daily: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    sub = _slice_daily(daily, start, end)
    empty = {
        "ret": np.nan,
        "mdd": np.nan,
        "sharpe": np.nan,
        "bh_ret": np.nan,
        "bh_dd": np.nan,
        "excess": np.nan,
        "dd_improve": np.nan,
        "n_trades": 0,
        "win_rate": np.nan,
        "profit_factor": np.nan,
        "avg_win": np.nan,
        "avg_loss": np.nan,
        "pl_ratio": np.nan,
        "n_bars": 0 if sub is None else len(sub),
    }
    if sub is None or len(sub) < MIN_BARS:
        return empty
    o = sub["open"].to_numpy(float)
    h = sub["high"].to_numpy(float)
    l = sub["low"].to_numpy(float)
    c = sub["close"].to_numpy(float)
    eq, _, trades = simulate_with_trades(o, h, l, c, thr=THR)
    m = _metrics_from_equity(eq, c)
    ts = _trade_stats(trades)
    return {
        "ret": m["total_return_pct"],
        "mdd": m["max_drawdown_pct"],
        "sharpe": m["sharpe_ratio"],
        "bh_ret": m["bh_return_pct"],
        "bh_dd": m["bh_max_drawdown_pct"],
        "excess": m["excess_return_pct"],
        "dd_improve": m["dd_improve_pct"],
        **ts,
        "n_bars": len(sub),
    }


def fetch_one(symbol: str, end: str, *, cache_only: bool = False) -> tuple[str, pd.DataFrame | None, str]:
    cache = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    if cache_only or cache.exists():
        try:
            if cache.exists():
                df = pd.read_parquet(cache)
                if df is not None and not df.empty:
                    df = df.copy()
                    df["date"] = pd.to_datetime(df["date"])
                    if df["date"].dt.tz is not None:
                        df["date"] = df["date"].dt.tz_localize(None)
                    return symbol, df, "ok"
            if cache_only:
                return symbol, None, "no_cache"
        except Exception as e:  # noqa: BLE001
            if cache_only:
                return symbol, None, f"cache_err:{e}"
    try:
        df = fetch_daily(symbol, FULL_START, end, cache_path=cache)
        if df is None or df.empty:
            return symbol, None, "empty"
        return symbol, df, "ok"
    except Exception as e:  # noqa: BLE001
        return symbol, None, f"{type(e).__name__}: {e}"


def run_symbol(row: dict, daily: pd.DataFrame, oos_end: str) -> dict:
    out = {
        "code": row["code"],
        "name": row["name"],
        "symbol": row["symbol"],
        "mainboard": int(row["mainboard"]),
        "ok": 1,
        "error": "",
    }
    try:
        fit = eval_window(daily, FIT_START, FIT_END)
        val = eval_window(daily, VAL_START, VAL_END)
        oos = eval_window(daily, OOS_START, oos_end)
        full = eval_window(daily, FULL_START, oos_end)
        for prefix, block in (("fit", fit), ("val", val), ("oos", oos), ("full", full)):
            for k, v in block.items():
                out[f"{prefix}_{k}"] = v
        out["dd_ratio"] = (
            out["fit_mdd"] / out["fit_bh_dd"]
            if out.get("fit_bh_dd") and out["fit_bh_dd"] > 0
            else np.nan
        )
    except Exception as e:  # noqa: BLE001
        out["ok"] = 0
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _fmt(v: object, nd: int = 2) -> str:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"
    if x != x or abs(x) > 1e8:
        return "-"
    return f"{x:.{nd}f}"


def build_report(df: pd.DataFrame, top: pd.DataFrame, rule: dict, oos_end: str) -> str:
    lines = [
        f"# AI应用概念 · 策略1因子1 + 因子13盈亏比 Top{TOP_N}",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 股票池：东财「AI应用」概念（剔除 ST / 北交所），有效回测 {int(df['ok'].sum())}/{len(df)} 只",
        f"- 策略：策略一 · 因子1（开盘 ±{THR*100:.1f}% 突破，阴/小阳可买，仅止损，T+1）",
        "- 选股层：因子13 质量带（定参段打分；排序结合整段盈亏比）",
        "",
        "## 1. 区间口径",
        "",
        "| 阶段 | 区间 | 用途 |",
        "|---|---|---|",
        f"| 定参 FIT | {FIT_START} → {FIT_END} | 因子13 质量打分 / 过滤 |",
        f"| 验证 VAL | {VAL_START} → {VAL_END} | 2023–2025 验证窗（至2024末；与定参在2023重叠） |",
        f"| 样本外 OOS | {OOS_START} → {oos_end} | 2025 至今 |",
        f"| 整段 FULL | {FULL_START} → {oos_end} | **盈亏比主排序** |",
        "",
        "## 2. 因子13 规则摘要",
        "",
        "```",
        f"signal={rule.get('signal')} top_k={rule.get('top_k')}",
        f"夏普带 [{rule.get('min_sharpe')}, {rule.get('max_sharpe')}]  "
        f"回撤带 [{rule.get('mdd_lo')}%, {rule.get('mdd_hi')}%]  "
        f"dd_ratio≤{rule.get('dd_ratio_max')}",
        "本报告在 AI 池内关闭 mainboard_only，保留科创/创业板。",
        "```",
        "",
        "## 3. 整段盈亏比 Top20（主表）",
        "",
        "| 名次 | 代码 | 名称 | 盈亏比 | 利润因子 | 胜率% | 闭环 | F13通过 | "
        "定参夏普 | 定参超额% | 验证收益% | OOS收益% | 整段收益% | 整段回撤% |",
        "|---:|---|---|---:|---:|---:|---:|:---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(top.itertuples(index=False), 1):
        f13 = "是" if int(getattr(r, "f13_pass", 0) or 0) == 1 else "否"
        lines.append(
            f"| {i} | {r.code} | {r.name} | {_fmt(r.full_pl_ratio)} | "
            f"{_fmt(r.full_profit_factor, 3)} | {_fmt(r.full_win_rate)} | "
            f"{int(r.full_n_trades or 0)} | {f13} | {_fmt(r.fit_sharpe, 3)} | "
            f"{_fmt(r.fit_excess)} | {_fmt(r.val_ret)} | {_fmt(r.oos_ret)} | "
            f"{_fmt(r.full_ret)} | {_fmt(r.full_mdd)} |"
        )

    lines += [
        "",
        "## 4. 定参段因子13质量分对照",
        "",
        "| 名次 | 代码 | 名称 | score_quality | 定参夏普 | 定参回撤% | dd_ratio | 定参盈亏比 |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(top.itertuples(index=False), 1):
        sq = getattr(r, "score_quality", np.nan)
        lines.append(
            f"| {i} | {r.code} | {r.name} | {_fmt(sq, 3)} | {_fmt(r.fit_sharpe, 3)} | "
            f"{_fmt(r.fit_mdd)} | {_fmt(getattr(r, 'dd_ratio', np.nan), 3)} | "
            f"{_fmt(r.fit_pl_ratio)} |"
        )

    n_pass = int((df["f13_pass"] == 1).sum()) if "f13_pass" in df.columns else 0
    lines += [
        "",
        "## 5. 读数提示",
        "",
        "- Top20：**因子13质量带通过优先**，组内按整段盈亏比降序；不足20用 score_quality 候选补齐后再按盈亏比排。",
        f"- 因子13 质量带硬过滤通过：{n_pass} 只（定参段夏普/回撤/dd_ratio）；主表「F13通过」列标注。",
        "- 盈亏比 = 平均盈利% / |平均亏损%|；利润因子 = 盈利总额 / |亏损总额|。",
        "- 「整日」= 日线开盘突破规则（非整段分钟线）；验证/OOS 为同规则窗口累计收益，非组合再平衡。",
        "- 概念成分随时间变化；本报告用当前成分回测历史，存在幸存者偏差。",
        "",
        "本报告基于历史回测与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI概念 策略1因子1 + 因子13 盈亏比报告")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--top", type=int, default=TOP_N)
    parser.add_argument("--workers", type=int, default=FETCH_WORKERS)
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="只读本地 data_cache/ai_concept，不联网补行情",
    )
    args = parser.parse_args()

    oos_end = _today_ymd()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not args.universe.exists():
        raise SystemExit(f"股票池文件不存在: {args.universe}")

    univ = load_universe(args.universe)
    print(
        f"宇宙 {len(univ)} 只 | FIT {FIT_START}-{FIT_END} | "
        f"VAL {VAL_START}-{VAL_END} | OOS {OOS_START}-{oos_end} | "
        f"cache_only={args.cache_only}"
    )

    # 拉行情
    daily_map: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(fetch_one, str(r.symbol), oos_end, cache_only=args.cache_only): str(r.symbol)
            for r in univ.itertuples(index=False)
        }
        done = 0
        for fut in as_completed(futs):
            sym, df, st = fut.result()
            done += 1
            if st == "ok" and df is not None:
                daily_map[sym] = df
            else:
                errors[sym] = st
            if done % 40 == 0 or done == len(futs):
                print(f"  行情 {done}/{len(futs)} · 成功 {len(daily_map)} · {time.time()-t0:.0f}s")

    rows: list[dict] = []
    for r in univ.itertuples(index=False):
        row = r._asdict() if hasattr(r, "_asdict") else {
            "code": r.code, "name": r.name, "symbol": r.symbol, "mainboard": r.mainboard
        }
        daily = daily_map.get(str(row["symbol"]))
        if daily is None:
            rows.append(
                {
                    **row,
                    "ok": 0,
                    "error": errors.get(str(row["symbol"]), "no_daily"),
                }
            )
            continue
        rows.append(run_symbol(row, daily, oos_end))

    df = pd.DataFrame(rows)
    ok = df[df["ok"] == 1].copy()
    print(f"回测完成 ok={len(ok)} fail={len(df)-len(ok)}")

    # 因子13 定参截面打分
    rule = load_best_rule()
    rule = {**rule, "mainboard_only": False}  # AI 池含创业/科创
    scored = ok.rename(
        columns={
            "fit_ret": "ret",
            "fit_mdd": "mdd",
            "fit_sharpe": "sharpe",
            "fit_bh_ret": "bh_ret",
            "fit_bh_dd": "bh_dd",
            "fit_excess": "excess",
            "fit_dd_improve": "dd_improve",
        }
    )
    scored = enrich_cross_section_scores(scored)
    # 质量带硬过滤（放宽补齐：优先严带，不足再放宽）
    bands = rule.get("fill_bands") or [
        {
            "min_sharpe": rule.get("min_sharpe"),
            "max_sharpe": rule.get("max_sharpe"),
            "mdd_lo": rule.get("mdd_lo"),
            "mdd_hi": rule.get("mdd_hi"),
            "dd_ratio_max": rule.get("dd_ratio_max"),
        }
    ]
    pass_mask = pd.Series(False, index=scored.index)
    for band in bands:
        m = pd.Series(True, index=scored.index)
        if band.get("min_sharpe") is not None:
            m &= scored["sharpe"] >= float(band["min_sharpe"])
        if band.get("max_sharpe") is not None:
            m &= scored["sharpe"] <= float(band["max_sharpe"])
        if band.get("mdd_lo") is not None:
            m &= scored["mdd"] >= float(band["mdd_lo"])
        if band.get("mdd_hi") is not None:
            m &= scored["mdd"] <= float(band["mdd_hi"])
        if band.get("dd_ratio_max") is not None:
            m &= (scored["dd_ratio"] <= float(band["dd_ratio_max"])) & (scored["bh_dd"] > 5)
        if int(m.sum()) >= int(rule.get("top_k", 10)):
            pass_mask = m
            break
        pass_mask = pass_mask | m

    scored["f13_pass"] = pass_mask.astype(int)
    # 合并回 ok 列名
    merge_cols = ["symbol", "score_quality", "score_fit", "score_esd", "f13_pass", "dd_ratio"]
    ok = ok.drop(columns=[c for c in ("score_quality", "f13_pass", "dd_ratio") if c in ok.columns], errors="ignore")
    ok = ok.merge(scored[merge_cols], on="symbol", how="left")

    # Top20：先取定参段 score_quality 前列（因子13排序池），再按整段盈亏比取前 N
    ranked = ok.copy()
    ranked["full_pl_ratio"] = pd.to_numeric(ranked["full_pl_ratio"], errors="coerce")
    ranked["score_quality"] = pd.to_numeric(ranked["score_quality"], errors="coerce")
    ranked = ranked[ranked["full_n_trades"].fillna(0) >= 5]
    ranked = ranked[ranked["fit_n_bars"].fillna(0) >= MIN_BARS]
    # 因子13 候选池：质量带通过优先；不足则用 score_quality 前 40 补齐
    pool = ranked[ranked["f13_pass"] == 1].copy()
    if len(pool) < int(args.top):
        extra = ranked[ranked["f13_pass"] != 1].sort_values(
            "score_quality", ascending=False, na_position="last"
        )
        need = max(40, int(args.top)) - len(pool)
        pool = pd.concat([pool, extra.head(need)], ignore_index=True)
    pool = pool.sort_values(
        by=["f13_pass", "full_pl_ratio", "full_profit_factor", "score_quality"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    top = pool.head(int(args.top)).reset_index(drop=True)

    # 落盘
    all_csv = OUT_DIR / "all_metrics.csv"
    top_csv = OUT_DIR / f"top{args.top}_pl_ratio.csv"
    report_md = OUT_DIR / f"report_top{args.top}.md"
    meta_json = OUT_DIR / "run_meta.json"

    df_out = df.merge(
        ok[["symbol", "score_quality", "score_fit", "f13_pass", "dd_ratio"]],
        on="symbol",
        how="left",
        suffixes=("", "_y"),
    )
    # clean duplicate dd_ratio
    if "dd_ratio_y" in df_out.columns:
        df_out["dd_ratio"] = df_out["dd_ratio_y"].combine_first(df_out.get("dd_ratio"))
        df_out = df_out.drop(columns=["dd_ratio_y"])

    df_out.to_csv(all_csv, index=False, encoding="utf-8-sig")
    for frame in (df_out, top):
        if "code" in frame.columns:
            frame["code"] = frame["code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    top.to_csv(top_csv, index=False, encoding="utf-8-sig")
    df_out.to_csv(all_csv, index=False, encoding="utf-8-sig")
    report = build_report(df_out, top, rule, oos_end)
    report_md.write_text(report, encoding="utf-8")
    meta_json.write_text(
        json.dumps(
            {
                "universe": str(args.universe),
                "n_universe": len(univ),
                "n_ok": int(ok.shape[0]),
                "fit": [FIT_START, FIT_END],
                "val": [VAL_START, VAL_END],
                "oos": [OOS_START, oos_end],
                "thr": THR,
                "top_n": int(args.top),
                "rule": rule,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(report)
    print(f"\n已写入:\n  {report_md}\n  {top_csv}\n  {all_csv}")


if __name__ == "__main__":
    main()
