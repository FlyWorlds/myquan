from __future__ import annotations

import numpy as np
import pandas as pd

from factor_grouped_wrapper.labels import build_forward_target, target_to_long
from factor_grouped_wrapper.preprocess import equal_date_weights, preprocess_cross_sectional


def test_target_alignment_uses_t_plus_one_to_t_plus_two() -> None:
    dates = pd.date_range("2022-01-03", periods=5, freq="B")
    prices = pd.DataFrame({1: [10.0, 11.0, 12.0, 15.0, 18.0]}, index=dates)
    target = build_forward_target(prices, execution_lag=1, horizon=1)
    assert target.loc[dates[0], 1] == 12.0 / 11.0 - 1.0
    assert target.loc[dates[1], 1] == 15.0 / 12.0 - 1.0
    assert np.isnan(target.loc[dates[-2], 1])
    long = target_to_long(target, "2022-01-03", "2022-01-07")
    assert long.columns.tolist() == ["date", "ticker", "target"]
    assert long["ticker"].dtype == np.dtype("int64")


def test_cross_sectional_preprocess_is_date_local_and_float32() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-01-03"] * 3 + ["2022-01-04"] * 3),
            "ticker": [1, 2, 3, 1, 2, 3],
            "alpha": [1.0, 2.0, 100.0, 1000.0, 2000.0, 3000.0],
        }
    )
    config = {
        "winsor_lower": 0.0,
        "winsor_upper": 1.0,
        "cross_sectional_zscore": True,
        "fill_value": 0.0,
        "min_assets_per_date": 3,
    }
    processed = preprocess_cross_sectional(frame, ["alpha"], config)
    by_date = processed.groupby("date")["alpha"]
    assert np.allclose(by_date.mean().to_numpy(), 0.0, atol=1e-6)
    assert np.allclose(by_date.std(ddof=0).to_numpy(), 1.0, atol=1e-6)
    assert processed["alpha"].dtype == np.dtype("float32")


def test_equal_date_weights_give_each_date_equal_mass() -> None:
    dates = pd.Series(pd.to_datetime(["2022-01-03"] * 2 + ["2022-01-04"] * 4))
    weights = pd.Series(equal_date_weights(dates), index=dates)
    masses = weights.groupby(level=0).sum()
    assert np.isclose(masses.iloc[0], masses.iloc[1])
