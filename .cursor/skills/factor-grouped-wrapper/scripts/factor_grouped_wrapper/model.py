from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .preprocess import equal_date_weights


class LightGBMModel:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.estimator = None
        self.feature_names: tuple[str, ...] = ()

    def fit(self, features: pd.DataFrame, target: pd.Series, dates: pd.Series) -> "LightGBMModel":
        try:
            from lightgbm import LGBMRegressor
        except ImportError as exc:
            raise RuntimeError("lightgbm is required; install requirements.txt") from exc
        params = dict(self.config.get("params", {}))
        params["n_jobs"] = int(self.config["n_jobs"])
        self.estimator = LGBMRegressor(**params)
        self.feature_names = tuple(str(name) for name in features.columns)
        self.estimator.fit(
            features.astype(np.float32),
            target.to_numpy(dtype=np.float64, copy=False),
            sample_weight=equal_date_weights(dates),
        )
        return self

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if self.estimator is None:
            raise RuntimeError("Model must be fitted before prediction")
        if tuple(str(name) for name in features.columns) != self.feature_names:
            raise ValueError("Prediction feature order does not match the fitted model")
        prediction = np.asarray(
            self.estimator.predict(features.astype(np.float32)), dtype=np.float64
        )
        if not np.isfinite(prediction).all():
            raise RuntimeError("LightGBM produced non-finite predictions")
        return prediction
