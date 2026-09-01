"""策略十三 ETF walk-forward 共用：拉数、回测、窗口指标。"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import akshare as ak
import pandas as pd

from strategy import BacktestConfig, run_open_break
from strategy.backtest import OpenBreak3Strategy, metric
from strategy.base import run_backtest_pipeline
from strategy.config import _DAILY_CACHE_DIR
from strategy.data import AKSHARE_CALL_LOCK, _normalize_daily
from strategy.runner import apply_strategy_config
from strategy.strategies.strategy4.portfolio import window_metrics

logging.disable(logging.CRITICAL)

END = pd.Timestamp.today().strftime("%Y-%m-%d")
CASH = 100_000.0
WARM_START = "20220101"

# 标准 cohort A
IS_A_START, IS_A_END = "2023-01-02", "2025-12-31"
OOS_A_START = "2025-01-02"
# 2025 上市 cohort B
IS_B_END = "2025-12-31"
OOS_B_START = "2026-01-02"
MIN_IS_A = 120
MIN_IS_B = 40
MIN_OOS = 20
MIN_OOS_TRADES = 2


def discover_etfs() -> list[tuple[str, str, str]]:
    with AKSHARE_CALL_LOCK:
        df = ak.fund_etf_category_sina(symbol="ETF基金")
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for _, r in df.iterrows():
        sym = str(r["代码"]).strip().lower()
        if not sym.startswith(("sh", "sz")):
            continue
        code = sym[2:]
        if code in seen:
            continue
        seen.add(code)
        rows.append((sym, code, str(r["名称"]).strip()))
    return rows


def fetch_etf_sina(sym: str, start: str, end: str) -> pd.DataFrame:
    cache = _DAILY_CACHE_DIR / f"{sym}_daily_qfq.parquet"
    if cache.exists():
        try:
            cached = pd.read_parquet(cache)
            if not cached.empty:
                return _normalize_daily(cached, symbol=sym, start=start, end=end)
        except Exception:
            pass
    with AKSHARE_CALL_LOCK:
        raw = ak.fund_etf_hist_sina(symbol=sym)
    df = _normalize_daily(raw, symbol=sym, start=start, end=end)
    if not df.empty:
        _DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)
    return df


def _dates(daily: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(daily["date"])
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return d


def assign_cohort(daily: pd.DataFrame) -> tuple[str, dict[str, str]] | None:
    dates = _dates(daily)
    if dates.empty:
        return None
    first = pd.Timestamp(dates.min())
    if first <= pd.Timestamp("2023-01-31"):
        return "A", {
            "is_start": IS_A_START,
            "is_end": IS_A_END,
            "oos_start": OOS_A_START,
            "oos_end": END,
        }
    if first < pd.Timestamp("2026-01-01"):
        is_start = max(first, pd.Timestamp("2025-01-02")).strftime("%Y-%m-%d")
        return "B", {
            "is_start": is_start,
            "is_end": IS_B_END,
            "oos_start": OOS_B_START,
            "oos_end": END,
        }
    return None


def cohort_ok(daily: pd.DataFrame, windows: dict[str, str], cohort: str) -> bool:
    dates = _dates(daily)
    is_mask = (dates >= pd.Timestamp(windows["is_start"])) & (
        dates <= pd.Timestamp(windows["is_end"])
    )
    oos_mask = (dates >= pd.Timestamp(windows["oos_start"])) & (
        dates <= pd.Timestamp(windows["oos_end"])
    )
    min_is = MIN_IS_A if cohort == "A" else MIN_IS_B
    return int(is_mask.sum()) >= min_is and int(oos_mask.sum()) >= MIN_OOS


def _nav_series(result: Any) -> pd.Series:
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return pd.Series(dtype=float)
    s = eq["equity"] if isinstance(eq, pd.DataFrame) else eq
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return (
        pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize())
        .dropna()
        .sort_index()
    )


def _bh_nav(daily: pd.DataFrame) -> pd.Series:
    d = daily.copy()
    dates = _dates(d)
    close = pd.Series(d["close"].astype(float).to_numpy(), index=dates).sort_index()
    close.index = close.index.normalize()
    return (close / close.iloc[0]) * CASH


def stats_window(nav: pd.Series, bh: pd.Series, start: str, end: str) -> dict[str, float]:
    nav = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))]
    bh = bh.reindex(nav.index).ffill()
    if len(nav) < 5:
        return {
            "ret_pct": float("nan"),
            "excess_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "n_days": int(len(nav)),
        }
    m = window_metrics(nav, start=start, end=end)
    bh_m = window_metrics(bh, start=start, end=end)
    return {
        "ret_pct": m["ret_pct"],
        "excess_pct": m["ret_pct"] - bh_m["ret_pct"],
        "sharpe": m["sharpe"],
        "mdd_pct": m["mdd_pct"],
        "n_days": int(len(nav)),
    }


def base_cfg(sym: str, code: str, name: str, start: str) -> BacktestConfig:
    return BacktestConfig(
        symbol=sym,
        symbol_name=name,
        em_symbol=code,
        threshold_pct=0.025,
        start_date=start,
        end_date=END.replace("-", ""),
        initial_cash=CASH,
        stamp_tax_rate=0.0,
        tick=0.001,
        t0=False,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        daily_cache=_DAILY_CACHE_DIR / f"{sym}_daily_qfq.parquet",
    )


def run_sym(cfg: BacktestConfig, label: str) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    r, d = run_open_break(cfg, show_report=False, verbose=False)
    nav = _nav_series(r)
    bh = _bh_nav(d)
    return (
        {
            "label": label,
            "entry_pct": float(cfg.resolved_entry_pct()),
            "stop_pct": float(cfg.resolved_stop_pct()),
            "prev_entry_mode": cfg.prev_entry_mode,
            "win_rate": float(metric(r.metrics_df, "win_rate")),
            "closed_trades": int(metric(r.metrics_df, "closed_trade_count")),
            "nav": nav,
            "bh": bh,
        },
        r,
        d,
    )


def run_asym(
    base: BacktestConfig,
    *,
    entry: float,
    stop: float,
    label: str,
    **cfg_kw: Any,
) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    c = replace(base, threshold_pct=entry, **cfg_kw)

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
    nav = _nav_series(r)
    bh = _bh_nav(d)
    return (
        {
            "label": label,
            "entry_pct": entry,
            "stop_pct": stop,
            "prev_entry_mode": c.prev_entry_mode,
            "win_rate": float(metric(r.metrics_df, "win_rate")),
            "closed_trades": int(metric(r.metrics_df, "closed_trade_count")),
            "nav": nav,
            "bh": bh,
        },
        r,
        d,
    )


def param_jobs(base: BacktestConfig) -> list[tuple[str, Callable[[], tuple]]]:
    jobs: list[tuple[str, Callable[[], tuple]]] = []
    for pct in (0.02, 0.025, 0.03):
        jobs.append(
            (
                f"sym±{pct*100:g}%",
                lambda p=pct: run_sym(replace(base, threshold_pct=p), f"sym±{p*100:g}%"),
            )
        )
    jobs.append(
        (
            "sym±2.5%仅阴",
            lambda: run_sym(
                replace(base, threshold_pct=0.025, prev_entry_mode="yin_only"),
                "sym±2.5%仅阴",
            ),
        )
    )
    jobs.append(
        (
            "sym±2.5%不限前日",
            lambda: run_sym(
                replace(base, threshold_pct=0.025, prev_entry_mode="any"),
                "sym±2.5%不限前日",
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
        jobs.append((tag, lambda e=entry, s=stop, t=tag: run_asym(base, entry=e, stop=s, label=t)))
    return jobs


def score_is(row: dict[str, Any], windows: dict[str, str]) -> float:
    is_m = stats_window(row["nav"], row["bh"], windows["is_start"], windows["is_end"])
    ex = float(is_m.get("excess_pct") or float("nan"))
    sh = float(is_m.get("sharpe") or float("nan"))
    if ex != ex or sh != sh:
        return -1e9
    if ex <= 0:
        return -1e6 + ex
    return 3.0 * sh + 2.0 * ex / 100.0


def enrich_oos(row: dict[str, Any], windows: dict[str, str]) -> dict[str, Any]:
    is_m = stats_window(row["nav"], row["bh"], windows["is_start"], windows["is_end"])
    oos_m = stats_window(row["nav"], row["bh"], windows["oos_start"], windows["oos_end"])
    oos_trades = row.get("oos_closed_trades")
    if oos_trades is None:
        oos_trades = row["closed_trades"]
    out = {k: v for k, v in row.items() if k not in ("nav", "bh", "result")}
    out["is"] = is_m
    out["oos"] = oos_m
    out["oos_win_rate"] = row["win_rate"]
    return out
