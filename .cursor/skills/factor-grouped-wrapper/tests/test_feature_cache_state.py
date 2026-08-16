from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from factor_grouped_wrapper.config import cache_dir, config_fingerprint, validate_config
from factor_grouped_wrapper.experiment import evaluate_oos_experiment, freeze_experiment
from factor_grouped_wrapper.feature_store import (
    CachedFeatureStore,
    prepare_development_cache,
    oos_cache_dir,
    prepare_oos_cache,
)
from factor_grouped_wrapper.serialization import atomic_write_json, read_json
from factor_grouped_wrapper.state import create_or_resume_run, update_lifecycle


def _toy_config(tmp_path: Path) -> dict:
    factor_path = tmp_path / "factors.parquet"
    rows = []
    dates = [20200102, 20200103, 20210104, 20210105, 20220104, 20220105]
    for date in dates:
        for ticker in (1, 2):
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "f1": float(ticker + date % 10),
                    "f2": 1.0 if date == 20200102 and ticker == 1 else np.nan,
                }
            )
    pd.DataFrame(rows).to_parquet(factor_path, index=False)

    market_root = tmp_path / "market"
    market_root.mkdir()
    price_dates = pd.bdate_range("2020-01-02", "2022-01-10")
    pd.DataFrame(
        {
            "1": 100.0 + np.arange(len(price_dates)),
            "2": 200.0 + np.arange(len(price_dates)),
        },
        index=price_dates,
    ).to_parquet(market_root / "trade_price.parquet")
    return {
        "data": {
            "factor_bank": str(factor_path),
            "external_factor_bank": None,
            "market_data_root": str(market_root),
            "initial_factors": ["f1", "f2"],
            "external_factors": None,
        },
        "split": {
            "train_start": "2020-01-02",
            "train_end": "2020-01-03",
            "valid_start": "2021-01-04",
            "valid_end": "2021-01-05",
            "oos_start": "2022-01-04",
            "oos_end": "2022-01-05",
        },
        "label": {"execution_lag": 1, "horizon": 1},
        "preprocess": {
            "min_factor_coverage": 0.75,
            "winsor_lower": 0.0,
            "winsor_upper": 1.0,
            "cross_sectional_zscore": True,
            "fill_value": 0.0,
            "min_assets_per_date": 2,
        },
        "model": {"type": "lgbm", "n_jobs": 1, "params": {"n_estimators": 2}},
        "grouping": {
            "seeds": [42],
            "source_prefixes": [],
            "backward_stages": [{"name": "singleton", "group_size": 1}],
            "forward_group_size": 1,
        },
        "selection": {
            "primary_metric": "mean_ic",
            "min_delta": 0.005,
            "forward_enabled": False,
        },
        "backtest": {
            "skill_root": str(tmp_path / "backtest"),
            "python_executable": "python",
            "strategy": "long_only_equal_weight",
            "init_cash": 100.0,
            "final_savemode": 3,
            "overrides": {"buy_sell_shift": 1, "benchmark": "benchmark"},
        },
        "runtime": {
            "output_root": str(tmp_path / "runs"),
            "cache_root": str(tmp_path / "cache"),
        },
    }


def test_development_cache_filters_coverage_and_does_not_read_oos(tmp_path: Path) -> None:
    config = _toy_config(tmp_path)
    manifest_path = prepare_development_cache(config)
    manifest = read_json(manifest_path)
    assert manifest["initial_factors"] == ["f1"]
    assert manifest["development_only"] is True
    assert not oos_cache_dir(config, ["f1"]).exists()
    store = CachedFeatureStore(config)
    train = store.load_supervised(["f1"], "2020-01-02", "2020-01-03")
    assert len(train) == 4
    assert train.columns.tolist() == ["date", "ticker", "f1", "target"]

    oos_manifest = prepare_oos_cache(config, ["f1"])
    assert oos_manifest.is_file()
    oos = CachedFeatureStore(config, oos=True, oos_factors=["f1"]).load_supervised(["f1"], "2022-01-04", "2022-01-05")
    assert len(oos) == 4


def test_freeze_requires_completed_search_and_is_idempotent(tmp_path: Path) -> None:
    config = _toy_config(tmp_path)
    prepare_development_cache(config)
    run_dir = create_or_resume_run(config)
    with pytest.raises(RuntimeError, match="completed development search"):
        freeze_experiment(config, run_dir)
    update_lifecycle(run_dir, "BACKWARD_DONE")
    with pytest.raises(FileNotFoundError, match="final_factor_pool.json"):
        freeze_experiment(config, run_dir)
    atomic_write_json(
        run_dir / "final_factor_pool.json",
        {
            "phase": "backward",
            "selected_from_pool_a": ["f1"],
            "added_from_pool_b": [],
            "final_factors": ["f1"],
            "best_candidate_id": "candidate",
            "search_metrics": {"mean_ic": 0.1},
        },
    )
    frozen = freeze_experiment(config, run_dir)
    assert read_json(frozen)["selected_factors"] == ["f1"]
    assert freeze_experiment(config, run_dir) == frozen


def test_config_rejects_label_backtest_misalignment(tmp_path: Path) -> None:
    config = _toy_config(tmp_path)
    config["backtest"]["overrides"]["buy_sell_shift"] = 2
    with pytest.raises(ValueError, match="must equal"):
        validate_config(config, check_paths=False)


def test_execution_parallelism_is_validated_but_excluded_from_config_identity(
    tmp_path: Path,
) -> None:
    config = _toy_config(tmp_path)
    baseline = config_fingerprint(config)
    prepare_development_cache(config)
    run_dir = create_or_resume_run(config)
    config["runtime"].update({
        "candidate_workers": 12,
        "seed_workers": 3,
        "backtest_threads": 2,
        "preload_features": True,
    })

    validate_config(config, check_paths=False)
    assert config_fingerprint(config) == baseline
    assert create_or_resume_run(config, run_dir) == run_dir
    resolved = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    assert resolved["runtime"]["candidate_workers"] == 12
    assert resolved["runtime"]["seed_workers"] == 3
    assert resolved["runtime"]["preload_features"] is True

    config["runtime"]["candidate_workers"] = 0
    with pytest.raises(ValueError, match="candidate_workers"):
        validate_config(config, check_paths=False)


def test_config_accepts_sharpe_and_requires_stats_savemode(tmp_path: Path) -> None:
    config = _toy_config(tmp_path)
    config["selection"]["primary_metric"] = "sharpe"
    config["backtest"]["search_savemode"] = 2
    validate_config(config, check_paths=False)

    config["backtest"]["search_savemode"] = 1
    with pytest.raises(ValueError, match="search_savemode"):
        validate_config(config, check_paths=False)


def test_three_frozen_snapshots_run_three_oos_backtests_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _toy_config(tmp_path)
    prepare_development_cache(config)
    run_dir = create_or_resume_run(config)
    update_lifecycle(run_dir, "BACKWARD_DONE")
    atomic_write_json(
        run_dir / "pool_a_selection.json",
        {
            "selected_factors": ["f1"],
            "search_metrics": {"mean_ic": 0.1},
        },
    )
    atomic_write_json(
        run_dir / "pool_b_expansion.json",
        {"base_factors": ["f1"], "added_factors": []},
    )
    atomic_write_json(
        run_dir / "final_factor_pool.json",
        {
            "phase": "forward",
            "final_factors": ["f1"],
            "search_metrics": {"mean_ic": 0.11},
        },
    )
    update_lifecycle(run_dir, "FORWARD_DONE")
    frozen_path = freeze_experiment(config, run_dir)
    frozen = read_json(frozen_path)
    assert [item["name"] for item in frozen["snapshots"]] == [
        "original_a",
        "backward_a_star",
        "forward_final",
    ]

    prepared_unions: list[list[str]] = []
    backtest_calls: list[str] = []

    class FakeStore:
        def __init__(self, config: dict, oos: bool = False, oos_factors=None):
            self.oos = oos

        def load_supervised(self, factors, start: str, end: str) -> pd.DataFrame:
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
                    "ticker": [1, 2],
                    "target": [0.01, 0.02],
                }
            )
            for index, factor in enumerate(factors):
                frame[factor] = [float(index + 1), float(index + 2)]
            return frame

    class FakeModel:
        def __init__(self, config: dict):
            pass

        def fit(self, features, target, dates):
            return self

        def predict(self, features):
            return features.sum(axis=1).to_numpy(dtype=float)

    class FakeBacktestRunner:
        def __init__(self, config: dict):
            pass

        def run(self, signal_path, output_dir, start, end, savemode, report=False):
            output_dir.mkdir(parents=True, exist_ok=True)
            name = output_dir.parent.name
            backtest_calls.append(name)
            score = float(len(backtest_calls)) / 100.0
            metrics = {
                "total_return": score,
                "hedged_total_return": score,
                "sharpe": score,
                "max_drawdown": score,
                "mean_ic": score,
                "icir": score,
            }
            invocation = {"stdout": "", "stderr": "", "command": ["factor-backtest", name]}
            return metrics, invocation

    monkeypatch.setattr(
        "factor_grouped_wrapper.experiment.prepare_oos_cache",
        lambda config, factors: prepared_unions.append(list(factors)) or tmp_path / "oos-cache",
    )
    monkeypatch.setattr("factor_grouped_wrapper.experiment.CachedFeatureStore", FakeStore)
    monkeypatch.setattr("factor_grouped_wrapper.experiment.LightGBMModel", FakeModel)
    monkeypatch.setattr("factor_grouped_wrapper.experiment.BacktestRunner", FakeBacktestRunner)

    comparison_path = evaluate_oos_experiment(config, run_dir)
    comparison = read_json(comparison_path)
    assert prepared_unions == [["f1"]]
    assert backtest_calls == ["original_a", "backward_a_star", "forward_final"]
    assert len(comparison["snapshot_results"]) == 3
    assert len(comparison["comparisons"]) == 2

    comparison_path.unlink()
    resumed_path = evaluate_oos_experiment(config, run_dir)
    assert resumed_path == comparison_path
    assert backtest_calls == ["original_a", "backward_a_star", "forward_final"]
