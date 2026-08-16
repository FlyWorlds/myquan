from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from factor_grouped_wrapper.backtest_evaluator import CandidateEvaluator, candidate_id
from factor_grouped_wrapper.contracts import CandidateSpec
from factor_grouped_wrapper.feature_store import prepare_development_cache
from factor_grouped_wrapper.serialization import read_json


def _config(tmp_path: Path) -> dict:
    factor_path = tmp_path / "factor.parquet"
    factor_rows = []
    for date in [20200102, 20200103, 20200106, 20210104, 20210105, 20210106]:
        for ticker in (1, 2, 3):
            factor_rows.append({"date": date, "ticker": ticker, "f1": float(ticker)})
    pd.DataFrame(factor_rows).to_parquet(factor_path, index=False)
    market_root = tmp_path / "market"
    market_root.mkdir()
    price_dates = pd.bdate_range("2020-01-02", "2021-01-12")
    pd.DataFrame(
        {str(ticker): 100.0 + ticker + np.arange(len(price_dates)) for ticker in (1, 2, 3)},
        index=price_dates,
    ).to_parquet(market_root / "trade_price.parquet")

    backtest_root = tmp_path / "skill-factor-backtest"
    entrypoint = backtest_root / "scripts" / "run_factor_backtest.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text(
        """from pathlib import Path
import argparse
import os
import numpy as np
import pandas as pd
p=argparse.ArgumentParser()
p.add_argument('--output-dir', required=True)
args, _ = p.parse_known_args()
out=Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
(out/"thread_env.txt").write_text("|".join(os.environ.get(name, "") for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")))
dates=pd.date_range('2021-01-01', periods=50, freq='B')
returns=np.resize(np.array([0.001, -0.0002, 0.0007, 0.0001]), len(dates))
nav=100.0*np.cumprod(1.0+returns)
pd.DataFrame({'date':dates.strftime('%Y%m%d'),'unrealized_pnl':nav,'hedged_unrealized_pnl':nav,'DailyPCT':99.0,'MaxDrawdown':0.0}).to_csv(out/'stats.csv', index=False)
pd.DataFrame({'date':dates.strftime('%Y%m%d'),'1d':0.02}).to_csv(out/'ICs.csv', index=False)
pd.DataFrame({'date':dates.strftime('%Y%m%d'),'group1':1.0}).to_csv(out/'group_ret.csv', index=False)
""",
        encoding="utf-8",
    )
    return {
        "data": {"factor_bank": str(factor_path), "external_factor_bank": None, "market_data_root": str(market_root), "initial_factors": ["f1"], "external_factors": None},
        "split": {"train_start": "2020-01-02", "train_end": "2020-01-06", "valid_start": "2021-01-04", "valid_end": "2021-01-06", "oos_start": "2022-01-03", "oos_end": "2022-01-04"},
        "label": {"execution_lag": 1, "horizon": 1},
        "preprocess": {"min_factor_coverage": 1.0, "winsor_lower": 0.0, "winsor_upper": 1.0, "cross_sectional_zscore": True, "fill_value": 0.0, "min_assets_per_date": 3},
        "model": {"type": "lgbm", "n_jobs": 1, "params": {"objective": "regression", "n_estimators": 2, "min_child_samples": 1, "verbose": -1, "random_state": 42}},
        "grouping": {"seeds": [42], "source_prefixes": [], "backward_stages": [{"name": "singleton", "group_size": 1}], "forward_group_size": 1},
        "selection": {"primary_metric": "mean_ic", "min_delta": 0.005, "forward_enabled": False},
        "backtest": {"skill_root": str(backtest_root), "python_executable": sys.executable, "strategy": "long_only_equal_weight", "init_cash": 100.0, "final_savemode": 3, "reverse": False, "overrides": {"buy_sell_shift": 1}},
        "runtime": {"output_root": str(tmp_path / "runs"), "cache_root": str(tmp_path / "cache")},
    }


def test_candidate_evaluator_uses_pearson_ic_and_reuses_result(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepare_development_cache(config)
    run_dir = tmp_path / "run"
    evaluator = CandidateEvaluator(config, run_dir)
    spec = CandidateSpec(("f1",), "baseline", 42, "initial", 0)
    first = evaluator.evaluate(spec)
    second = evaluator.evaluate(spec)
    assert "mean_ic" in first.metrics
    assert "icir" in first.metrics
    assert "mean_rank_ic" in first.metrics
    assert second.cached is True
    assert first.candidate_id == second.candidate_id
    assert (first.candidate_dir / "result.json").is_file()
    assert not (first.candidate_dir / "validation_signal.parquet").exists()


def test_candidate_evaluator_preloads_features_without_changing_results(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    prepare_development_cache(config)
    spec = CandidateSpec(("f1",), "baseline", 42, "initial", 0)
    regular = CandidateEvaluator(config, tmp_path / "regular").evaluate(spec)

    config["runtime"]["preload_features"] = True
    preloaded_evaluator = CandidateEvaluator(config, tmp_path / "preloaded")
    preloaded = preloaded_evaluator.evaluate(spec)

    assert preloaded_evaluator._preloaded_train is not None
    assert preloaded_evaluator._preloaded_valid is not None
    assert preloaded.candidate_id == regular.candidate_id
    assert preloaded.metrics == regular.metrics


def test_candidate_evaluator_uses_validation_backtest_for_sharpe_and_reuses_result(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config["selection"].update({"primary_metric": "sharpe", "min_delta": 0.05})
    config["backtest"]["search_savemode"] = 2
    config["runtime"]["backtest_threads"] = 3
    prepare_development_cache(config)
    evaluator = CandidateEvaluator(config, tmp_path / "run")
    spec = CandidateSpec(("f1",), "baseline", 42, "initial", 0)

    first = evaluator.evaluate(spec)
    second = evaluator.evaluate(spec)

    assert np.isfinite(first.metrics["sharpe"])
    assert first.metrics["backtest_mean_rank_ic"] == 0.02
    assert "mean_ic" in first.metrics
    assert second.cached is True
    assert (first.candidate_dir / "validation_signal.parquet").is_file()
    assert (first.candidate_dir / "validation_backtest" / "stats.csv").is_file()
    invocation_path = first.candidate_dir / "backtest_invocation.json"
    assert invocation_path.is_file()
    assert read_json(invocation_path)["thread_limits"] == {
        "OMP_NUM_THREADS": "3",
        "OPENBLAS_NUM_THREADS": "3",
        "MKL_NUM_THREADS": "3",
        "NUMEXPR_NUM_THREADS": "3",
    }
    assert (first.candidate_dir / "validation_backtest" / "thread_env.txt").read_text() == "3|3|3|3"
    assert (first.candidate_dir / "backtest_stdout.log").is_file()


def test_candidate_ids_are_isolated_between_ic_and_sharpe_modes(tmp_path: Path) -> None:
    ic_config = _config(tmp_path)
    sharpe_config = {**ic_config, "selection": {**ic_config["selection"], "primary_metric": "sharpe"}}
    spec = CandidateSpec(("f1",), "baseline", 42, "initial", 0)

    assert candidate_id(spec, ic_config) != candidate_id(spec, sharpe_config)

    parallel_config = {**ic_config, "runtime": {**ic_config["runtime"], "candidate_workers": 12, "backtest_threads": 2}}
    assert candidate_id(spec, ic_config) == candidate_id(spec, parallel_config)
