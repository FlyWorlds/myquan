from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import cache_fingerprint, config_fingerprint, public_config
from .feature_store import load_cache_manifest
from .serialization import atomic_write_json, atomic_write_text, read_json


LIFECYCLE_ORDER = {
    "CREATED": 0,
    "VALIDATED": 1,
    "CACHED": 2,
    "BACKWARD_DONE": 3,
    "FORWARD_DONE": 4,
    "FROZEN": 5,
    "OOS_EVALUATED": 6,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / f"run_{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = root / f"run_{stamp}_{suffix:02d}"
        suffix += 1
    return candidate


def create_or_resume_run(config: dict[str, Any], run_dir: str | Path | None = None) -> Path:
    run_path = (
        Path(run_dir).expanduser().resolve()
        if run_dir is not None
        else _new_run_dir(Path(config["runtime"]["output_root"]).resolve())
    )
    resolved_path = run_path / "config.resolved.yaml"
    if resolved_path.is_file():
        existing = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
        if config_fingerprint(existing) != config_fingerprint(config):
            raise RuntimeError("Resolved configuration does not match the existing run")
        resolved = public_config(config)
        if existing != resolved:
            atomic_write_text(
                resolved_path,
                yaml.safe_dump(resolved, sort_keys=False, allow_unicode=True),
            )
        return run_path
    if run_path.exists() and any(run_path.iterdir()):
        raise FileExistsError(f"Run directory is non-empty but has no resolved config: {run_path}")
    run_path.mkdir(parents=True, exist_ok=True)
    resolved = public_config(config)
    atomic_write_text(resolved_path, yaml.safe_dump(resolved, sort_keys=False, allow_unicode=True))
    manifest = load_cache_manifest(config)
    atomic_write_json(
        run_path / "data_manifest.json",
        {
            "schema_version": 1,
            "cache_fingerprint": cache_fingerprint(config),
            "cache_manifest": str(
                (
                    Path(config["runtime"]["cache_root"])
                    / f"cache_{cache_fingerprint(config)[:16]}"
                    / "cache_manifest.json"
                ).resolve()
            ),
            "sources": manifest["sources"],
            "initial_factors": manifest["initial_factors"],
            "external_factors": manifest["external_factors"],
        },
    )
    atomic_write_json(
        run_path / "lifecycle.json",
        {"state": "CACHED", "created_at": utc_now(), "updated_at": utc_now()},
    )
    return run_path


def lifecycle_state(run_dir: str | Path) -> str:
    path = Path(run_dir) / "lifecycle.json"
    return str(read_json(path)["state"]) if path.is_file() else "CREATED"


def update_lifecycle(run_dir: str | Path, state: str) -> None:
    if state not in LIFECYCLE_ORDER:
        raise ValueError(f"Unknown lifecycle state: {state}")
    run_path = Path(run_dir)
    current = lifecycle_state(run_path)
    if LIFECYCLE_ORDER[state] < LIFECYCLE_ORDER[current]:
        raise RuntimeError(f"Lifecycle cannot move backward from {current} to {state}")
    path = run_path / "lifecycle.json"
    payload = read_json(path) if path.is_file() else {"created_at": utc_now()}
    payload.update({"state": state, "updated_at": utc_now()})
    atomic_write_json(path, payload)
