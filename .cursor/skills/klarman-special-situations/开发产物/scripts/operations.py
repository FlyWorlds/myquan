"""P4 health report over production artifacts and durable run manifests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .panda_adapter import inspect_production
    from .run_manifest import latest_manifest
except ImportError:
    from panda_adapter import inspect_production
    from run_manifest import latest_manifest


def health_report(
    production_path: str | Path,
    *,
    data_version: str,
    manifest_dir: str | Path,
    max_runtime_minutes: int = 30,
    max_staleness_hours: int = 72,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    artifact = inspect_production(production_path, expected_data_version=data_version)
    alerts: list[dict[str, str]] = []
    if artifact["status"] != "current":
        alerts.append({"severity": "critical", "code": "artifact_not_current", "message": artifact["status"]})
    try:
        frame = pd.read_parquet(production_path) if Path(production_path).exists() else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    if frame.empty:
        current = pd.DataFrame()
    elif "data_version" not in frame:
        current = frame.iloc[0:0].copy()
    else:
        current = frame.loc[frame["data_version"].astype(str) == data_version].copy()
    if artifact.get("current_row_count") == 0:
        alerts.append({"severity": "critical", "code": "empty_current_partition", "message": data_version})
    if artifact.get("invalid_json"):
        alerts.append({"severity": "critical", "code": "invalid_result_json", "message": str(artifact["invalid_json"])})
    if artifact.get("duplicate_keys"):
        alerts.append({"severity": "critical", "code": "duplicate_production_key", "message": str(artifact["duplicate_keys"])})
    if artifact.get("scope_types") and "all_a_share" not in artifact["scope_types"]:
        alerts.append({"severity": "critical", "code": "scope_not_full_market", "message": ",".join(artifact["scope_types"])})
    update_times = pd.to_datetime(current.get("update_time", pd.Series(dtype=str)), utc=True, errors="coerce").dropna()
    latest_update = update_times.max() if not update_times.empty else None
    if latest_update is not None:
        age_hours = (datetime.now(timezone.utc) - latest_update.to_pydatetime()).total_seconds() / 3600
        if age_hours > max_staleness_hours:
            alerts.append({"severity": "critical", "code": "artifact_stale", "message": f"{age_hours:.1f}h"})
    else:
        age_hours = None
    gaps: list[str] = []
    for _, row in current.loc[current.get("result_type", pd.Series(dtype=str)) == "coverage_gap"].iterrows():
        try:
            gaps.append(str(json.loads(row["result_json"]).get("api")))
        except Exception:
            gaps.append("unparseable_gap")
    for api in sorted(set(gaps)):
        alerts.append({"severity": "warning", "code": "coverage_gap", "message": api})
    manifest = latest_manifest(manifest_dir)
    if manifest and manifest.get("status") == "failed":
        alerts.append({"severity": "critical", "code": "latest_run_failed", "message": str(manifest.get("error_type") or "unknown")})
    elif manifest and manifest.get("status") == "running":
        alerts.append({"severity": "warning", "code": "latest_run_incomplete", "message": str(manifest.get("run_id"))})
    if manifest and manifest.get("started_at") and manifest.get("finished_at"):
        runtime = (datetime.fromisoformat(manifest["finished_at"]) - datetime.fromisoformat(manifest["started_at"])).total_seconds() / 60
        if runtime > max_runtime_minutes:
            alerts.append({"severity": "warning", "code": "runtime_sla", "message": f"{runtime:.1f}m"})
    else:
        runtime = None
        alerts.append({"severity": "warning", "code": "manifest_missing", "message": "no completed run manifest"})
    report = {
        "artifact": artifact,
        "manifest": manifest,
        "runtime_minutes": runtime,
        "artifact_age_hours": age_hours,
        "coverage_gaps": sorted(set(gaps)),
        "alerts": alerts,
        "status": "critical" if any(item["severity"] == "critical" for item in alerts) else ("attention" if alerts else "healthy"),
    }
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(target)
    return report
