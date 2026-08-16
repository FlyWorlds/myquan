from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def factor_coverage(frame: pd.DataFrame, factors: Iterable[str]) -> pd.Series:
    names = list(factors)
    if frame.empty:
        return pd.Series(0.0, index=names, dtype=float)
    numeric = frame.loc[:, names].replace([np.inf, -np.inf], np.nan)
    return numeric.notna().mean().reindex(names).fillna(0.0)


def select_by_coverage(
    valid_counts: pd.Series,
    total_rows: int,
    min_coverage: float,
) -> tuple[list[str], dict[str, float]]:
    if total_rows <= 0:
        raise ValueError("Training factor bank contains no rows")
    coverage = valid_counts.astype(float).div(float(total_rows))
    selected = sorted(coverage.index[coverage >= min_coverage].astype(str).tolist())
    if not selected:
        raise ValueError("Training coverage filter removed every factor")
    return selected, {str(name): float(value) for name, value in coverage.sort_index().items()}


def preprocess_cross_sectional(
    frame: pd.DataFrame,
    factors: Iterable[str],
    config: dict,
) -> pd.DataFrame:
    names = list(factors)
    if not names:
        return frame.loc[:, ["date", "ticker"]].copy()
    required = {"date", "ticker", *names}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Feature frame is missing columns: {missing}")
    output_parts: list[pd.DataFrame] = []
    lower = float(config["winsor_lower"])
    upper = float(config["winsor_upper"])
    minimum = int(config["min_assets_per_date"])
    zscore = bool(config.get("cross_sectional_zscore", True))
    fill_value = float(config.get("fill_value", 0.0))

    for _, group in frame.groupby("date", sort=True, observed=True):
        values = group.loc[:, names].apply(pd.to_numeric, errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        counts = values.notna().sum(axis=0)
        low = values.quantile(lower, axis=0)
        high = values.quantile(upper, axis=0)
        clipped = values.clip(lower=low, upper=high, axis=1)
        if zscore:
            means = clipped.mean(axis=0)
            stds = clipped.std(axis=0, ddof=0).replace(0.0, np.nan)
            clipped = clipped.sub(means, axis=1).div(stds, axis=1)
        clipped.loc[:, counts < minimum] = np.nan
        keys = group.loc[:, ["date", "ticker"]].reset_index(drop=True)
        transformed = clipped.reset_index(drop=True).fillna(fill_value).astype("float32")
        output_parts.append(pd.concat([keys, transformed], axis=1))
    if not output_parts:
        return pd.DataFrame(columns=["date", "ticker", *names])
    output = pd.concat(output_parts, ignore_index=True)
    return output.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)


def equal_date_weights(dates: pd.Series) -> np.ndarray:
    counts = dates.groupby(dates, observed=True).transform("size").astype(float)
    weights = 1.0 / counts
    return (weights / weights.mean()).to_numpy(dtype=np.float64)
