from __future__ import annotations

import hashlib
import time
from threading import Lock
from pathlib import Path

import pytest

from factor_grouped_wrapper.contracts import CandidateSpec, EvaluationResult
from factor_grouped_wrapper.search import (
    run_backward_path,
    run_backward_search,
    run_forward_path,
    run_forward_search,
)
from factor_grouped_wrapper.serialization import atomic_write_json, read_json


class FakeEvaluator:
    def __init__(self, preferred: set[str]):
        self.preferred = preferred
        self.calls = 0

    def evaluate(self, spec: CandidateSpec) -> EvaluationResult:
        self.calls += 1
        factors = tuple(sorted(spec.factors))
        score = 0.10 - 0.02 * len(set(factors).difference(self.preferred)) - 0.05 * len(
            self.preferred.difference(factors)
        )
        identifier = hashlib.sha256(repr(spec.normalized()).encode()).hexdigest()
        metrics = {
            "mean_ic": score,
            "icir": score,
            "mean_rank_ic": score,
            "rank_icir": score,
            "hedged_total_return": score,
            "total_return": score,
            "sharpe": score,
            "max_drawdown": 0.1,
            "monthly_hedged_returns": {"2022-01": score, "2022-02": score},
        }
        return EvaluationResult(identifier, factors, metrics, Path("/tmp") / identifier)


class ConcurrentEvaluator(FakeEvaluator):
    def __init__(self, preferred: set[str]):
        super().__init__(preferred)
        self._lock = Lock()
        self.active = 0
        self.max_active = 0

    def evaluate(self, spec: CandidateSpec) -> EvaluationResult:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.02)
            return super().evaluate(spec)
        finally:
            with self._lock:
                self.active -= 1


class ConflictingMetricEvaluator:
    def evaluate(self, spec: CandidateSpec) -> EvaluationResult:
        factors = tuple(sorted(spec.factors))
        scores = {
            ("A", "B", "C"): (0.00, 0.00),
            ("A", "B"): (0.01, 0.90),
            ("A", "C"): (0.02, -0.90),
            ("B", "C"): (-0.10, 1.00),
        }
        mean_ic, mean_rank_ic = scores.get(factors, (0.00, 0.00))
        identifier = hashlib.sha256(repr(spec.normalized()).encode()).hexdigest()
        metrics = {
            "mean_ic": mean_ic,
            "icir": mean_ic,
            "mean_rank_ic": mean_rank_ic,
            "rank_icir": mean_rank_ic,
        }
        return EvaluationResult(identifier, factors, metrics, Path("/tmp") / identifier)


class SharpeEvaluator:
    evaluator_version = "factor_backtest_sharpe_v1"

    def __init__(self, preferred: set[str]):
        self.preferred = preferred

    def evaluate(self, spec: CandidateSpec) -> EvaluationResult:
        factors = tuple(sorted(spec.factors))
        sharpe = 1.0 - 0.2 * len(set(factors).difference(self.preferred)) - 0.4 * len(
            self.preferred.difference(factors)
        )
        identifier = hashlib.sha256(repr(spec.normalized()).encode()).hexdigest()
        metrics = {
            "sharpe": sharpe,
            "mean_ic": -sharpe,
            "icir": -sharpe,
            "mean_rank_ic": -sharpe,
            "rank_icir": -sharpe,
        }
        return EvaluationResult(identifier, factors, metrics, Path("/tmp") / identifier)


def _config() -> dict:
    return {
        "selection": {
            "primary_metric": "mean_ic",
            "min_delta": 0.005,
        },
        "grouping": {
            "source_prefixes": [],
            "backward_stages": [{"name": "singleton", "group_size": 1}],
            "forward_group_size": 1,
        },
    }


def _search_config(forward_enabled: bool) -> dict:
    config = _config()
    config["grouping"]["seeds"] = [7, 42]
    config["selection"]["forward_enabled"] = forward_enabled
    return config


def test_backward_path_eliminates_harmful_factors_and_resumes(tmp_path: Path) -> None:
    evaluator = FakeEvaluator({"A"})
    state = run_backward_path(_config(), tmp_path, evaluator, 42, ["A", "B", "C"])
    assert state["status"] == "complete"
    assert state["current_factors"] == ["A"]
    calls = evaluator.calls
    resumed = run_backward_path(_config(), tmp_path, evaluator, 42, ["A", "B", "C"])
    assert resumed["current_factors"] == ["A"]
    assert evaluator.calls == calls
    assert (tmp_path / "paths" / "seed_42" / "backward_history.parquet").is_file()


def test_backward_path_evaluates_one_iteration_in_parallel(tmp_path: Path) -> None:
    config = _config()
    config["runtime"] = {"candidate_workers": 4}
    evaluator = ConcurrentEvaluator({"A"})

    state = run_backward_path(config, tmp_path, evaluator, 42, ["A", "B", "C", "D"])

    assert state["current_factors"] == ["A"]
    assert evaluator.max_active > 1


def test_backward_path_prefers_pearson_ic_when_rank_ic_disagrees(tmp_path: Path) -> None:
    state = run_backward_path(
        _config(), tmp_path, ConflictingMetricEvaluator(), 42, ["A", "B", "C"]
    )
    assert state["current_factors"] == ["A", "C"]


def test_forward_path_adds_only_improving_group(tmp_path: Path) -> None:
    evaluator = FakeEvaluator({"A", "B"})
    state = run_forward_path(_config(), tmp_path, evaluator, 7, ["A"], ["B", "C"])
    assert state["status"] == "complete"
    assert state["current_factors"] == ["A", "B"]


def test_backward_and_forward_can_optimize_sharpe_when_ic_disagrees(tmp_path: Path) -> None:
    config = _config()
    config["selection"].update({"primary_metric": "sharpe", "min_delta": 0.05})

    backward = run_backward_path(
        config, tmp_path / "backward", SharpeEvaluator({"A"}), 42, ["A", "B", "C"]
    )
    forward = run_forward_path(
        config, tmp_path / "forward", SharpeEvaluator({"A", "B"}), 42, ["A"], ["B", "C"]
    )

    assert backward["current_factors"] == ["A"]
    assert forward["current_factors"] == ["A", "B"]


def test_search_state_cannot_resume_across_ic_and_sharpe_modes(tmp_path: Path) -> None:
    run_backward_path(_config(), tmp_path, FakeEvaluator({"A"}), 42, ["A", "B"])
    sharpe_config = _config()
    sharpe_config["selection"].update({"primary_metric": "sharpe", "min_delta": 0.05})

    with pytest.raises(RuntimeError, match="incompatible evaluator"):
        run_backward_path(
            sharpe_config, tmp_path, SharpeEvaluator({"A"}), 42, ["A", "B"]
        )


def test_forward_resume_rejects_a_different_pool_a(tmp_path: Path) -> None:
    evaluator = FakeEvaluator({"A", "B"})
    run_forward_path(_config(), tmp_path, evaluator, 7, ["A"], ["B"])
    with pytest.raises(RuntimeError, match="current pool A"):
        run_forward_path(_config(), tmp_path, evaluator, 7, ["X"], ["B"])


def test_backward_seed_paths_can_run_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {"initial_factors": ["A", "B", "C"], "external_factors": []}
    monkeypatch.setattr(
        "factor_grouped_wrapper.search.load_cache_manifest", lambda config: manifest
    )
    config = _search_config(forward_enabled=False)
    config["runtime"] = {"candidate_workers": 1, "seed_workers": 2}
    evaluator = ConcurrentEvaluator({"A"})

    run_backward_search(config, tmp_path, evaluator)

    assert evaluator.max_active > 1
    for seed in config["grouping"]["seeds"]:
        state = read_json(tmp_path / "paths" / f"seed_{seed}" / "backward_state.json")
        assert state["status"] == "complete"


def test_backward_writes_pool_a_and_final_when_forward_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {"initial_factors": ["A", "X"], "external_factors": []}
    monkeypatch.setattr(
        "factor_grouped_wrapper.search.load_cache_manifest", lambda config: manifest
    )

    pool_a_path = run_backward_search(
        _search_config(forward_enabled=False), tmp_path, FakeEvaluator({"A"})
    )

    pool_a = read_json(pool_a_path)
    assert pool_a["selected_factors"] == ["A"]
    assert pool_a["removed_factors"] == ["X"]
    final_pool = read_json(tmp_path / "final_factor_pool.json")
    assert final_pool["selected_from_pool_a"] == ["A"]
    assert final_pool["added_from_pool_b"] == []
    assert final_pool["final_factors"] == ["A"]


def test_forward_seeds_share_best_pool_a_and_write_pool_b_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "initial_factors": ["A", "X"],
        "external_factors": ["B", "C"],
    }
    monkeypatch.setattr(
        "factor_grouped_wrapper.search.load_cache_manifest", lambda config: manifest
    )
    config = _search_config(forward_enabled=True)
    run_backward_search(config, tmp_path, FakeEvaluator({"A"}))
    assert not (tmp_path / "final_factor_pool.json").exists()

    seed_42_backward = tmp_path / "paths" / "seed_42" / "backward_state.json"
    unrelated_backward = read_json(seed_42_backward)
    unrelated_backward["current_factors"] = ["X"]
    atomic_write_json(seed_42_backward, unrelated_backward)

    final_path = run_forward_search(config, tmp_path, FakeEvaluator({"A", "B"}))

    for seed in config["grouping"]["seeds"]:
        forward_state = read_json(tmp_path / "paths" / f"seed_{seed}" / "forward_state.json")
        assert forward_state["history"][0]["factors"] == ["A"]
    pool_b = read_json(tmp_path / "pool_b_expansion.json")
    assert pool_b["base_factors"] == ["A"]
    assert pool_b["added_factors"] == ["B"]
    assert pool_b["rejected_factors"] == ["C"]
    final_pool = read_json(final_path)
    assert final_pool["selected_from_pool_a"] == ["A"]
    assert final_pool["added_from_pool_b"] == ["B"]
    assert final_pool["final_factors"] == ["A", "B"]


def test_forward_search_can_start_from_original_pool_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {"initial_factors": ["A"], "external_factors": ["B", "C"]}
    monkeypatch.setattr(
        "factor_grouped_wrapper.search.load_cache_manifest", lambda config: manifest
    )
    config = _search_config(forward_enabled=True)

    final_path = run_forward_search(config, tmp_path, FakeEvaluator({"A", "B"}))

    assert not (tmp_path / "pool_a_selection.json").exists()
    pool_b = read_json(tmp_path / "pool_b_expansion.json")
    assert pool_b["base_factors"] == ["A"]
    assert pool_b["added_factors"] == ["B"]
    assert read_json(final_path)["final_factors"] == ["A", "B"]
