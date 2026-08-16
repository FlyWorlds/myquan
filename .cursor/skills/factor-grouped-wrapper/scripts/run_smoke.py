#!/usr/bin/env python3
"""Run the synthetic development workflow through freeze, without OOS backtesting."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from make_smoke_fixture import SMOKE_CONFIG, build_fixture


SKILL_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = SKILL_ROOT / "scripts" / "run_factor_grouped_wrapper.py"


def _run(command: str, *extra: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "--config",
            str(SMOKE_CONFIG),
            command,
            *extra,
        ],
        cwd=SKILL_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Smoke stage {command} failed: {detail}")
    return json.loads(completed.stdout)


def main() -> int:
    try:
        fixture = build_fixture()
        validated = _run("validate")
        cached = _run("prepare-cache")
        backward = _run("search-backward")
        run_dir = str(backward["run_dir"])
        forward = _run("search-forward", "--run-dir", run_dir)
        frozen = _run("freeze", "--run-dir", run_dir)
        print(
            json.dumps(
                {
                    "status": "smoke_complete",
                    "oos_backtest_executed": False,
                    "fixture": fixture,
                    "stages": [
                        validated["status"],
                        cached["status"],
                        backward["status"],
                        forward["status"],
                        frozen["status"],
                    ],
                    "run_dir": run_dir,
                    "snapshot_names": [
                        snapshot["name"] for snapshot in frozen["selection"]["snapshots"]
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    except (FileExistsError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
