from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


script = Path(__file__).resolve().parents[1] / "scripts" / "audit_rolls.py"
completed = subprocess.run(
    [sys.executable, "-B", str(script), "--demo", "--adjustment-method", "difference"],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
report = json.loads(completed.stdout)
assert report["assumptions"]["adjustment_method"] == "difference"
assert report["domain_result"]["roll_events"]
assert "ratio_adjustment" in report["domain_result"]["roll_events"][0]
print("futures-roll-auditor smoke: PASS")
