"""Durable, credential-free lifecycle records for production BUILD runs."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunManifest:
    """Atomically persist stages so a long Panda run is inspectable and resumable."""

    def __init__(self, directory: str | Path, *, build_id: str, as_of_date: str, start_date: str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_id = f"{build_id}-{as_of_date}-{uuid4().hex[:12]}"
        self.path = self.directory / f"{self.run_id}.json"
        self.data: dict[str, Any] = {
            "run_id": self.run_id,
            "build_id": build_id,
            "as_of_date": as_of_date,
            "start_date": start_date,
            "started_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "stages": [],
            "alerts": [],
        }
        self._write()

    def stage(self, name: str, metadata: Mapping[str, Any] | None = None) -> None:
        self.data["stages"].append({"stage": name, "at": utc_now(), **dict(metadata or {})})
        self._write()

    def finish(self, *, status: str, metadata: Mapping[str, Any] | None = None) -> None:
        self.data["status"] = status
        self.data["finished_at"] = utc_now()
        if metadata:
            self.data.update(dict(metadata))
        self._write()

    def _write(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(5):
            try:
                temporary.replace(self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))


def latest_manifest(directory: str | Path) -> dict[str, Any] | None:
    root = Path(directory)
    manifests: list[tuple[str, dict[str, Any]]] = []
    for path in root.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(item, Mapping) or not all(
            key in item for key in ("run_id", "build_id", "started_at", "status")
        ):
            continue
        stages = item.get("stages")
        if not isinstance(stages, list) or not any(
            isinstance(stage, Mapping) and stage.get("stage") == "scan_started"
            for stage in stages
        ):
            continue
        manifests.append((str(item["started_at"]), dict(item)))
    if not manifests:
        return None
    return max(manifests, key=lambda pair: pair[0])[1]
