from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .contracts import CandidateSpec, EvaluationResult
from .feature_store import load_cache_manifest
from .grouping import balanced_groups, groups_for_stage
from .metrics import is_improvement
from .serialization import atomic_write_json, read_json
from .state import update_lifecycle, utc_now


SEARCH_STATE_SCHEMA_VERSION = 3


class Evaluator(Protocol):
    def evaluate(self, spec: CandidateSpec) -> EvaluationResult: ...


def _evaluator_version(evaluator: Evaluator, primary: str) -> str:
    fallback = "factor_backtest_sharpe_v1" if primary == "sharpe" else "pearson_ic_v1"
    return str(getattr(evaluator, "evaluator_version", fallback))


def _metric_ranking_key(metrics: dict[str, Any], primary: str) -> tuple[float, ...]:
    ordered = (primary,) + tuple(
        metric
        for metric in ("mean_ic", "icir", "mean_rank_ic", "rank_icir")
        if metric != primary
    )
    return tuple(-float(metrics.get(metric, float("-inf"))) for metric in ordered)


def _ranking_key(result: EvaluationResult, primary: str) -> tuple:
    return (
        *_metric_ranking_key(result.metrics, primary),
        result.factor_count,
        result.factors,
    )


def _history_path(run_dir: Path, seed: int, phase: str) -> Path:
    return run_dir / "paths" / f"seed_{seed}" / f"{phase}_history.parquet"


def _state_path(run_dir: Path, seed: int, phase: str) -> Path:
    return run_dir / "paths" / f"seed_{seed}" / f"{phase}_state.json"


def _write_history(path: Path, history: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pd.DataFrame(history).to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _history_row(
    result: EvaluationResult,
    spec: CandidateSpec,
    accepted: bool,
    primary: str,
    delta: float | None,
) -> dict[str, Any]:
    return {
        "candidate_id": result.candidate_id,
        "direction": spec.direction,
        "seed": spec.seed,
        "stage": spec.stage,
        "iteration": spec.iteration,
        "group_id": spec.group_id,
        "changed_factors": list(spec.changed_factors),
        "factor_count": result.factor_count,
        "factors": list(result.factors),
        "primary_metric": primary,
        "primary_value": float(result.metrics[primary]),
        "primary_delta": delta,
        "accepted": bool(accepted),
        "cached": bool(result.cached),
    }


def _persist(state_path: Path, history_path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(state_path, state)
    _write_history(history_path, state["history"])


def _load_or_initialize(
    evaluator: Evaluator,
    run_dir: Path,
    factors: list[str],
    seed: int,
    phase: str,
    primary: str,
) -> tuple[Path, Path, dict[str, Any]]:
    state_path = _state_path(run_dir, seed, phase)
    history_path = _history_path(run_dir, seed, phase)
    if state_path.is_file():
        state = read_json(state_path)
        expected_evaluator = _evaluator_version(evaluator, primary)
        if (
            state.get("schema_version") != SEARCH_STATE_SCHEMA_VERSION
            or state.get("evaluator_version") != expected_evaluator
        ):
            raise RuntimeError(
                "Existing search state uses an incompatible evaluator; start a new run directory"
            )
        return state_path, history_path, state
    spec = CandidateSpec(tuple(factors), "baseline", seed, f"{phase}_initial", 0)
    result = evaluator.evaluate(spec)
    state = {
        "schema_version": SEARCH_STATE_SCHEMA_VERSION,
        "evaluator_version": _evaluator_version(evaluator, primary),
        "phase": phase,
        "seed": seed,
        "status": "running",
        "current_factors": list(result.factors),
        "baseline_candidate_id": result.candidate_id,
        "baseline_metrics": result.metrics,
        "completed_stages": [],
        "next_iteration": 1,
        "history": [_history_row(result, spec, True, primary, None)],
        "started_at": utc_now(),
    }
    _persist(state_path, history_path, state)
    return state_path, history_path, state


def _groups_path(run_dir: Path, seed: int, phase: str, stage: str) -> Path:
    return run_dir / "groups" / f"{phase}_seed_{seed}_{stage}.json"


def _load_or_create_backward_groups(
    run_dir: Path,
    seed: int,
    stage: dict,
    factors: list[str],
    prefixes: list[str],
) -> list[tuple[str, ...]]:
    path = _groups_path(run_dir, seed, "backward", str(stage["name"]))
    if path.is_file():
        return [tuple(group) for group in read_json(path)["groups"]]
    groups = groups_for_stage(factors, stage, seed, prefixes)
    atomic_write_json(path, {"phase": "backward", "seed": seed, "stage": stage, "groups": [list(group) for group in groups]})
    return groups


def _candidate_specs(
    current: set[str],
    groups: list[tuple[str, ...]],
    direction: str,
    seed: int,
    stage: str,
    iteration: int,
) -> list[CandidateSpec]:
    specs = []
    for index, fixed_group in enumerate(groups):
        if direction == "backward":
            changed = tuple(sorted(current.intersection(fixed_group)))
            factors = tuple(sorted(current.difference(changed)))
        else:
            changed = tuple(sorted(set(fixed_group).difference(current)))
            factors = tuple(sorted(current.union(changed)))
        if not changed or not factors:
            continue
        specs.append(CandidateSpec(
            factors=factors,
            direction=direction,  # type: ignore[arg-type]
            seed=seed,
            stage=stage,
            iteration=iteration,
            group_id=f"group_{index:03d}",
            changed_factors=changed,
        ))
    return specs


def _evaluate_iteration(
    evaluator: Evaluator,
    specs: list[CandidateSpec],
    baseline_metrics: dict[str, Any],
    selection: dict,
    history: list[dict[str, Any]],
    candidate_workers: int = 1,
) -> tuple[bool, EvaluationResult | None]:
    if not specs:
        return False, None
    primary = str(selection["primary_metric"])
    worker_count = min(max(1, int(candidate_workers)), len(specs))
    if worker_count == 1:
        results = [evaluator.evaluate(spec) for spec in specs]
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="wrapper-candidate"
        ) as executor:
            results = list(executor.map(evaluator.evaluate, specs))
    evaluated = list(zip(specs, results, strict=True))
    _, best = sorted(evaluated, key=lambda item: _ranking_key(item[1], primary))[0]
    accepted, _ = is_improvement(best.metrics, baseline_metrics, selection)
    for spec, result in evaluated:
        candidate_accepted, delta = is_improvement(result.metrics, baseline_metrics, selection)
        history.append(_history_row(
            result,
            spec,
            accepted and candidate_accepted and result.candidate_id == best.candidate_id,
            primary,
            delta,
        ))
    return accepted, best


def run_backward_path(
    config: dict[str, Any],
    run_dir: Path,
    evaluator: Evaluator,
    seed: int,
    initial_factors: list[str],
) -> dict[str, Any]:
    selection, grouping = config["selection"], config["grouping"]
    primary = str(selection["primary_metric"])
    state_path, history_path, state = _load_or_initialize(
        evaluator, run_dir, initial_factors, seed, "backward", primary
    )
    if state["status"] == "complete":
        return state
    prefixes = list(grouping.get("source_prefixes", []))
    for stage in grouping["backward_stages"]:
        stage_name = str(stage["name"])
        if stage_name in state["completed_stages"]:
            continue
        threshold = stage.get("enter_when_factor_count_at_most")
        if threshold is not None and len(state["current_factors"]) > int(threshold):
            state["completed_stages"].append(stage_name)
            state.setdefault("skipped_stages", []).append(stage_name)
            _persist(state_path, history_path, state)
            continue
        groups = _load_or_create_backward_groups(
            run_dir, seed, stage, state["current_factors"], prefixes
        )
        while True:
            iteration = int(state["next_iteration"])
            specs = _candidate_specs(
                set(state["current_factors"]), groups, "backward", seed, stage_name, iteration
            )
            accepted, best = _evaluate_iteration(
                evaluator,
                specs,
                state["baseline_metrics"],
                selection,
                state["history"],
                int(config.get("runtime", {}).get("candidate_workers", 1)),
            )
            state["next_iteration"] = iteration + 1
            if not accepted or best is None:
                break
            state["current_factors"] = list(best.factors)
            state["baseline_candidate_id"] = best.candidate_id
            state["baseline_metrics"] = best.metrics
            _persist(state_path, history_path, state)
        state["completed_stages"].append(stage_name)
        _persist(state_path, history_path, state)
    state.update({"status": "complete", "completed_at": utc_now()})
    _persist(state_path, history_path, state)
    return state


def run_forward_path(
    config: dict[str, Any],
    run_dir: Path,
    evaluator: Evaluator,
    seed: int,
    start_factors: list[str],
    external_factors: list[str],
) -> dict[str, Any]:
    selection, grouping = config["selection"], config["grouping"]
    primary = str(selection["primary_metric"])
    state_path, history_path, state = _load_or_initialize(
        evaluator, run_dir, start_factors, seed, "forward", primary
    )
    initial_state_factors = sorted(state.get("history", [{}])[0].get("factors", []))
    if initial_state_factors != sorted(start_factors):
        raise RuntimeError(
            f"Existing forward path for seed {seed} does not start from the current pool A selection"
        )
    if state["status"] == "complete":
        return state
    groups_path = _groups_path(run_dir, seed, "forward", "external")
    if groups_path.is_file():
        groups = [tuple(group) for group in read_json(groups_path)["groups"]]
    else:
        groups = balanced_groups(
            external_factors,
            seed=seed,
            source_prefixes=grouping.get("source_prefixes", []),
            group_size=int(grouping.get("forward_group_size", 10)),
        )
        atomic_write_json(groups_path, {
            "phase": "forward", "seed": seed, "stage": "external", "groups": [list(group) for group in groups]
        })
    while True:
        iteration = int(state["next_iteration"])
        specs = _candidate_specs(
            set(state["current_factors"]), groups, "forward", seed, "external", iteration
        )
        accepted, best = _evaluate_iteration(
            evaluator,
            specs,
            state["baseline_metrics"],
            selection,
            state["history"],
            int(config.get("runtime", {}).get("candidate_workers", 1)),
        )
        state["next_iteration"] = iteration + 1
        if not accepted or best is None:
            break
        state["current_factors"] = list(best.factors)
        state["baseline_candidate_id"] = best.candidate_id
        state["baseline_metrics"] = best.metrics
        _persist(state_path, history_path, state)
    state.update({"status": "complete", "completed_stages": ["external"], "completed_at": utc_now()})
    _persist(state_path, history_path, state)
    return state


def build_development_checkpoint(config: dict[str, Any], run_dir: Path, phase: str) -> Path:
    primary = str(config["selection"]["primary_metric"])
    paths = []
    for seed in [int(value) for value in config["grouping"]["seeds"]]:
        state_path = _state_path(run_dir, seed, phase)
        if state_path.is_file():
            state = read_json(state_path)
            if state.get("status") == "complete":
                paths.append(state)
    if not paths:
        raise RuntimeError(f"No completed {phase} paths")
    paths.sort(key=lambda state: (
        *_metric_ranking_key(state["baseline_metrics"], primary),
        len(state["current_factors"]),
        tuple(state["current_factors"]),
    ))
    best = paths[0]
    all_factors = sorted({name for state in paths for name in state["current_factors"]})
    checkpoint = {
        "schema_version": SEARCH_STATE_SCHEMA_VERSION,
        "phase": phase,
        "primary_metric": primary,
        "best_seed": int(best["seed"]),
        "best_candidate_id": best["baseline_candidate_id"],
        "selected_factors": best["current_factors"],
        "search_metrics": best["baseline_metrics"],
        "factor_survival_frequency": {
            name: sum(name in state["current_factors"] for state in paths) / len(paths)
            for name in all_factors
        },
        "paths": [{
            "seed": state["seed"],
            "candidate_id": state["baseline_candidate_id"],
            "factor_count": len(state["current_factors"]),
            "search_metrics": state["baseline_metrics"],
        } for state in paths],
        "updated_at": utc_now(),
    }
    path = run_dir / "development_checkpoint.json"
    atomic_write_json(path, checkpoint)
    return path


def _write_final_factor_pool(
    run_dir: Path,
    pool_a: dict[str, Any],
    checkpoint: dict[str, Any],
    added_factors: list[str],
) -> Path:
    final_factors = sorted(checkpoint["selected_factors"])
    payload = {
        "schema_version": SEARCH_STATE_SCHEMA_VERSION,
        "phase": checkpoint["phase"],
        "selected_from_pool_a": sorted(pool_a["selected_factors"]),
        "added_from_pool_b": sorted(added_factors),
        "final_factors": final_factors,
        "factor_count": len(final_factors),
        "primary_metric": checkpoint["primary_metric"],
        "best_seed": checkpoint["best_seed"],
        "best_candidate_id": checkpoint["best_candidate_id"],
        "search_metrics": checkpoint["search_metrics"],
        "updated_at": utc_now(),
    }
    path = run_dir / "final_factor_pool.json"
    atomic_write_json(path, payload)
    return path


def _write_pool_a_selection(
    run_dir: Path,
    initial_factors: list[str],
    checkpoint: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    selected = sorted(checkpoint["selected_factors"])
    payload = {
        "schema_version": SEARCH_STATE_SCHEMA_VERSION,
        "phase": "backward",
        "input_factors": sorted(initial_factors),
        "selected_factors": selected,
        "removed_factors": sorted(set(initial_factors).difference(selected)),
        "factor_count": len(selected),
        "primary_metric": checkpoint["primary_metric"],
        "best_seed": checkpoint["best_seed"],
        "best_candidate_id": checkpoint["best_candidate_id"],
        "search_metrics": checkpoint["search_metrics"],
        "factor_survival_frequency": checkpoint["factor_survival_frequency"],
        "paths": checkpoint["paths"],
        "updated_at": utc_now(),
    }
    path = run_dir / "pool_a_selection.json"
    atomic_write_json(path, payload)
    return path, payload


def _write_pool_b_expansion(
    run_dir: Path,
    pool_a: dict[str, Any],
    external_factors: list[str],
    checkpoint: dict[str, Any],
) -> tuple[Path, Path]:
    base = set(pool_a["selected_factors"])
    candidates = set(external_factors).difference(base)
    selected = set(checkpoint["selected_factors"])
    added = sorted(selected.difference(base).intersection(candidates))
    payload = {
        "schema_version": SEARCH_STATE_SCHEMA_VERSION,
        "phase": "forward",
        "base_factors": sorted(base),
        "candidate_factors": sorted(candidates),
        "added_factors": added,
        "rejected_factors": sorted(candidates.difference(added)),
        "factor_count_before": len(base),
        "factor_count_after": len(selected),
        "primary_metric": checkpoint["primary_metric"],
        "best_seed": checkpoint["best_seed"],
        "best_candidate_id": checkpoint["best_candidate_id"],
        "search_metrics_before": pool_a["search_metrics"],
        "search_metrics_after": checkpoint["search_metrics"],
        "paths": checkpoint["paths"],
        "updated_at": utc_now(),
    }
    path = run_dir / "pool_b_expansion.json"
    atomic_write_json(path, payload)
    final_path = _write_final_factor_pool(run_dir, pool_a, checkpoint, added)
    return path, final_path


def run_backward_search(config: dict[str, Any], run_dir: Path, evaluator: Evaluator) -> Path:
    manifest = load_cache_manifest(config)
    initial = manifest["initial_factors"]
    seeds = [int(value) for value in config["grouping"]["seeds"]]
    seed_workers = min(
        max(1, int(config.get("runtime", {}).get("seed_workers", 1))), len(seeds)
    )
    if seed_workers == 1:
        for seed in seeds:
            run_backward_path(config, run_dir, evaluator, seed, initial)
    else:
        with ThreadPoolExecutor(
            max_workers=seed_workers, thread_name_prefix="wrapper-backward-seed"
        ) as executor:
            list(
                executor.map(
                    lambda seed: run_backward_path(
                        config, run_dir, evaluator, seed, initial
                    ),
                    seeds,
                )
            )
    checkpoint = build_development_checkpoint(config, run_dir, "backward")
    checkpoint_payload = read_json(checkpoint)
    pool_a_path, pool_a = _write_pool_a_selection(run_dir, initial, checkpoint_payload)
    forward_pending = bool(config["selection"].get("forward_enabled", False)) and bool(
        manifest["external_factors"]
    )
    if not forward_pending:
        _write_final_factor_pool(run_dir, pool_a, checkpoint_payload, [])
    update_lifecycle(run_dir, "BACKWARD_DONE")
    return pool_a_path


def run_forward_search(config: dict[str, Any], run_dir: Path, evaluator: Evaluator) -> Path:
    if not config["selection"].get("forward_enabled", False):
        raise ValueError("Forward search is disabled by selection.forward_enabled")
    external = load_cache_manifest(config)["external_factors"]
    if not external:
        raise ValueError("Forward search requires data.external_factor_bank with eligible factors")
    pool_a_path = run_dir / "pool_a_selection.json"
    if pool_a_path.is_file():
        pool_a = read_json(pool_a_path)
    else:
        initial = list(load_cache_manifest(config)["initial_factors"])
        first_seed = int(config["grouping"]["seeds"][0])
        baseline = evaluator.evaluate(
            CandidateSpec(tuple(initial), "baseline", first_seed, "forward_initial", 0)
        )
        pool_a = {
            "phase": "original",
            "selected_factors": initial,
            "search_metrics": baseline.metrics,
        }
    start_factors = list(pool_a["selected_factors"])
    seeds = [int(value) for value in config["grouping"]["seeds"]]
    seed_workers = min(
        max(1, int(config.get("runtime", {}).get("seed_workers", 1))), len(seeds)
    )
    if seed_workers == 1:
        for seed in seeds:
            run_forward_path(
                config, run_dir, evaluator, seed, start_factors, external
            )
    else:
        with ThreadPoolExecutor(
            max_workers=seed_workers, thread_name_prefix="wrapper-forward-seed"
        ) as executor:
            list(
                executor.map(
                    lambda seed: run_forward_path(
                        config, run_dir, evaluator, seed, start_factors, external
                    ),
                    seeds,
                )
            )
    checkpoint = build_development_checkpoint(config, run_dir, "forward")
    _, final_path = _write_pool_b_expansion(run_dir, pool_a, external, read_json(checkpoint))
    update_lifecycle(run_dir, "FORWARD_DONE")
    return final_path
