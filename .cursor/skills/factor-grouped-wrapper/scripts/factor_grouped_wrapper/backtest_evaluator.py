from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from .config import cache_fingerprint, config_fingerprint
from .contracts import CandidateSpec, EvaluationResult
from .feature_store import CachedFeatureStore
from .metrics import calculate_prediction_metrics, parse_backtest_metrics
from .model import LightGBMModel
from .serialization import atomic_write_json, atomic_write_text, fingerprint, read_json


SIGNAL_COLUMN = "prediction"
BACKTEST_ENTRYPOINT = Path("scripts") / "run_factor_backtest.py"
IC_EVALUATOR_VERSION = "pearson_ic_v1"
SHARPE_EVALUATOR_VERSION = "factor_backtest_sharpe_v1"


def candidate_evaluator_version(config: dict[str, Any]) -> str:
    if config["selection"]["primary_metric"] == "sharpe":
        return SHARPE_EVALUATOR_VERSION
    return IC_EVALUATOR_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yyyymmdd(value: str) -> int:
    return int(pd.Timestamp(value).strftime("%Y%m%d"))


def resolve_backtest_entrypoint(config: dict[str, Any]) -> Path:
    roots = []
    if config["backtest"].get("skill_root"):
        roots.append(Path(config["backtest"]["skill_root"]).expanduser().resolve())
    if os.environ.get("FACTOR_BACKTEST_SKILL_ROOT"):
        roots.append(Path(os.environ["FACTOR_BACKTEST_SKILL_ROOT"]).expanduser().resolve())
    skill_root = Path(__file__).resolve().parents[2]
    roots.extend([skill_root.parent / "skill-factor-backtest", Path.home() / ".codex" / "skills" / "skill-factor-backtest"])
    for root in roots:
        entrypoint = root / BACKTEST_ENTRYPOINT
        if entrypoint.is_file():
            return entrypoint
    checked = ", ".join(str(root / BACKTEST_ENTRYPOINT) for root in roots)
    raise FileNotFoundError(f"Could not locate factor-backtest public CLI. Checked: {checked}")


def build_backtest_command(
    config: dict[str, Any], signal_path: Path, output_dir: Path,
    start: str, end: str, savemode: int, report: bool = False,
) -> list[str]:
    backtest = config["backtest"]
    command = [
        str(backtest.get("python_executable") or sys.executable),
        str(resolve_backtest_entrypoint(config)),
        "--input-file", str(signal_path),
        "--factor-column", SIGNAL_COLUMN,
        "--data-root", str(Path(config["data"]["market_data_root"]).resolve()),
        "--output-dir", str(output_dir),
        "--timespan", str(_yyyymmdd(start)), str(_yyyymmdd(end)),
        "--strategy", str(backtest.get("strategy", "long_only_equal_weight")),
        "--savemode", str(int(savemode)),
        "--init-cash", str(float(backtest.get("init_cash", 1e8))),
    ]
    for key, value in backtest.get("overrides", {}).items():
        command.extend(["--override", f"{key}={value}"])
    if backtest.get("reverse", False):
        command.append("--reverse")
    if report:
        command.append("--report")
    return command


def write_signal(frame: pd.DataFrame, path: Path) -> None:
    required = ["date", "ticker", SIGNAL_COLUMN]
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ValueError(f"Signal frame is missing: {missing}")
    output = frame.loc[:, required].copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y%m%d").astype("int64")
    output["ticker"] = pd.to_numeric(output["ticker"], errors="raise").astype("int64")
    output[SIGNAL_COLUMN] = pd.to_numeric(output[SIGNAL_COLUMN], errors="coerce")
    if output.empty or not np.isfinite(output[SIGNAL_COLUMN]).all():
        raise ValueError("Signal predictions must be non-empty and finite")
    if output.duplicated(["date", "ticker"]).any():
        raise ValueError("Signal contains duplicate (date,ticker) rows")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    output.sort_values(["date", "ticker"], kind="stable").to_parquet(temporary, index=False)
    os.replace(temporary, path)


class BacktestRunner:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(
        self, signal_path: Path, output_dir: Path, start: str, end: str,
        savemode: int, report: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        command = build_backtest_command(self.config, signal_path, output_dir, start, end, savemode, report)
        thread_count = int(self.config.get("runtime", {}).get("backtest_threads", 1))
        thread_limits = {
            name: str(thread_count)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        }
        environment = os.environ.copy()
        environment.update(thread_limits)
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True, env=environment
        )
        invocation = {
            "command": command,
            "returncode": completed.returncode,
            "thread_limits": thread_limits,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            raise RuntimeError(f"FactorBacktest failed with exit code {completed.returncode}: {completed.stderr[-2000:]}")
        metrics = parse_backtest_metrics(output_dir, float(self.config["backtest"].get("init_cash", 1e8)))
        return metrics, invocation


@contextmanager
def _candidate_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def candidate_id(spec: CandidateSpec, config: dict[str, Any]) -> str:
    normalized = spec.normalized()
    return fingerprint({
        "schema_version": 3,
        "evaluator_version": candidate_evaluator_version(config),
        "factors": list(normalized.factors),
        "config_fingerprint": config_fingerprint(config),
        "cache_fingerprint": cache_fingerprint(config),
    })


def _result_from_payload(payload: dict[str, Any], candidate_dir: Path, cached: bool) -> EvaluationResult:
    return EvaluationResult(
        candidate_id=str(payload["candidate_id"]), factors=tuple(payload["factors"]),
        metrics=payload["metrics"], candidate_dir=candidate_dir, cached=cached,
    )


class CandidateEvaluator:
    def __init__(self, config: dict[str, Any], run_dir: str | Path):
        self.config = config
        self.run_dir = Path(run_dir).resolve()
        self.store = CachedFeatureStore(config, oos=False)
        self.evaluator_version = candidate_evaluator_version(config)
        self._preloaded_train: pd.DataFrame | None = None
        self._preloaded_valid: pd.DataFrame | None = None
        if bool(config.get("runtime", {}).get("preload_features", False)):
            split = config["split"]
            manifest = self.store.manifest
            factors = sorted(
                set(manifest["initial_factors"]).union(manifest["external_factors"])
            )
            self._preloaded_train = self.store.load_supervised(
                factors, split["train_start"], split["train_end"]
            )
            self._preloaded_valid = self.store.load_supervised(
                factors, split["valid_start"], split["valid_end"]
            )

    def _select_preloaded(self, frame: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
        return frame.loc[:, ["date", "ticker", *factors, "target"]]

    def _load_candidate_frames(
        self, factors: list[str], split: dict[str, Any]
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._preloaded_train is not None and self._preloaded_valid is not None:
            return (
                self._select_preloaded(self._preloaded_train, factors),
                self._select_preloaded(self._preloaded_valid, factors),
            )
        return (
            self.store.load_supervised(
                factors, split["train_start"], split["train_end"]
            ),
            self.store.load_supervised(
                factors, split["valid_start"], split["valid_end"]
            ),
        )

    def evaluate(self, spec: CandidateSpec) -> EvaluationResult:
        normalized = spec.normalized()
        if not normalized.factors:
            raise ValueError("Candidate factor set must not be empty")
        identifier = candidate_id(normalized, self.config)
        candidate_dir = self.run_dir / "candidates" / identifier
        result_path = candidate_dir / "result.json"
        with _candidate_lock(candidate_dir / ".lock"):
            if result_path.is_file():
                return _result_from_payload(read_json(result_path), candidate_dir, cached=True)
            candidate_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(candidate_dir / "status.json", {"status": "running", "candidate_id": identifier, "started_at": _utc_now()})
            try:
                split = self.config["split"]
                factors = list(normalized.factors)
                train, valid = self._load_candidate_frames(factors, split)
                if train.empty or valid.empty:
                    raise ValueError("Candidate has no aligned training or validation rows")
                model = LightGBMModel(self.config["model"]).fit(train[factors], train["target"], train["date"])
                scored = valid.loc[:, ["date", "ticker", "target"]].assign(
                    prediction=model.predict(valid[factors])
                )
                metrics = calculate_prediction_metrics(scored)
                if self.config["selection"]["primary_metric"] == "sharpe":
                    signal_path = candidate_dir / "validation_signal.parquet"
                    backtest_dir = candidate_dir / "validation_backtest"
                    write_signal(scored, signal_path)
                    backtest_metrics, invocation = BacktestRunner(self.config).run(
                        signal_path,
                        backtest_dir,
                        split["valid_start"],
                        split["valid_end"],
                        int(self.config["backtest"].get("search_savemode", 2)),
                    )
                    metrics.update({
                        "sharpe": backtest_metrics["sharpe"],
                        "total_return": backtest_metrics["total_return"],
                        "hedged_total_return": backtest_metrics["hedged_total_return"],
                        "max_drawdown": backtest_metrics["max_drawdown"],
                        "monthly_hedged_returns": backtest_metrics["monthly_hedged_returns"],
                        "backtest_mean_rank_ic": backtest_metrics["mean_ic"],
                        "backtest_rank_icir": backtest_metrics["icir"],
                        "backtest_observation_count": backtest_metrics["observation_count"],
                    })
                    atomic_write_json(
                        candidate_dir / "backtest_invocation.json",
                        {
                            "command": invocation["command"],
                            "returncode": invocation["returncode"],
                            "thread_limits": invocation["thread_limits"],
                        },
                    )
                    atomic_write_text(
                        candidate_dir / "backtest_stdout.log", invocation["stdout"]
                    )
                    atomic_write_text(
                        candidate_dir / "backtest_stderr.log", invocation["stderr"]
                    )
                payload = {
                    "schema_version": 3, "evaluator_version": self.evaluator_version,
                    "status": "complete", "candidate_id": identifier,
                    "spec": normalized.to_dict(), "factors": factors, "factor_count": len(factors),
                    "metrics": metrics, "train_rows": int(len(train)), "validation_rows": int(len(valid)),
                    "validation_period": [split["valid_start"], split["valid_end"]],
                    "config_fingerprint": config_fingerprint(self.config),
                    "cache_fingerprint": cache_fingerprint(self.config), "completed_at": _utc_now(),
                }
                atomic_write_json(result_path, payload)
                atomic_write_json(candidate_dir / "status.json", {"status": "complete", "candidate_id": identifier, "completed_at": payload["completed_at"]})
                return _result_from_payload(payload, candidate_dir, cached=False)
            except BaseException as exc:
                atomic_write_json(candidate_dir / "status.json", {
                    "status": "failed", "candidate_id": identifier, "failed_at": _utc_now(),
                    "error_type": type(exc).__name__, "error": str(exc),
                })
                raise
