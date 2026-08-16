from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .serialization import fingerprint, source_descriptor


PATH_KEYS = {
    "factor_bank", "external_factor_bank", "market_data_root", "skill_root", "output_root", "cache_root"
}
REQUIRED_MARKET_FILES = (
    "calendar.parquet", "name_dict.parquet", "adjfactor.parquet", "pre_close.parquet",
    "trade_price.parquet", "balance_price.parquet", "open_price.parquet",
    "mask_isopen.parquet", "mask_isST.parquet",
)
PREDICTION_METRICS = {"mean_rank_ic", "rank_icir", "mean_ic", "icir"}
BACKTEST_METRICS = {"sharpe"}
SUPPORTED_METRICS = PREDICTION_METRICS | BACKTEST_METRICS
EXECUTION_RUNTIME_KEYS = {
    "candidate_workers", "seed_workers", "backtest_threads", "preload_features"
}


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Configuration root must be a mapping")
    resolved = deepcopy(payload)
    for section in resolved.values():
        if not isinstance(section, dict):
            continue
        for key, value in list(section.items()):
            if key in PATH_KEYS and value not in (None, ""):
                candidate = Path(str(value)).expanduser()
                section[key] = str(candidate.resolve() if candidate.is_absolute() else (config_path.parent / candidate).resolve())
    resolved["_config_path"] = str(config_path)
    return resolved


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if not key.startswith("_")}


def config_fingerprint(config: dict[str, Any]) -> str:
    resolved = deepcopy(public_config(config))
    runtime = resolved.get("runtime")
    if isinstance(runtime, dict):
        for key in EXECUTION_RUNTIME_KEYS:
            runtime.pop(key, None)
    return fingerprint(resolved)


def cache_fingerprint(config: dict[str, Any]) -> str:
    data = config["data"]
    payload: dict[str, Any] = {
        "factor_bank": source_descriptor(data["factor_bank"]),
        "split": config["split"],
        "label": config["label"],
        "preprocess": config["preprocess"],
        "initial_factors": data.get("initial_factors"),
    }
    if data.get("external_factor_bank"):
        payload["external_factor_bank"] = source_descriptor(data["external_factor_bank"])
        payload["external_factors"] = data.get("external_factors")
    return fingerprint(payload)


def cache_dir(config: dict[str, Any]) -> Path:
    return Path(config["runtime"]["cache_root"]) / f"cache_{cache_fingerprint(config)[:16]}"


def _require_sections(config: dict[str, Any]) -> None:
    required = ("data", "split", "label", "preprocess", "model", "grouping", "selection", "backtest", "runtime")
    missing = [name for name in required if name not in config]
    if missing:
        raise ValueError(f"Missing configuration sections: {missing}")


def validate_config(config: dict[str, Any], check_paths: bool = True) -> None:
    _require_sections(config)
    split = config["split"]
    required_dates = ("train_start", "train_end", "valid_start", "valid_end", "oos_start", "oos_end")
    missing_dates = [name for name in required_dates if split.get(name) is None]
    if missing_dates:
        raise ValueError(f"Missing split dates: {missing_dates}")
    train_start, train_end, valid_start, valid_end, oos_start, oos_end = (pd.Timestamp(split[name]) for name in required_dates)
    if not train_start <= train_end < valid_start <= valid_end < oos_start <= oos_end:
        raise ValueError("Expected non-overlapping Train < Validation < OOS date ranges")

    label = config["label"]
    if int(label.get("execution_lag", -1)) != 1 or int(label.get("horizon", -1)) != 1:
        raise ValueError("Version 1 requires label.execution_lag=1 and label.horizon=1")

    preprocess = config["preprocess"]
    coverage = float(preprocess["min_factor_coverage"])
    lower, upper = float(preprocess["winsor_lower"]), float(preprocess["winsor_upper"])
    if not 0.0 <= coverage <= 1.0:
        raise ValueError("preprocess.min_factor_coverage must be between zero and one")
    if not 0.0 <= lower < upper <= 1.0:
        raise ValueError("Expected 0 <= winsor_lower < winsor_upper <= 1")
    if int(preprocess["min_assets_per_date"]) < 1:
        raise ValueError("preprocess.min_assets_per_date must be positive")

    if config["model"].get("type") != "lgbm":
        raise ValueError("Version 1 supports model.type=lgbm only")
    if int(config["model"].get("n_jobs", 0)) < 1:
        raise ValueError("model.n_jobs must be positive")

    runtime = config["runtime"]
    for key in ("candidate_workers", "seed_workers", "backtest_threads"):
        if int(runtime.get(key, 1)) < 1:
            raise ValueError(f"runtime.{key} must be positive")
    if "preload_features" in runtime and not isinstance(runtime["preload_features"], bool):
        raise ValueError("runtime.preload_features must be boolean")

    seeds = config["grouping"].get("seeds", [])
    if not seeds or len(set(int(seed) for seed in seeds)) != len(seeds):
        raise ValueError("grouping.seeds must contain unique values")
    stages = config["grouping"].get("backward_stages", [])
    if not stages:
        raise ValueError("grouping.backward_stages must not be empty")
    names = [str(stage.get("name", "")) for stage in stages]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Every backward stage needs a unique non-empty name")
    for stage in stages:
        size_keys = [key for key in ("target_group_count", "group_size") if stage.get(key) is not None]
        if len(size_keys) != 1 or int(stage[size_keys[0]]) < 1:
            raise ValueError(f"Stage must set one positive grouping size: {stage}")

    selection = config["selection"]
    if float(selection.get("min_delta", 0.0)) < 0:
        raise ValueError("selection.min_delta must be non-negative")
    primary_metric = selection.get("primary_metric")
    if primary_metric not in SUPPORTED_METRICS:
        raise ValueError(f"Unsupported primary metric: {primary_metric}")
    if primary_metric in BACKTEST_METRICS:
        search_savemode = int(config["backtest"].get("search_savemode", 2))
        if search_savemode not in (2, 3):
            raise ValueError(
                "Sharpe selection requires backtest.search_savemode to be 2 or 3"
            )

    overrides = config["backtest"].get("overrides", {})
    if int(overrides.get("buy_sell_shift", 1)) != int(label["execution_lag"]):
        raise ValueError("backtest buy_sell_shift must equal label.execution_lag")

    if not check_paths:
        return
    factor_bank = Path(config["data"]["factor_bank"])
    market_root = Path(config["data"]["market_data_root"])
    if not factor_bank.exists():
        raise FileNotFoundError(f"Factor bank does not exist: {factor_bank}")
    if not market_root.is_dir():
        raise FileNotFoundError(f"Market data root does not exist: {market_root}")
    missing_market = [name for name in REQUIRED_MARKET_FILES if not (market_root / name).is_file()]
    benchmark = str(overrides.get("benchmark", "benchmark"))
    if not (market_root / "Benchmark" / f"{benchmark}.parquet").is_file():
        missing_market.append(f"Benchmark/{benchmark}.parquet")
    stock_pool = str(overrides.get("stock_pool", "whole"))
    if stock_pool != "whole" and not (market_root / "stock_pool" / f"{stock_pool}.parquet").is_file():
        missing_market.append(f"stock_pool/{stock_pool}.parquet")
    if missing_market:
        raise FileNotFoundError(f"Market data root is missing: {missing_market}")
    external = config["data"].get("external_factor_bank")
    if external and not Path(external).exists():
        raise FileNotFoundError(f"External factor bank does not exist: {external}")
