"""科创综指ETF鹏华(589680) · 因子1 分析 + 参数优化 + 分月等权/超额。

口径：
  · 策略一 · 仅因子1（不开因子2）
  · 强制 T+1（t0=False；ETF 虽可 T0，按用户要求不启用）
  · 印花税 0；tick=0.001
  · 区间：上市日起 → 今；初始资金 10 万
  · 等权/平权持有 = 买入持有收盘价路径；超额 = 策略 − 平权

优化网格（票内择优）：
  · 对称阈值 ±2 / ±2.5 / ±3%
  · 前日过滤：阴/小阳（默认）| 仅阴 | 不限
  · 双阳过滤开/关
  · 非对称买/止损（买2止3、买2.5止3.5、买3止2.5）
  · 隔日止损跳买 / 连亏2次跳买
择优：先要求累计超额>0；再按 5×超额分位 + 3×夏普分位 + 2×回撤改善分位 打分。
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from strategy import BacktestConfig, run_open_break  # noqa: E402
from strategy.backtest import OpenBreak3Strategy, metric, monthly_returns_df  # noqa: E402
from strategy.base import run_backtest_pipeline  # noqa: E402
from strategy.config import _DAILY_CACHE_DIR  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.runner import apply_strategy_config  # noqa: E402

DIR = Path(__file__).resolve().parent
CACHE = _DAILY_CACHE_DIR / "sh589680_daily_qfq.parquet"
NAME = "科创综指ETF鹏华"
CODE = "589680"
SYMBOL = "sh589680"
START = "20250305"  # 上市后首个有行情交易日（成立日 2025-02-26）
CASH = 100_000.0


def base_cfg(**kw: Any) -> BacktestConfig:
    c = BacktestConfig(
        symbol=SYMBOL,
        symbol_name=NAME,
        em_symbol=CODE,
        threshold_pct=0.025,
        start_date=START,
        initial_cash=CASH,
        stamp_tax_rate=0.0,
        tick=0.001,
        t0=False,  # 强制 T+1
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        daily_cache=CACHE,
        report_path=DIR / f"{NAME}_report.html",
    )
    return replace(c, **kw) if kw else c


def _bh_ret(daily: pd.DataFrame) -> float:
    closes = pd.to_numeric(daily["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return float("nan")
    return (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1.0) * 100.0


def _bh_dd(daily: pd.DataFrame) -> float:
    closes = pd.to_numeric(daily["close"], errors="coerce").dropna()
    if closes.empty:
        return float("nan")
    peak = closes.cummax()
    return float(-(closes / peak - 1.0).min() * 100.0)


def _stats(result: Any, daily: pd.DataFrame, label: str) -> dict[str, Any]:
    m = result.metrics_df
    strat = float(metric(m, "total_return_pct"))
    bh = _bh_ret(daily)
    bh_dd = _bh_dd(daily)
    s_dd = float(metric(m, "max_drawdown_pct"))
    return {
        "方案": label,
        "阈值%": None,
        "累计策略%": round(strat, 2),
        "累计平权%": round(bh, 2),
        "累计超额%": round(strat - bh, 2),
        "夏普": round(float(metric(m, "sharpe_ratio")), 3),
        "策略回撤%": round(s_dd, 2),
        "平权回撤%": round(bh_dd, 2) if bh_dd == bh_dd else None,
        "回撤改善%": round(bh_dd - s_dd, 2) if bh_dd == bh_dd else None,
        "胜率%": round(float(metric(m, "win_rate")), 2),
        "闭环": int(metric(m, "closed_trade_count")),
        "利润因子": round(float(metric(m, "profit_factor")), 3),
    }


def _run_f1(cfg: BacktestConfig, label: str) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    r, d = run_open_break(cfg, show_report=False, verbose=False)
    row = _stats(r, d, label)
    row["阈值%"] = round(float(cfg.threshold_pct) * 100.0, 1)
    row["_cfg"] = {
        "threshold_pct": float(cfg.threshold_pct),
        "prev_entry_mode": cfg.prev_entry_mode,
        "ban_double_yang": bool(cfg.ban_double_yang),
        "skip_buy_after_overnight_stop": bool(cfg.skip_buy_after_overnight_stop),
        "skip_buy_after_consec_stops": int(cfg.skip_buy_after_consec_stops),
        "entry_pct": None,
        "stop_pct": None,
        "t0": False,
    }
    return row, r, d


def _run_f1_asym(
    cfg: BacktestConfig,
    *,
    entry: float,
    stop: float,
    label: str,
) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    c = replace(cfg, threshold_pct=entry)

    def configure(strategy: OpenBreak3Strategy, params: Any) -> None:
        apply_strategy_config(strategy, params)
        strategy.entry_pct = entry
        strategy.stop_pct = stop
        strategy.prev_small_yang_pct = entry

    r, d = run_backtest_pipeline(
        params=c,
        strategy_cls=OpenBreak3Strategy,
        configure=configure,
        print_summary_fn=None,
        show_report=False,
        verbose=False,
    )
    row = _stats(r, d, label)
    row["阈值%"] = round(entry * 100.0, 1)
    row["_cfg"] = {
        "threshold_pct": float(entry),
        "prev_entry_mode": c.prev_entry_mode,
        "ban_double_yang": bool(c.ban_double_yang),
        "skip_buy_after_overnight_stop": bool(c.skip_buy_after_overnight_stop),
        "skip_buy_after_consec_stops": int(c.skip_buy_after_consec_stops),
        "entry_pct": float(entry),
        "stop_pct": float(stop),
        "t0": False,
    }
    return row, r, d


def build_jobs(base: BacktestConfig) -> list[tuple[str, Callable[[], tuple]]]:
    jobs: list[tuple[str, Callable[[], tuple]]] = []
    for pct in (0.02, 0.025, 0.03):
        jobs.append(
            (
                f"F1±{pct*100:g}%",
                lambda p=pct: _run_f1(replace(base, threshold_pct=p), f"F1±{p*100:g}%"),
            )
        )
    jobs.append(
        (
            "F1±2.5%仅阴",
            lambda: _run_f1(
                replace(base, threshold_pct=0.025, prev_entry_mode="yin_only"),
                "F1±2.5%仅阴",
            ),
        )
    )
    jobs.append(
        (
            "F1±3%仅阴",
            lambda: _run_f1(
                replace(base, threshold_pct=0.03, prev_entry_mode="yin_only"),
                "F1±3%仅阴",
            ),
        )
    )
    jobs.append(
        (
            "F1±2.5%不限前日",
            lambda: _run_f1(
                replace(base, threshold_pct=0.025, prev_entry_mode="any"),
                "F1±2.5%不限前日",
            ),
        )
    )
    jobs.append(
        (
            "F1±2.5%不禁双阳",
            lambda: _run_f1(
                replace(base, threshold_pct=0.025, ban_double_yang=False),
                "F1±2.5%不禁双阳",
            ),
        )
    )
    jobs.append(
        (
            "F1±2%不禁双阳",
            lambda: _run_f1(
                replace(base, threshold_pct=0.02, ban_double_yang=False),
                "F1±2%不禁双阳",
            ),
        )
    )
    jobs.append(
        (
            "F1隔日止损跳买±2.5%",
            lambda: _run_f1(
                replace(base, skip_buy_after_overnight_stop=True),
                "F1隔日止损跳买±2.5%",
            ),
        )
    )
    jobs.append(
        (
            "F1连亏2次跳买±2.5%",
            lambda: _run_f1(
                replace(base, skip_buy_after_consec_stops=2),
                "F1连亏2次跳买±2.5%",
            ),
        )
    )
    for entry, stop, tag in (
        (0.02, 0.03, "买2/止3"),
        (0.025, 0.035, "买2.5/止3.5"),
        (0.03, 0.025, "买3/止2.5"),
        (0.02, 0.025, "买2/止2.5"),
        (0.03, 0.04, "买3/止4"),
    ):
        jobs.append(
            (
                f"F1{tag}",
                lambda e=entry, s=stop, t=tag: _run_f1_asym(
                    base, entry=e, stop=s, label=f"F1{t}"
                ),
            )
        )
    return jobs


def _rank(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # 只在超额>0 的方案里打分；否则分数置底
    pos = out["累计超额%"] > 0
    for col, higher_better in (
        ("累计超额%", True),
        ("夏普", True),
        ("回撤改善%", True),
    ):
        s = out[col].astype(float)
        if higher_better:
            out[f"_{col}_pct"] = s.rank(pct=True, method="average")
        else:
            out[f"_{col}_pct"] = (-s).rank(pct=True, method="average")
    out["得分"] = (
        5.0 * out["_累计超额%_pct"]
        + 3.0 * out["_夏普_pct"]
        + 2.0 * out["_回撤改善%_pct"]
    )
    out.loc[~pos, "得分"] = out.loc[~pos, "得分"] - 100.0
    out = out.sort_values(["得分", "累计超额%", "夏普"], ascending=False)
    return out


def _prepare_eq_close(result: Any, daily: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eq = result.equity_curve.sort_index()
    if getattr(eq.index, "tz", None) is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq.index = eq.index.normalize()
    eq = eq.groupby(eq.index).last()

    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    else:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai")
    close = px.set_index("date")["close"].astype(float).sort_index()
    close.index = close.index.normalize()
    close = close.resample("D").last().ffill()
    eq = eq.reindex(close.index).ffill()
    return eq, close


def monthly_excess_rows(
    result: Any, daily: pd.DataFrame, *, label: str, initial_cash: float
) -> pd.DataFrame:
    m = monthly_returns_df(result, daily, initial_cash=initial_cash)
    eq, _ = _prepare_eq_close(result, daily)
    rows = []
    for _, r in m.iterrows():
        month = str(r["月份"])
        period = pd.Period(month, freq="M")
        eq_m = eq[eq.index.to_period("M") == period]
        mdd = float("nan")
        if not eq_m.empty:
            peak = eq_m.cummax()
            mdd = float((eq_m / peak - 1.0).min() * 100.0)
        strat = float(r["策略收益%"])
        bh = float(r["持有收益%"])
        rows.append(
            {
                "月份": month,
                "标的": label,
                "策略%": round(strat, 2),
                "平权持有%": round(bh, 2),
                "超额%": round(strat - bh, 2),
                "月末权益": round(float(eq_m.iloc[-1]), 2) if not eq_m.empty else None,
                "月内回撤%": round(mdd, 2) if mdd == mdd else None,
            }
        )
    return pd.DataFrame(rows)


def yearly_rows(
    result: Any, daily: pd.DataFrame, *, label: str, initial_cash: float
) -> pd.DataFrame:
    eq, close = _prepare_eq_close(result, daily)
    years = sorted(set(eq.index.year) | set(close.index.year))
    rows = []
    for y in years:
        eq_y = eq[eq.index.year == y]
        px_y = close[close.index.year == y]
        if eq_y.empty:
            continue
        prev_eq = eq[eq.index.year < y]
        base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else initial_cash
        strat = (float(eq_y.iloc[-1]) / base_eq - 1.0) * 100.0
        prev_px = close[close.index.year < y]
        base_px = float(prev_px.iloc[-1]) if not prev_px.empty else float(px_y.iloc[0])
        bh = (float(px_y.iloc[-1]) / base_px - 1.0) * 100.0
        peak = eq_y.cummax()
        mdd = float((eq_y / peak - 1.0).min() * 100.0)
        closed = 0
        td = getattr(result, "trades_df", None)
        if td is not None and not td.empty:
            col = next(
                (
                    c
                    for c in ("exit_time", "close_time", "end_time", "timestamp")
                    if c in td.columns
                ),
                None,
            )
            if col:
                cts = pd.to_datetime(td[col])
                if getattr(cts.dt, "tz", None) is not None:
                    cts = cts.dt.tz_convert("Asia/Shanghai")
                closed = int((cts.dt.year == y).sum())
        rows.append(
            {
                "年份": int(y),
                "标的": label,
                "策略%": round(strat, 2),
                "平权持有%": round(bh, 2),
                "超额%": round(strat - bh, 2),
                "年内回撤%": round(mdd, 2),
                "闭环笔数": closed,
            }
        )
    return pd.DataFrame(rows)


def rolling12m(eq: pd.Series, close: pd.Series, *, label: str) -> pd.DataFrame:
    df = pd.DataFrame({"eq": eq, "close": close}).dropna()
    # 上市不足一年：用可用长度滚动，但至少 60 交易日
    win = min(252, max(60, len(df) // 2))
    if len(df) <= win:
        return pd.DataFrame()
    rows = []
    for i in range(win, len(df)):
        sl = df.iloc[i - win : i + 1]
        s_ret = (sl["eq"].iloc[-1] / sl["eq"].iloc[0] - 1.0) * 100.0
        h_ret = (sl["close"].iloc[-1] / sl["close"].iloc[0] - 1.0) * 100.0
        rows.append(
            {
                "日期": sl.index[-1].strftime("%Y-%m-%d"),
                "窗口交易日": win,
                "滚动策略%": round(s_ret, 2),
                "滚动持有%": round(h_ret, 2),
                "滚动超额%": round(s_ret - h_ret, 2),
                "标的": label,
            }
        )
    return pd.DataFrame(rows)


def _norm_from_monthly(m: pd.DataFrame) -> tuple[list[str], list[float], list[float]]:
    eq, bh = CASH, CASH
    dates, s, h = [], [], []
    for _, r in m.sort_values("月份").iterrows():
        eq *= 1 + float(r["策略%"]) / 100
        bh *= 1 + float(r["平权持有%"]) / 100
        dates.append(str(r["月份"]))
        s.append(round(eq, 2))
        h.append(round(bh, 2))
    return dates, s, h


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    base = base_cfg()

    # 预热日线缓存，避免扫参时重复打东财
    daily0 = fetch_daily(
        SYMBOL,
        START,
        base.end_date,
        cache_path=CACHE,
        force_refresh=False,
    )
    print(
        f"日线: {len(daily0)} 根 · "
        f"{pd.to_datetime(daily0['date']).min().date()} → "
        f"{pd.to_datetime(daily0['date']).max().date()}"
    )

    print(f"=== {NAME}({CODE}) 因子1 参数扫描 · T+1 ===")
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, tuple[Any, pd.DataFrame]] = {}
    for name, fn in build_jobs(base):
        print(f"  running {name} ...", flush=True)
        row, r, d = fn()
        artifacts[name] = (r, d)
        rows.append({k: v for k, v in row.items() if k != "_cfg"})
        # keep cfg on side
        rows[-1]["_cfg_json"] = json.dumps(row["_cfg"], ensure_ascii=False)

    sweep = pd.DataFrame(rows)
    ranked = _rank(sweep)
    ranked.to_csv(DIR / "param_sweep.csv", index=False, encoding="utf-8-sig")

    best = ranked.iloc[0]
    best_name = str(best["方案"])
    best_cfg = json.loads(str(best["_cfg_json"]))
    print(f"\n最优方案: {best_name}")
    print(best[[c for c in ranked.columns if not c.startswith("_")]].to_string())

    # 用最优方案再跑一次（确保报告路径）并产出分月
    # 从 artifacts 取
    result, daily = artifacts[best_name]

    # 若最优是非对称，artifacts 已有结果
    monthly = monthly_excess_rows(result, daily, label=NAME, initial_cash=CASH)
    yearly = yearly_rows(result, daily, label=NAME, initial_cash=CASH)
    eq, close = _prepare_eq_close(result, daily)
    rolling = rolling12m(eq, close, label=NAME)

    monthly.to_csv(DIR / "monthly_excess.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(DIR / "yearly_decay.csv", index=False, encoding="utf-8-sig")
    if not rolling.empty:
        rolling.to_csv(DIR / "rolling_excess.csv", index=False, encoding="utf-8-sig")

    win = float((monthly["超额%"] > 0).mean() * 100.0) if len(monthly) else 0.0
    yr_ex = {int(r["年份"]): float(r["超额%"]) for _, r in yearly.iterrows()}
    roll_last = float(rolling["滚动超额%"].iloc[-1]) if len(rolling) else None
    d0 = str(pd.to_datetime(daily["date"]).min().date())
    d1 = str(pd.to_datetime(daily["date"]).max().date())

    summary = {
        "标的": NAME,
        "代码": CODE,
        "区间": f"{d0} → {d1}",
        "口径": f"策略一·仅因子1；T+1；最优={best_name}；平权=买入持有",
        "最优方案": best_name,
        "最优参数": best_cfg,
        "累计策略%": float(best["累计策略%"]),
        "累计平权%": float(best["累计平权%"]),
        "累计超额%": float(best["累计超额%"]),
        "夏普": float(best["夏普"]),
        "策略回撤%": float(best["策略回撤%"]),
        "超额月胜率%": round(win, 1),
        "月均超额%": round(float(monthly["超额%"].mean()), 2) if len(monthly) else 0.0,
        "年超额": {str(k): v for k, v in yr_ex.items()},
        "滚动最新超额%": roll_last,
        "闭环": int(best["闭环"]),
        "扫描方案数": int(len(ranked)),
        "有超额方案数": int((ranked["累计超额%"] > 0).sum()),
    }
    (DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # top10 for report
    top = ranked.head(10).drop(columns=[c for c in ranked.columns if c.startswith("_")])
    top.to_csv(DIR / "param_top10.csv", index=False, encoding="utf-8-sig")

    # canvas payload
    eq_dates, eq_s, eq_h = _norm_from_monthly(monthly)
    payload = {
        "meta": summary,
        "equity_cats": eq_dates,
        "equity_strat": eq_s,
        "equity_bh": eq_h,
        "month_cats": monthly["月份"].astype(str).tolist(),
        "month_strat": monthly["策略%"].astype(float).tolist(),
        "month_bh": monthly["平权持有%"].astype(float).tolist(),
        "month_excess": monthly["超额%"].astype(float).tolist(),
        "year_rows": yearly.to_dict(orient="records"),
        "recent_rows": monthly.tail(12).to_dict(orient="records"),
        "top_params": top.to_dict(orient="records"),
        "roll_cats": rolling["日期"].tolist() if len(rolling) else [],
        "roll_excess": rolling["滚动超额%"].astype(float).tolist() if len(rolling) else [],
    }
    (DIR / "_canvas_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n分月行数: {len(monthly)}")
    print(monthly.to_string(index=False))
    print(f"\n产出目录: {DIR}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
