from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _ic_summary(values: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return 0.0, 0.0
    standard_deviation = float(clean.std(ddof=1)) if len(clean) > 1 else float("nan")
    mean = float(clean.mean())
    information_ratio = (
        float(np.sqrt(252.0) * mean / standard_deviation)
        if standard_deviation > 0
        else 0.0
    )
    return mean, information_ratio


def calculate_prediction_metrics(
    frame: pd.DataFrame,
    prediction_column: str = "prediction",
    target_column: str = "target",
) -> dict[str, Any]:
    required = {"date", prediction_column, target_column}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Prediction metric frame is missing: {missing}")
    working = frame.loc[:, ["date", prediction_column, target_column]].copy()
    working[prediction_column] = pd.to_numeric(working[prediction_column], errors="coerce")
    working[target_column] = pd.to_numeric(working[target_column], errors="coerce")
    finite = np.isfinite(working[prediction_column]) & np.isfinite(working[target_column])
    working = working.loc[finite]
    if working.empty:
        raise ValueError("Prediction metric frame has no finite observations")

    pearson_values: list[float] = []
    rank_values: list[float] = []
    for _, cross_section in working.groupby("date", sort=True, observed=True):
        if len(cross_section) < 2:
            continue
        prediction = cross_section[prediction_column]
        target = cross_section[target_column]
        pearson_values.append(float(prediction.corr(target, method="pearson")))
        rank_values.append(float(prediction.corr(target, method="spearman")))

    daily_ic = pd.Series(pearson_values, dtype=float)
    daily_rank_ic = pd.Series(rank_values, dtype=float)
    mean_ic, icir = _ic_summary(daily_ic)
    mean_rank_ic, rank_icir = _ic_summary(daily_rank_ic)
    valid_dates = int(daily_ic.replace([np.inf, -np.inf], np.nan).notna().sum())
    if valid_dates == 0:
        raise ValueError("No validation date has a finite cross-sectional Pearson IC")
    return {
        "mean_rank_ic": mean_rank_ic,
        "rank_icir": rank_icir,
        "mean_ic": mean_ic,
        "icir": icir,
        "valid_date_count": valid_dates,
        "observation_count": int(len(working)),
    }


def _date_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    for name in ("date", "tradeDate", "datetime", "Unnamed: 0"):
        if name in frame.columns:
            values = frame[name]
            break
    else:
        values = pd.Series(frame.index, index=frame.index)
    raw = values.astype("string").str.strip()
    compact = raw.str.fullmatch(r"\d{8}").fillna(False)
    parsed = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    parsed.loc[compact] = pd.to_datetime(raw.loc[compact], format="%Y%m%d", errors="coerce")
    parsed.loc[~compact] = pd.to_datetime(raw.loc[~compact], errors="coerce")
    return pd.DatetimeIndex(parsed)


def _numeric(frame: pd.DataFrame, name: str | None) -> pd.Series:
    if name is None or name not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def annualized_sharpe_from_nav(nav: pd.Series) -> float:
    clean = pd.to_numeric(nav, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    returns = clean.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2:
        return 0.0
    standard_deviation = float(returns.std(ddof=1))
    if not np.isfinite(standard_deviation) or standard_deviation <= 0.0:
        return 0.0
    return float(np.sqrt(252.0) * returns.mean() / standard_deviation)


def parse_backtest_metrics(output_dir: str | Path, init_cash: float) -> dict[str, Any]:
    root = Path(output_dir)
    required = [root / "stats.csv", root / "ICs.csv", root / "group_ret.csv"]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"FactorBacktest output is missing: {missing}")
    stats = pd.read_csv(required[0])
    ics = pd.read_csv(required[1])
    if stats.empty:
        raise ValueError("FactorBacktest stats.csv is empty")

    absolute_nav = _numeric(stats, "unrealized_pnl")
    hedged_nav = _numeric(stats, "hedged_unrealized_pnl")
    if absolute_nav.empty or hedged_nav.empty:
        raise ValueError("stats.csv lacks usable unrealized_pnl or hedged_unrealized_pnl")
    sharpe = annualized_sharpe_from_nav(hedged_nav)
    drawdown = _numeric(stats, "MaxDrawdown")

    preferred_ic = "1d" if "1d" in ics.columns else None
    if preferred_ic is None:
        candidates = [
            name for name in ics.columns
            if name not in {"date", "tradeDate", "datetime", "Unnamed: 0"}
            and pd.to_numeric(ics[name], errors="coerce").notna().any()
        ]
        preferred_ic = candidates[0] if candidates else None
    ic = _numeric(ics, preferred_ic)
    ic_std = float(ic.std(ddof=1)) if len(ic) > 1 else float("nan")

    dates = _date_index(stats)
    nav_frame = pd.DataFrame(
        {"date": dates, "nav": pd.to_numeric(stats["hedged_unrealized_pnl"], errors="coerce")}
    )
    nav_frame = nav_frame.dropna().sort_values("date").set_index("date")
    monthly = nav_frame["nav"].resample("ME").last().pct_change(fill_method=None).dropna()
    return {
        "total_return": float(absolute_nav.iloc[-1] / float(init_cash) - 1.0),
        "hedged_total_return": float(hedged_nav.iloc[-1] / float(init_cash) - 1.0),
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.abs().max()) if not drawdown.empty else 0.0,
        "mean_ic": float(ic.mean()) if not ic.empty else 0.0,
        "icir": float(np.sqrt(252.0) * ic.mean() / ic_std) if ic_std > 0 else 0.0,
        "monthly_hedged_returns": {
            timestamp.strftime("%Y-%m"): float(value) for timestamp, value in monthly.items()
        },
        "observation_count": int(len(stats)),
    }


def is_improvement(
    candidate: dict[str, Any], baseline: dict[str, Any], selection: dict
) -> tuple[bool, float]:
    primary = str(selection["primary_metric"])
    delta = float(candidate[primary]) - float(baseline[primary])
    accepted = delta >= float(selection["min_delta"])
    return accepted, delta
