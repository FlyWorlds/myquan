from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest_evaluator import BacktestRunner, CandidateEvaluator, write_signal
from .config import cache_fingerprint, config_fingerprint, validate_config
from .feature_store import (
    CachedFeatureStore,
    inspect_factor_banks,
    load_cache_manifest,
    prepare_development_cache,
    prepare_oos_cache,
)
from .model import LightGBMModel
from .search import run_backward_search, run_forward_search
from .serialization import atomic_write_json, atomic_write_text, read_json
from .state import create_or_resume_run, lifecycle_state, update_lifecycle, utc_now


def validate_experiment(config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config, check_paths=True)
    inspected = inspect_factor_banks(config)
    return {
        "status": "valid",
        "initial_factor_count": len(inspected["initial_factors"]),
        "external_factor_count": len(inspected["external_factors"]),
        "market_data_root": config["data"]["market_data_root"],
        "factor_bank": config["data"]["factor_bank"],
        "config_fingerprint": config_fingerprint(config),
        "cache_fingerprint": cache_fingerprint(config),
    }


def prepare_cache_experiment(config: dict[str, Any]) -> Path:
    validate_config(config, check_paths=True)
    return prepare_development_cache(config)


def backward_experiment(config: dict[str, Any], run_dir: str | Path | None = None) -> tuple[Path, Path]:
    validate_config(config, check_paths=True)
    load_cache_manifest(config)
    run_path = create_or_resume_run(config, run_dir)
    evaluator = CandidateEvaluator(config, run_path)
    checkpoint = run_backward_search(config, run_path, evaluator)
    return run_path, checkpoint


def forward_experiment(config: dict[str, Any], run_dir: str | Path | None = None) -> tuple[Path, Path]:
    validate_config(config, check_paths=True)
    run_path = create_or_resume_run(config, run_dir)
    if lifecycle_state(run_path) not in {"CACHED", "BACKWARD_DONE", "FORWARD_DONE"}:
        raise RuntimeError("Forward search requires a cached run")
    evaluator = CandidateEvaluator(config, run_path)
    checkpoint = run_forward_search(config, run_path, evaluator)
    return run_path, checkpoint


def _snapshot_payload(
    name: str, phase: str, factors: list[str], search_metrics: dict[str, Any] | None = None
) -> dict[str, Any]:
    snapshot = {
        "name": name,
        "phase": phase,
        "factors": sorted(factors),
        "factor_count": len(factors),
    }
    if search_metrics is not None:
        snapshot["search_metrics"] = search_metrics
    return snapshot


def freeze_experiment(config: dict[str, Any], run_dir: str | Path) -> Path:
    run_path = create_or_resume_run(config, run_dir)
    state = lifecycle_state(run_path)
    if state not in {"BACKWARD_DONE", "FORWARD_DONE", "FROZEN", "OOS_EVALUATED"}:
        raise RuntimeError("Freeze requires a completed development search")
    final_pool_path = run_path / "final_factor_pool.json"
    if not final_pool_path.is_file():
        raise FileNotFoundError(
            "final_factor_pool.json is missing; finish the configured search before freezing"
        )

    manifest = load_cache_manifest(config)
    final_pool = read_json(final_pool_path)
    snapshots = [
        _snapshot_payload("original_a", "original", list(manifest["initial_factors"]))
    ]
    pool_a_path = run_path / "pool_a_selection.json"
    if pool_a_path.is_file():
        pool_a = read_json(pool_a_path)
        snapshots.append(
            _snapshot_payload(
                "backward_a_star",
                "backward",
                list(pool_a["selected_factors"]),
                pool_a.get("search_metrics"),
            )
        )
    pool_b_path = run_path / "pool_b_expansion.json"
    if pool_b_path.is_file():
        snapshots.append(
            _snapshot_payload(
                "forward_final",
                "forward",
                list(final_pool["final_factors"]),
                final_pool.get("search_metrics"),
            )
        )

    final_snapshot = snapshots[-1]
    payload = {
        "schema_version": 2,
        "status": "frozen",
        "phase": final_snapshot["phase"],
        "selected_factors": final_snapshot["factors"],
        "factor_count": final_snapshot["factor_count"],
        "snapshots": snapshots,
        "config_fingerprint": config_fingerprint(config),
        "cache_fingerprint": cache_fingerprint(config),
        "frozen_at": utc_now(),
    }
    frozen_path = run_path / "frozen_selection.json"
    if frozen_path.is_file():
        existing = read_json(frozen_path)
        comparable = {key: value for key, value in payload.items() if key != "frozen_at"}
        existing_comparable = {
            key: value for key, value in existing.items() if key != "frozen_at"
        }
        if existing_comparable != comparable:
            raise FileExistsError(
                "Existing frozen selection differs from the current factor snapshots"
            )
        return frozen_path
    atomic_write_json(frozen_path, payload)
    update_lifecycle(run_path, "FROZEN")
    return frozen_path


def _append_oos_access(run_path: Path, event: dict[str, Any]) -> None:
    path = run_path / "oos_access_log.json"
    payload = read_json(path) if path.is_file() else {"schema_version": 1, "events": []}
    payload["events"].append(event)
    atomic_write_json(path, payload)


BACKTEST_DELTA_METRICS = (
    "total_return",
    "hedged_total_return",
    "sharpe",
    "max_drawdown",
    "mean_ic",
    "icir",
)


def _metric_deltas(
    later: dict[str, Any], earlier: dict[str, Any]
) -> dict[str, float]:
    return {
        name: float(later[name]) - float(earlier[name])
        for name in BACKTEST_DELTA_METRICS
        if name in later and name in earlier
    }


def _evaluate_oos_snapshot(
    config: dict[str, Any],
    run_path: Path,
    snapshot: dict[str, Any],
    train: pd.DataFrame,
    oos: pd.DataFrame,
    runner: BacktestRunner,
    *,
    force: bool,
    report: bool,
) -> dict[str, Any]:
    name = str(snapshot["name"])
    factors = list(snapshot["factors"])
    snapshot_root = run_path / "oos" / name
    result_path = snapshot_root / "evaluation.json"
    if result_path.is_file() and not force:
        existing = read_json(result_path)
        if (
            existing.get("status") == "complete"
            and existing.get("factors") == factors
            and existing.get("config_fingerprint") == config_fingerprint(config)
            and existing.get("cache_fingerprint") == cache_fingerprint(config)
        ):
            return existing
        raise RuntimeError(f"Existing OOS snapshot result is incompatible: {name}")
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    snapshot_root.mkdir(parents=True, exist_ok=True)

    split = config["split"]
    model = LightGBMModel(config["model"]).fit(
        train[factors], train["target"], train["date"]
    )
    signal = oos.loc[:, ["date", "ticker"]].assign(
        prediction=model.predict(oos[factors])
    )
    signal_path = snapshot_root / "predictions.parquet"
    write_signal(signal, signal_path)
    backtest_dir = snapshot_root / "backtest"
    metrics, invocation = runner.run(
        signal_path,
        backtest_dir,
        split["oos_start"],
        split["oos_end"],
        int(config["backtest"].get("final_savemode", 3)),
        report=report,
    )
    payload = {
        "schema_version": 2,
        "status": "complete",
        "name": name,
        "phase": snapshot["phase"],
        "factors": factors,
        "factor_count": len(factors),
        "refit_period": [split["train_start"], split["valid_end"]],
        "oos_period": [split["oos_start"], split["oos_end"]],
        "refit_rows": int(len(train)),
        "oos_rows": int(len(oos)),
        "metrics": metrics,
        "signal_path": str(signal_path),
        "backtest_output": str(backtest_dir),
        "config_fingerprint": config_fingerprint(config),
        "cache_fingerprint": cache_fingerprint(config),
        "completed_at": utc_now(),
    }
    atomic_write_text(snapshot_root / "backtest_stdout.log", invocation["stdout"])
    atomic_write_text(snapshot_root / "backtest_stderr.log", invocation["stderr"])
    atomic_write_json(
        snapshot_root / "backtest_invocation.json", {"command": invocation["command"]}
    )
    atomic_write_json(result_path, payload)
    return payload


def evaluate_oos_experiment(
    config: dict[str, Any],
    run_dir: str | Path,
    *,
    force: bool = False,
    report: bool = False,
) -> Path:
    run_path = create_or_resume_run(config, run_dir)
    frozen_path = run_path / "frozen_selection.json"
    if not frozen_path.is_file():
        raise FileNotFoundError("OOS evaluation requires frozen_selection.json")
    frozen = read_json(frozen_path)
    if frozen.get("schema_version") != 2:
        raise RuntimeError("Frozen selection uses an incompatible snapshot schema")
    if frozen.get("config_fingerprint") != config_fingerprint(config):
        raise RuntimeError("Frozen selection configuration fingerprint mismatch")
    if frozen.get("cache_fingerprint") != cache_fingerprint(config):
        raise RuntimeError("Frozen selection cache fingerprint mismatch")
    snapshots = list(frozen.get("snapshots", []))
    if not snapshots:
        raise RuntimeError("Frozen selection contains no OOS snapshots")

    evaluation_path = run_path / "oos_comparison.json"
    if evaluation_path.exists() and not force:
        raise FileExistsError(
            "OOS comparison already exists; pass --force only for an explicit rerun"
        )
    event = {
        "action": "evaluate_oos",
        "started_at": utc_now(),
        "force": bool(force),
        "snapshot_names": [snapshot["name"] for snapshot in snapshots],
    }
    _append_oos_access(run_path, event)
    try:
        factor_union = sorted(
            {factor for snapshot in snapshots for factor in snapshot["factors"]}
        )
        prepare_oos_cache(config, factor_union)
        split = config["split"]
        development_store = CachedFeatureStore(config, oos=False)
        oos_store = CachedFeatureStore(config, oos=True, oos_factors=factor_union)
        train = development_store.load_supervised(
            factor_union, split["train_start"], split["valid_end"]
        )
        oos = oos_store.load_supervised(
            factor_union, split["oos_start"], split["oos_end"]
        )
        if train.empty or oos.empty:
            raise ValueError("Frozen snapshots have no aligned refit or OOS rows")

        runner = BacktestRunner(config)
        results = [
            _evaluate_oos_snapshot(
                config,
                run_path,
                snapshot,
                train,
                oos,
                runner,
                force=force,
                report=report,
            )
            for snapshot in snapshots
        ]
        comparisons = [
            {
                "from": earlier["name"],
                "to": later["name"],
                "metric_deltas": _metric_deltas(later["metrics"], earlier["metrics"]),
            }
            for earlier, later in zip(results, results[1:])
        ]
        payload = {
            "schema_version": 2,
            "status": "complete",
            "refit_period": [split["train_start"], split["valid_end"]],
            "oos_period": [split["oos_start"], split["oos_end"]],
            "factor_union": factor_union,
            "snapshot_results": results,
            "comparisons": comparisons,
            "config_fingerprint": config_fingerprint(config),
            "cache_fingerprint": cache_fingerprint(config),
            "completed_at": utc_now(),
        }
        atomic_write_json(evaluation_path, payload)
        event.update({"status": "complete", "completed_at": payload["completed_at"]})
        _append_oos_access(run_path, event)
        update_lifecycle(run_path, "OOS_EVALUATED")
        return evaluation_path
    except BaseException as exc:
        event.update({"status": "failed", "failed_at": utc_now(), "error": str(exc)})
        _append_oos_access(run_path, event)
        raise
