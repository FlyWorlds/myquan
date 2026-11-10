"""科创综指ETF(589680) · 策略一(因子1+因子2) 前视切割选参。

选参窗口（阈值必须在 2026 年前生成）:
  2025-03-05 → 2025-12-31

冻结参数后全期回测:
  2025-03-05 → 今

口径:
  · 因子1：开盘突破买入 / 开盘止损；强制 T+1；ETF 印花税 0；tick=0.001
  · 因子2：仅用选参窗权益曲线标定加减仓预警阈值（回测不注资、不改权益）
  · 平权持有 = 买入持有收盘价路径

研究用途，不构成投资建议。
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

from strategy.backtest import OpenBreak3Strategy, metric, monthly_returns_df  # noqa: E402
from strategy.base import run_backtest_pipeline  # noqa: E402
from strategy.config import BacktestConfig, _DAILY_CACHE_DIR  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.dd_alert import derive_thresholds, evaluate_alert  # noqa: E402
from strategy.runner import apply_strategy_config, run_open_break  # noqa: E402
from strategy.strategies.strategy1 import run_strategy1  # noqa: E402

DIR = Path(__file__).resolve().parent
CACHE = _DAILY_CACHE_DIR / "sh589680_daily_qfq.parquet"
NAME = "科创综指ETF鹏华"
CODE = "589680"
SYMBOL = "sh589680"
START = "20250305"
SELECT_END = "20251231"  # 阈值截止：不含 2026
CASH = 100_000.0


def base_cfg(**kw: Any) -> BacktestConfig:
    c = BacktestConfig(
        symbol=SYMBOL,
        symbol_name=NAME,
        em_symbol=CODE,
        threshold_pct=0.025,
        start_date=START,
        end_date=kw.pop("end_date", SELECT_END) if "end_date" in kw else SELECT_END,
        initial_cash=CASH,
        stamp_tax_rate=0.0,
        tick=0.001,
        t0=False,
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


def _cfg_side(
    cfg: BacktestConfig,
    *,
    entry: float | None = None,
    stop: float | None = None,
) -> dict[str, Any]:
    e = float(entry) if entry is not None else float(cfg.resolved_entry_pct())
    s = float(stop) if stop is not None else float(cfg.resolved_stop_pct())
    return {
        "threshold_pct": float(cfg.threshold_pct),
        "prev_entry_mode": cfg.prev_entry_mode,
        "ban_double_yang": bool(cfg.ban_double_yang),
        "skip_buy_after_overnight_stop": bool(cfg.skip_buy_after_overnight_stop),
        "skip_buy_after_consec_stops": int(cfg.skip_buy_after_consec_stops),
        "entry_pct": e,
        "stop_pct": s,
        "t0": False,
    }


def _run_f1(cfg: BacktestConfig, label: str) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    r, d = run_open_break(cfg, show_report=False, verbose=False)
    row = _stats(r, d, label)
    row["阈值%"] = round(float(cfg.resolved_entry_pct()) * 100.0, 1)
    row["_cfg"] = _cfg_side(cfg)
    return row, r, d


def _run_f1_asym(
    cfg: BacktestConfig,
    *,
    entry: float,
    stop: float,
    label: str,
) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    c = replace(cfg, threshold_pct=entry, entry_pct=entry, stop_pct=stop)

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
    row["_cfg"] = _cfg_side(c, entry=entry, stop=stop)
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
    pos = out["累计超额%"] > 0
    for col in ("累计超额%", "夏普", "回撤改善%"):
        s = out[col].astype(float)
        out[f"_{col}_pct"] = s.rank(pct=True, method="average")
    out["得分"] = (
        5.0 * out["_累计超额%_pct"]
        + 3.0 * out["_夏普_pct"]
        + 2.0 * out["_回撤改善%_pct"]
    )
    out.loc[~pos, "得分"] = out.loc[~pos, "得分"] - 100.0
    return out.sort_values(["得分", "累计超额%", "夏普"], ascending=False)


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


def holdings_table(result: Any, daily: pd.DataFrame) -> pd.DataFrame:
    """从成交重建持仓区间与浮动盈亏。"""
    exec_df = getattr(result, "executions_df", None)
    if exec_df is None or getattr(exec_df, "empty", True):
        return pd.DataFrame()

    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    else:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai")
    close = px.set_index("date")["close"].astype(float).sort_index()
    last_close = float(close.iloc[-1]) if len(close) else float("nan")
    last_day = close.index[-1] if len(close) else None

    df = exec_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if getattr(df["timestamp"].dt, "tz", None) is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Shanghai")
    df = df.sort_values("timestamp")
    side = df["side"].astype(str).str.lower()

    rows: list[dict[str, Any]] = []
    open_lot: dict[str, Any] | None = None
    for _, ex in df.iterrows():
        s = str(ex["side"]).lower()
        ts = ex["timestamp"]
        price = float(ex.get("price") or ex.get("avg_price") or 0)
        qty = float(ex.get("quantity") or ex.get("qty") or 0)
        if s == "buy":
            if open_lot is not None:
                # 加仓合并（策略一通常一次打满）
                prev_q = float(open_lot["数量"])
                prev_p = float(open_lot["买入价"])
                new_q = prev_q + qty
                open_lot["买入价"] = (
                    (prev_p * prev_q + price * qty) / new_q if new_q else price
                )
                open_lot["数量"] = new_q
            else:
                open_lot = {
                    "序号": len(rows) + 1,
                    "买入日": ts.strftime("%Y-%m-%d"),
                    "买入价": round(price, 4),
                    "数量": qty,
                    "卖出日": None,
                    "卖出价": None,
                    "持有交易日": None,
                    "收益%": None,
                    "状态": "持有中",
                }
        elif s == "sell" and open_lot is not None:
            entry = pd.Timestamp(open_lot["买入日"]).tz_localize("Asia/Shanghai")
            mask = (close.index >= entry.normalize()) & (close.index <= ts.normalize())
            hold_days = int(mask.sum())
            ret = (price / float(open_lot["买入价"]) - 1.0) * 100.0
            open_lot.update(
                {
                    "卖出日": ts.strftime("%Y-%m-%d"),
                    "卖出价": round(price, 4),
                    "持有交易日": hold_days,
                    "收益%": round(ret, 2),
                    "状态": "已平仓",
                    "数量": float(open_lot["数量"]),
                }
            )
            rows.append(open_lot)
            open_lot = None

    if open_lot is not None and last_day is not None:
        entry = pd.Timestamp(open_lot["买入日"]).tz_localize("Asia/Shanghai")
        mask = (close.index >= entry.normalize()) & (close.index <= last_day.normalize())
        hold_days = max(1, int(mask.sum()))
        ret = (last_close / float(open_lot["买入价"]) - 1.0) * 100.0
        open_lot.update(
            {
                "卖出日": "",
                "卖出价": round(last_close, 4),
                "持有交易日": hold_days,
                "收益%": round(ret, 2),
                "状态": "持有中",
            }
        )
        rows.append(open_lot)

    out = pd.DataFrame(rows)
    if not out.empty:
        out["数量"] = out["数量"].astype(int)
    return out


def factor2_alert_path(eq: pd.Series, th: Any) -> pd.DataFrame:
    """按冻结因子2阈值扫描权益路径；只记录动作切换日（不改仓）。"""
    eq = eq.dropna().sort_index()
    if eq.empty:
        return pd.DataFrame()
    peak = float(eq.iloc[0])
    in_add = False
    prev_action = ""
    rows = []
    for ts, val in eq.items():
        v = float(val)
        peak = max(peak, v)
        sig = evaluate_alert(equity=v, peak=peak, thresholds=th, in_add_zone=in_add)
        action = str(sig.get("action") or "")
        if action == "add_alert":
            in_add = True
        elif action == "reduce_alert":
            in_add = False
        elif action == "near_max":
            in_add = True
        if action in ("add_alert", "reduce_alert", "near_max") and action != prev_action:
            rows.append(
                {
                    "日期": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                    "权益": round(v, 2),
                    "峰值": round(peak, 2),
                    "回撤%": round(float(sig.get("dd_pct", 0)), 2),
                    "动作": action,
                    "说明": sig.get("alert") or "",
                }
            )
            prev_action = action
        elif action == "hold":
            prev_action = "hold"
    return pd.DataFrame(rows)


def freeze_factor2(equity: pd.Series) -> tuple[Any, dict[str, Any], str]:
    """由选参窗权益冻结因子2；样本最大回撤过小则回退默认阈值。"""
    from strategy.dd_alert import DEFAULT_AVG_YEARLY_MAX_DD, DEFAULT_HIST_MAX_DD

    raw = derive_thresholds(equity)
    note = "由2025选参窗权益标定"
    th = raw
    if float(raw.hist_max_dd) < 0.10 or float(raw.add_alert_dd) < 0.05:
        th = derive_thresholds(
            hist_max_dd=DEFAULT_HIST_MAX_DD,
            avg_yearly_max_dd=DEFAULT_AVG_YEARLY_MAX_DD,
        )
        note = (
            f"选参窗最大回撤仅{raw.hist_max_dd*100:.1f}%、加仓线退化到"
            f"{raw.add_alert_dd*100:.0f}%，样本过短不可用；"
            f"回退策略一默认 {th.label()}"
        )
    return th, th.as_dict(), note


def apply_best_cfg(best_cfg: dict[str, Any], *, end_date: str) -> BacktestConfig:
    entry = float(best_cfg.get("entry_pct") or best_cfg["threshold_pct"])
    stop = float(best_cfg.get("stop_pct") or best_cfg["threshold_pct"])
    return base_cfg(
        end_date=end_date,
        threshold_pct=float(best_cfg["threshold_pct"]),
        entry_pct=entry,
        stop_pct=stop,
        prev_entry_mode=str(best_cfg.get("prev_entry_mode") or "yin_or_small_yang"),
        ban_double_yang=bool(best_cfg.get("ban_double_yang", True)),
        skip_buy_after_overnight_stop=bool(
            best_cfg.get("skip_buy_after_overnight_stop", False)
        ),
        skip_buy_after_consec_stops=int(best_cfg.get("skip_buy_after_consec_stops") or 0),
    )


def run_best_full(best_cfg: dict[str, Any], *, end_date: str) -> tuple[Any, pd.DataFrame]:
    cfg = apply_best_cfg(best_cfg, end_date=end_date)
    entry = float(cfg.resolved_entry_pct())
    stop = float(cfg.resolved_stop_pct())
    if abs(entry - stop) < 1e-12 and cfg.entry_pct is None and cfg.stop_pct is None:
        return run_strategy1(cfg, show_report=False, verbose=False)

    def configure(strategy: OpenBreak3Strategy, params: Any) -> None:
        apply_strategy_config(strategy, params)
        strategy.entry_pct = entry
        strategy.stop_pct = stop
        strategy.prev_small_yang_pct = entry

    return run_backtest_pipeline(
        params=cfg,
        strategy_cls=OpenBreak3Strategy,
        configure=configure,
        print_summary_fn=None,
        show_report=False,
        verbose=False,
    )


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    today = pd.Timestamp.today().strftime("%Y%m%d")
    print(f"加载/刷新日线缓存 → {today}")
    try:
        daily_full = fetch_daily(
            SYMBOL,
            START,
            today,
            cache_path=CACHE,
            force_refresh=True,
        )
    except Exception as exc:
        print(f"远程刷新失败，改用本地缓存: {exc}")
        daily_full = fetch_daily(
            SYMBOL,
            START,
            today,
            cache_path=CACHE,
            force_refresh=False,
        )
    d0 = str(pd.to_datetime(daily_full["date"]).min().date())
    d1 = str(pd.to_datetime(daily_full["date"]).max().date())
    print(f"日线: {len(daily_full)} 根 · {d0} → {d1}")

    select_base = base_cfg(end_date=SELECT_END)
    print(f"=== 选参窗 {START}→{SELECT_END}（阈值须在 2026 前生成）===")
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, tuple[Any, pd.DataFrame]] = {}
    for name, fn in build_jobs(select_base):
        print(f"  IS {name} ...", flush=True)
        row, r, d = fn()
        artifacts[name] = (r, d)
        clean = {k: v for k, v in row.items() if k != "_cfg"}
        clean["_cfg_json"] = json.dumps(row["_cfg"], ensure_ascii=False)
        rows.append(clean)

    sweep = pd.DataFrame(rows)
    ranked = _rank(sweep)
    ranked.to_csv(DIR / "param_sweep_is_2025.csv", index=False, encoding="utf-8-sig")

    best = ranked.iloc[0]
    best_name = str(best["方案"])
    best_cfg = json.loads(str(best["_cfg_json"]))
    print(f"\n选参窗最优: {best_name}")
    print(best[[c for c in ranked.columns if not c.startswith("_")]].to_string())

    # 因子2：仅用选参窗权益标定，冻结（样本过短则回退默认）
    is_result, _ = artifacts[best_name]
    f2_th, f2_frozen, f2_note = freeze_factor2(is_result.equity_curve)
    print(f"\n因子2冻结预警阈值: {f2_th.label()}")
    print(f"  ({f2_note})")

    # 全期回测（冻结因子1参数）
    print(f"\n=== 冻结参数全期回测 {START}→{today} ===")
    result, daily = run_best_full(best_cfg, end_date=today)
    full_stats = _stats(result, daily, best_name)
    monthly = monthly_excess_rows(result, daily, label=NAME, initial_cash=CASH)
    holdings = holdings_table(result, daily)
    eq, close = _prepare_eq_close(result, daily)
    f2_events = factor2_alert_path(eq, f2_th)

    # 2026 样本外切片
    eq_2026 = eq[eq.index.year >= 2026]
    close_2026 = close[close.index.year >= 2026]
    oos = {}
    if len(eq_2026) > 1 and len(close_2026) > 1:
        # 以 2025 年末权益/收盘为起点
        eq_pre = eq[eq.index.year < 2026]
        px_pre = close[close.index.year < 2026]
        base_eq = float(eq_pre.iloc[-1]) if len(eq_pre) else CASH
        base_px = float(px_pre.iloc[-1]) if len(px_pre) else float(close_2026.iloc[0])
        oos_strat = (float(eq_2026.iloc[-1]) / base_eq - 1.0) * 100.0
        oos_bh = (float(close_2026.iloc[-1]) / base_px - 1.0) * 100.0
        peak = eq_2026.cummax()
        oos_dd = float((eq_2026 / peak - 1.0).min() * 100.0)
        oos = {
            "策略%": round(oos_strat, 2),
            "平权持有%": round(oos_bh, 2),
            "超额%": round(oos_strat - oos_bh, 2),
            "回撤%": round(oos_dd, 2),
        }

    monthly.to_csv(DIR / "monthly_excess.csv", index=False, encoding="utf-8-sig")
    if not holdings.empty:
        holdings.to_csv(DIR / "holdings.csv", index=False, encoding="utf-8-sig")
    if not f2_events.empty:
        f2_events.to_csv(DIR / "factor2_alerts.csv", index=False, encoding="utf-8-sig")

    top = ranked.head(10).drop(
        columns=[c for c in ranked.columns if c.startswith("_")], errors="ignore"
    )
    top.to_csv(DIR / "param_top10_is_2025.csv", index=False, encoding="utf-8-sig")

    win = float((monthly["超额%"] > 0).mean() * 100.0) if len(monthly) else 0.0
    currently_holding = False
    if not holdings.empty:
        currently_holding = str(holdings.iloc[-1].get("状态")) == "持有中"

    summary = {
        "标的": NAME,
        "代码": CODE,
        "选参窗口": f"{START} → {SELECT_END}",
        "回测窗口": f"{d0} → {d1}",
        "口径": (
            "策略一·因子1交易+因子2预警(不注资)；"
            f"阈值仅用2025选参；最优={best_name}；平权=买入持有"
        ),
        "最优方案": best_name,
        "最优因子1参数": best_cfg,
        "因子2冻结阈值": f2_frozen,
        "因子2说明": f2_th.label(),
        "因子2标定备注": f2_note,
        "选参窗": {
            "累计策略%": float(best["累计策略%"]),
            "累计平权%": float(best["累计平权%"]),
            "累计超额%": float(best["累计超额%"]),
            "夏普": float(best["夏普"]),
            "策略回撤%": float(best["策略回撤%"]),
            "闭环": int(best["闭环"]),
        },
        "全期": {
            "累计策略%": float(full_stats["累计策略%"]),
            "累计平权%": float(full_stats["累计平权%"]),
            "累计超额%": float(full_stats["累计超额%"]),
            "夏普": float(full_stats["夏普"]),
            "策略回撤%": float(full_stats["策略回撤%"]),
            "平权回撤%": full_stats["平权回撤%"],
            "闭环": int(full_stats["闭环"]),
            "胜率%": float(full_stats["胜率%"]),
        },
        "2026样本外": oos,
        "超额月胜率%": round(win, 1),
        "月均超额%": round(float(monthly["超额%"].mean()), 2) if len(monthly) else 0.0,
        "持仓笔数": int(len(holdings)),
        "当前持仓": currently_holding,
        "因子2预警次数": int(len(f2_events)),
        "扫描方案数": int(len(ranked)),
        "选参窗有超额方案数": int((ranked["累计超额%"] > 0).sum()),
    }
    (DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report_lines = [
        f"# {NAME}({CODE}) 策略一·因子1+因子2 前视切割回测",
        "",
        "> 研究回测，不构成投资建议。阈值仅用 2025-03-05～2025-12-31 生成，再冻结用于全期。",
        "",
        "## 最佳阈值（2025 选参窗）",
        "",
        f"- **方案**: {best_name}",
        f"- **买入阈值**: {best_cfg.get('entry_pct', best_cfg['threshold_pct'])*100:.1f}%",
        f"- **止损阈值**: {best_cfg.get('stop_pct', best_cfg['threshold_pct'])*100:.1f}%",
        f"- **前日过滤**: {best_cfg.get('prev_entry_mode')}",
        f"- **禁双阳**: {best_cfg.get('ban_double_yang')}",
        f"- **因子2预警（冻结）**: {f2_th.label()}",
        f"- **因子2备注**: {f2_note}",
        "",
        "### 选参窗表现",
        "",
        f"| 累计策略 | 累计持有 | 超额 | 夏普 | 回撤 | 闭环 |",
        f"|---:|---:|---:|---:|---:|---:|",
        (
            f"| {best['累计策略%']:.2f}% | {best['累计平权%']:.2f}% | "
            f"{best['累计超额%']:.2f}% | {best['夏普']:.3f} | "
            f"{best['策略回撤%']:.2f}% | {int(best['闭环'])} |"
        ),
        "",
        f"## 全期回测（{d0} → {d1}）",
        "",
        f"| 累计策略 | 累计持有 | 超额 | 夏普 | 策略回撤 | 持有回撤 | 闭环 | 胜率 |",
        f"|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {full_stats['累计策略%']:.2f}% | {full_stats['累计平权%']:.2f}% | "
            f"{full_stats['累计超额%']:.2f}% | {full_stats['夏普']:.3f} | "
            f"{full_stats['策略回撤%']:.2f}% | {full_stats['平权回撤%']} | "
            f"{full_stats['闭环']} | {full_stats['胜率%']:.1f}% |"
        ),
        "",
    ]
    if oos:
        report_lines += [
            "## 2026 样本外（相对 2025 年末）",
            "",
            f"| 策略 | 持有 | 超额 | 回撤 |",
            f"|---:|---:|---:|---:|",
            (
                f"| {oos['策略%']:.2f}% | {oos['平权持有%']:.2f}% | "
                f"{oos['超额%']:.2f}% | {oos['回撤%']:.2f}% |"
            ),
            "",
        ]
    report_lines += [
        "## 分月收益 vs 持有",
        "",
        monthly.to_markdown(index=False),
        "",
        f"超额月胜率 {win:.1f}% · 月均超额 {summary['月均超额%']:.2f}%",
        "",
        "## 持仓明细",
        "",
    ]
    if holdings.empty:
        report_lines.append("_无成交_")
    else:
        report_lines.append(holdings.to_markdown(index=False))
    report_lines += ["", "## 因子2 预警事件（冻结阈值扫描）", ""]
    if f2_events.empty:
        report_lines.append("_选参窗标定阈值下，全期未触发加减仓预警切换_")
    else:
        report_lines.append("_下表仅列动作切换日（非每日重复）_")
        report_lines.append("")
        report_lines.append(f2_events.to_markdown(index=False))
    report_lines += [
        "",
        "## 选参窗 Top10",
        "",
        top.to_markdown(index=False),
        "",
    ]
    (DIR / "report.md").write_text("\n".join(report_lines), encoding="utf-8")

    print("\n========== 全期 ==========")
    print(json.dumps(summary["全期"], ensure_ascii=False, indent=2))
    print("\n分月:")
    print(monthly.to_string(index=False))
    if not holdings.empty:
        print("\n持仓:")
        print(holdings.to_string(index=False))
    print(f"\n产出: {DIR}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
