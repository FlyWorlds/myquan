"""P4 single-entry production job for Windows Task Scheduler or manual runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .build import run
    from .core import DATA_VERSION
    from .evidence_queue import review_directory
    from .panda_adapter import clear_process_credentials, configure_from_environment
    from .production_dashboard import build as build_dashboard
except ImportError:
    from build import run
    from core import DATA_VERSION
    from evidence_queue import review_directory
    from panda_adapter import clear_process_credentials, configure_from_environment
    from production_dashboard import build as build_dashboard

ROOT = Path(__file__).resolve().parents[1]


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def _execute_impl(
    *,
    as_of_date: str,
    start_date: str | None = None,
    evidence_dir: str | Path | None = None,
    production_path: str | Path | None = None,
    operations_dir: str | Path | None = None,
    dashboard_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the production chain; credentials must already be configured in process."""
    production = Path(production_path or ROOT / "生产产物" / "数据库.parquet")
    operations = Path(operations_dir or ROOT / "validation" / "operations")
    dashboard = Path(dashboard_path or ROOT / "validation" / "production_dashboard.html")
    start = start_date or (datetime.strptime(as_of_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
    config: dict[str, Any] = {
        "materialize": True,
        "output_path": production,
        "manifest_dir": operations,
        "checkpoint_dir": operations / "checkpoints",
    }
    if evidence_dir is not None:
        config["evidence_dir"] = Path(evidence_dir)
    result = run({"as_of_date": as_of_date, "start_date": start}, config)
    evidence_report = None
    if evidence_dir is not None:
        evidence_report = review_directory(
            evidence_dir,
            as_of_date=as_of_date,
            output_path=operations / "evidence_queue.json",
        )
    build_dashboard(dashboard, production_path=production, operations_path=operations)
    health = json.loads((operations / "health_latest.json").read_text(encoding="utf-8"))
    summary = {
        "status": "completed",
        "as_of_date": as_of_date,
        "data_version": DATA_VERSION,
        "production_path": str(production.resolve()),
        "dashboard_path": str(dashboard.resolve()),
        "run_manifest_path": result.get("run_manifest_path"),
        "record_count": result.get("summary", {}).get("total"),
        "health_status": health.get("status"),
        "alert_count": len(health.get("alerts", [])),
        "evidence_ready_count": None if evidence_report is None else evidence_report.get("ready_count"),
    }
    _atomic_json(operations / "job_latest.json", summary)
    return summary


def execute(
    *,
    as_of_date: str,
    start_date: str | None = None,
    evidence_dir: str | Path | None = None,
    production_path: str | Path | None = None,
    operations_dir: str | Path | None = None,
    dashboard_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the job and leave a credential-free terminal record on failure."""
    operations = Path(operations_dir or ROOT / "validation" / "operations")
    try:
        return _execute_impl(
            as_of_date=as_of_date,
            start_date=start_date,
            evidence_dir=evidence_dir,
            production_path=production_path,
            operations_dir=operations,
            dashboard_path=dashboard_path,
        )
    except Exception as exc:
        _atomic_json(
            operations / "job_latest.json",
            {
                "status": "failed",
                "as_of_date": as_of_date,
                "data_version": DATA_VERSION,
                "error_type": type(exc).__name__,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Q51 Klarman production job")
    parser.add_argument("--as-of", required=True, dest="as_of_date")
    parser.add_argument("--start", dest="start_date")
    parser.add_argument("--evidence-dir")
    args = parser.parse_args()
    try:
        configure_from_environment(clear=True)
        result = execute(
            as_of_date=args.as_of_date,
            start_date=args.start_date,
            evidence_dir=args.evidence_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        clear_process_credentials()


if __name__ == "__main__":
    main()
