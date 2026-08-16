from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from .config import cache_dir, cache_fingerprint
from .labels import build_forward_target, load_trade_price_matrix, normalize_dates, normalize_tickers, target_to_long
from .preprocess import preprocess_cross_sectional, select_by_coverage
from .serialization import atomic_write_json, fingerprint, read_json, sha256_file, source_descriptor


KEY_COLUMNS = ("date", "ticker")


def oos_cache_dir(config: dict[str, Any], factors: Iterable[str]) -> Path:
    selected = sorted(set(str(name) for name in factors))
    return cache_dir(config) / f"oos_{fingerprint(selected)[:16]}"


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".parquet", dir=path.parent)
    os.close(fd)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _years(start: str, end: str) -> list[int]:
    return list(range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1))


def _year_bounds(year: int, start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    return max(pd.Timestamp(start), pd.Timestamp(year, 1, 1)), min(pd.Timestamp(end), pd.Timestamp(year, 12, 31))


class FeatureBank:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"Feature bank does not exist: {self.path}")
        self.dataset = ds.dataset(self.path, format="parquet")
        missing = sorted(set(KEY_COLUMNS).difference(self.dataset.schema.names))
        if missing:
            raise ValueError(f"Feature bank is missing key columns: {missing}")

    @property
    def feature_names(self) -> list[str]:
        return sorted(name for name in self.dataset.schema.names if name not in KEY_COLUMNS)

    def select_features(self, requested: Iterable[str] | None) -> list[str]:
        available = self.feature_names
        selected = available if requested is None else sorted(set(str(name) for name in requested))
        missing = sorted(set(selected).difference(available))
        if missing:
            raise ValueError(f"Feature bank does not contain requested factors: {missing[:20]}")
        if not selected:
            raise ValueError("Feature bank contains no selected factor columns")
        return selected

    def _filter(self, start: pd.Timestamp, end: pd.Timestamp):
        field_type = self.dataset.schema.field("date").type
        expression = ds.field("date")
        if pa.types.is_integer(field_type):
            return (expression >= int(start.strftime("%Y%m%d"))) & (expression <= int(end.strftime("%Y%m%d")))
        if pa.types.is_timestamp(field_type):
            return (expression >= start.to_pydatetime()) & (expression <= end.to_pydatetime())
        if pa.types.is_date32(field_type) or pa.types.is_date64(field_type):
            return (expression >= start.date()) & (expression <= end.date())
        if pa.types.is_string(field_type) or pa.types.is_large_string(field_type):
            compact = (expression >= start.strftime("%Y%m%d")) & (expression <= end.strftime("%Y%m%d"))
            iso = (expression >= start.strftime("%Y-%m-%d")) & (
                expression <= end.strftime("%Y-%m-%d")
            )
            return compact | iso
        return None

    def read(self, factors: Iterable[str], start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DataFrame:
        start_date, end_date = pd.Timestamp(start), pd.Timestamp(end)
        names = list(factors)
        missing = sorted(set(names).difference(self.feature_names))
        if missing:
            raise ValueError(f"Unknown factors requested from {self.path}: {missing[:20]}")
        table = self.dataset.to_table(columns=[*KEY_COLUMNS, *names], filter=self._filter(start_date, end_date))
        frame = table.to_pandas()
        if frame.empty:
            return pd.DataFrame(columns=[*KEY_COLUMNS, *names])
        frame["date"] = normalize_dates(frame["date"])
        frame["ticker"] = normalize_tickers(frame["ticker"], f"{self.path} ticker").to_numpy()
        frame = frame.loc[(frame["date"] >= start_date) & (frame["date"] <= end_date)].copy()
        for name in names:
            raw_present = frame[name].notna()
            numeric = pd.to_numeric(frame[name], errors="coerce")
            if (raw_present & numeric.isna()).any():
                raise ValueError(f"Factor {name} contains non-numeric values")
            frame[name] = numeric.replace([np.inf, -np.inf], np.nan)
        duplicate = frame.duplicated(list(KEY_COLUMNS), keep=False)
        if duplicate.any():
            examples = frame.loc[duplicate, list(KEY_COLUMNS)].head(5).to_dict("records")
            raise ValueError(f"Feature bank contains duplicate (date,ticker) rows: {examples}")
        return frame.sort_values(list(KEY_COLUMNS), kind="stable").reset_index(drop=True)


def inspect_factor_banks(config: dict[str, Any]) -> dict[str, Any]:
    data = config["data"]
    initial_bank = FeatureBank(data["factor_bank"])
    initial = initial_bank.select_features(data.get("initial_factors"))
    external: list[str] = []
    external_bank = None
    if data.get("external_factor_bank"):
        external_bank = FeatureBank(data["external_factor_bank"])
        external = external_bank.select_features(data.get("external_factors"))
        overlap = sorted(set(initial).intersection(external))
        if overlap:
            raise ValueError(f"Initial and external factor names overlap: {overlap[:20]}")
    return {"initial_bank": initial_bank, "initial_factors": initial, "external_bank": external_bank, "external_factors": external}


def _coverage_for_period(bank: FeatureBank, factors: list[str], start: str, end: str) -> tuple[pd.Series, int]:
    counts = pd.Series(0, index=factors, dtype="int64")
    total = 0
    for year in _years(start, end):
        year_start, year_end = _year_bounds(year, start, end)
        frame = bank.read(factors, year_start, year_end)
        counts = counts.add(frame[factors].notna().sum().astype("int64"), fill_value=0).astype("int64")
        total += len(frame)
    return counts, total


def _write_feature_years(
    bank: FeatureBank,
    factors: list[str],
    destination: Path,
    start: str,
    end: str,
    preprocess_config: dict,
) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for year in _years(start, end):
        year_start, year_end = _year_bounds(year, start, end)
        processed = preprocess_cross_sectional(bank.read(factors, year_start, year_end), factors, preprocess_config)
        path = destination / f"year={year}.parquet"
        _atomic_parquet(processed, path)
        files[str(year)] = {"path": str(path), "sha256": sha256_file(path), "rows": int(len(processed))}
    return files


def _write_target_years(
    target: pd.DataFrame,
    destination: Path,
    start: str,
    end: str,
    min_assets: int,
) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for year in _years(start, end):
        year_start, year_end = _year_bounds(year, start, end)
        long = target_to_long(target, str(year_start.date()), str(year_end.date()))
        counts = long.groupby("date", observed=True)["target"].transform("count")
        long = long.loc[counts >= min_assets].reset_index(drop=True)
        path = destination / f"year={year}.parquet"
        _atomic_parquet(long, path)
        files[str(year)] = {"path": str(path), "sha256": sha256_file(path), "rows": int(len(long))}
    return files


def prepare_development_cache(config: dict[str, Any]) -> Path:
    destination = cache_dir(config)
    manifest_path = destination / "cache_manifest.json"
    expected_fingerprint = cache_fingerprint(config)
    if manifest_path.is_file():
        existing = read_json(manifest_path)
        if existing.get("cache_fingerprint") == expected_fingerprint:
            return manifest_path
        raise RuntimeError(f"Existing cache fingerprint mismatch: {manifest_path}")

    inspected = inspect_factor_banks(config)
    split, preprocess = config["split"], config["preprocess"]
    threshold = float(preprocess["min_factor_coverage"])
    initial_counts, initial_total = _coverage_for_period(
        inspected["initial_bank"], inspected["initial_factors"], split["train_start"], split["train_end"]
    )
    initial, initial_coverage = select_by_coverage(initial_counts, initial_total, threshold)
    external: list[str] = []
    external_coverage: dict[str, float] = {}
    if inspected["external_bank"] is not None:
        external_counts, external_total = _coverage_for_period(
            inspected["external_bank"], inspected["external_factors"], split["train_start"], split["train_end"]
        )
        external, external_coverage = select_by_coverage(external_counts, external_total, threshold)

    initial_files = _write_feature_years(
        inspected["initial_bank"], initial, destination / "development" / "initial",
        split["train_start"], split["valid_end"], preprocess,
    )
    external_files: dict[str, dict[str, Any]] = {}
    if external:
        external_files = _write_feature_years(
            inspected["external_bank"], external, destination / "development" / "external",
            split["train_start"], split["valid_end"], preprocess,
        )
    prices = load_trade_price_matrix(config["data"]["market_data_root"])
    target = build_forward_target(prices, int(config["label"]["execution_lag"]), int(config["label"]["horizon"]))
    target_files = _write_target_years(
        target, destination / "development" / "target", split["train_start"], split["valid_end"],
        int(preprocess["min_assets_per_date"]),
    )
    factor_sources = {name: "initial" for name in initial} | {name: "external" for name in external}
    manifest = {
        "schema_version": 1,
        "cache_fingerprint": expected_fingerprint,
        "development_only": True,
        "sources": {
            "initial": source_descriptor(config["data"]["factor_bank"]),
            "external": source_descriptor(config["data"]["external_factor_bank"])
            if config["data"].get("external_factor_bank") else None,
            "market_data_root": str(Path(config["data"]["market_data_root"]).resolve()),
        },
        "initial_factors": initial,
        "external_factors": external,
        "factor_sources": factor_sources,
        "coverage": {"initial": initial_coverage, "external": external_coverage},
        "files": {"initial": initial_files, "external": external_files, "target": target_files},
        "split": {key: split[key] for key in ("train_start", "train_end", "valid_start", "valid_end")},
    }
    atomic_write_json(manifest_path, manifest)
    return manifest_path


def prepare_oos_cache(config: dict[str, Any], frozen_factors: Iterable[str]) -> Path:
    selected = sorted(set(str(name) for name in frozen_factors))
    destination = oos_cache_dir(config, selected)
    manifest_path = destination / "cache_manifest.json"
    if manifest_path.is_file():
        existing = read_json(manifest_path)
        if existing.get("cache_fingerprint") == cache_fingerprint(config) and existing.get("factors") == selected:
            return manifest_path
        raise RuntimeError("Existing OOS cache belongs to another configuration or frozen factor set")
    development = load_cache_manifest(config)
    unknown = sorted(set(selected).difference(development["factor_sources"]))
    if unknown:
        raise ValueError(f"Frozen selection contains factors outside the development cache: {unknown}")
    inspected = inspect_factor_banks(config)
    split, preprocess = config["split"], config["preprocess"]
    initial = [name for name in selected if development["factor_sources"][name] == "initial"]
    external = [name for name in selected if development["factor_sources"][name] == "external"]
    initial_files = _write_feature_years(
        inspected["initial_bank"], initial, destination / "oos" / "initial",
        split["oos_start"], split["oos_end"], preprocess,
    ) if initial else {}
    external_files = _write_feature_years(
        inspected["external_bank"], external, destination / "oos" / "external",
        split["oos_start"], split["oos_end"], preprocess,
    ) if external and inspected["external_bank"] is not None else {}
    prices = load_trade_price_matrix(config["data"]["market_data_root"])
    target = build_forward_target(prices, int(config["label"]["execution_lag"]), int(config["label"]["horizon"]))
    target_files = _write_target_years(
        target, destination / "oos" / "target", split["oos_start"], split["oos_end"],
        int(preprocess["min_assets_per_date"]),
    )
    manifest = {
        "schema_version": 1,
        "cache_fingerprint": cache_fingerprint(config),
        "factors": selected,
        "factor_sources": {name: development["factor_sources"][name] for name in selected},
        "files": {"initial": initial_files, "external": external_files, "target": target_files},
        "split": {"oos_start": split["oos_start"], "oos_end": split["oos_end"]},
    }
    atomic_write_json(manifest_path, manifest)
    return manifest_path


def load_cache_manifest(config: dict[str, Any]) -> dict[str, Any]:
    path = cache_dir(config) / "cache_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Development cache is missing: {path}. Run prepare-cache first.")
    manifest = read_json(path)
    if manifest.get("cache_fingerprint") != cache_fingerprint(config):
        raise RuntimeError("Development cache fingerprint does not match the resolved configuration")
    return manifest


class CachedFeatureStore:
    def __init__(
        self, config: dict[str, Any], oos: bool = False, oos_factors: Iterable[str] | None = None
    ):
        if oos and oos_factors is None:
            raise ValueError("OOS feature store requires the frozen factor union")
        path = (
            oos_cache_dir(config, oos_factors or []) / "cache_manifest.json"
            if oos
            else cache_dir(config) / "cache_manifest.json"
        )
        if not path.is_file():
            raise FileNotFoundError(f"Cache manifest does not exist: {path}")
        self.manifest = read_json(path)
        if self.manifest.get("cache_fingerprint") != cache_fingerprint(config):
            raise RuntimeError("Cache manifest fingerprint mismatch")

    def _read_years(self, source: str, columns: list[str], start: str, end: str) -> pd.DataFrame:
        parts = []
        for year in _years(start, end):
            entry = self.manifest["files"].get(source, {}).get(str(year))
            if entry is not None:
                parts.append(pd.read_parquet(entry["path"], columns=[*KEY_COLUMNS, *columns]))
        if not parts:
            return pd.DataFrame(columns=[*KEY_COLUMNS, *columns])
        frame = pd.concat(parts, ignore_index=True)
        frame["date"] = pd.to_datetime(frame["date"])
        mask = (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))
        return frame.loc[mask].sort_values(list(KEY_COLUMNS), kind="stable").reset_index(drop=True)

    def load_features(self, factors: Iterable[str], start: str, end: str) -> pd.DataFrame:
        names = sorted(set(str(name) for name in factors))
        sources = self.manifest["factor_sources"]
        unknown = sorted(set(names).difference(sources))
        if unknown:
            raise ValueError(f"Factors are absent from the cache: {unknown}")
        frames = []
        for source in ("initial", "external"):
            selected = [name for name in names if sources[name] == source]
            if selected:
                frames.append(self._read_years(source, selected, start, end))
        if not frames:
            raise ValueError("A candidate must contain at least one factor")
        result = frames[0]
        for frame in frames[1:]:
            result = result.merge(frame, on=list(KEY_COLUMNS), how="inner", validate="one_to_one")
        return result.loc[:, [*KEY_COLUMNS, *names]]

    def load_target(self, start: str, end: str) -> pd.DataFrame:
        return self._read_years("target", ["target"], start, end)

    def load_supervised(self, factors: Iterable[str], start: str, end: str) -> pd.DataFrame:
        features = self.load_features(factors, start, end)
        target = self.load_target(start, end)
        merged = features.merge(target, on=list(KEY_COLUMNS), how="inner", validate="one_to_one")
        return merged.loc[np.isfinite(merged["target"])].reset_index(drop=True)
