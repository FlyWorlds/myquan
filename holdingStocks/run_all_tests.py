"""One-command test runner for watch/strategy work.

Runs the default unittest regression first, then the repository-wide pytest
suite when pytest is installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--skip-pytest-if-missing",
        action="store_true",
        help="Return success when pytest is not installed after default regression passes.",
    )
    ap.add_argument(
        "--default-only",
        action="store_true",
        help="Only run holdingStocks/run_regression_tests.py.",
    )
    args = ap.parse_args()

    rc = _run([sys.executable, "holdingStocks/run_regression_tests.py"])
    if rc != 0 or args.default_only:
        return rc

    if importlib.util.find_spec("pytest") is None:
        msg = (
            "pytest is not installed. Install dev deps with:\n"
            "  python3 -m pip install -r requirements.txt -r requirements-dev.txt"
        )
        print(msg, file=sys.stderr)
        return 0 if args.skip_pytest_if_missing else 2

    return _run([sys.executable, "-m", "pytest", "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
