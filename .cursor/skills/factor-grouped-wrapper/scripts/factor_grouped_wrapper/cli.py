from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .experiment import (
    backward_experiment,
    evaluate_oos_experiment,
    forward_experiment,
    freeze_experiment,
    prepare_cache_experiment,
    validate_experiment,
)
from .serialization import read_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resumable grouped wrapper selection for quantitative factor banks."
    )
    parser.add_argument("--config", type=Path, required=True, help="YAML configuration file")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate configuration and data contracts")
    subparsers.add_parser("prepare-cache", help="Build development-only yearly feature cache")
    backward = subparsers.add_parser("search-backward", help="Run or resume grouped backward elimination")
    backward.add_argument("--run-dir", type=Path)
    forward = subparsers.add_parser("search-forward", help="Run or resume optional grouped forward inclusion")
    forward.add_argument("--run-dir", type=Path)
    freeze = subparsers.add_parser("freeze", help="Freeze the selected development factor set")
    freeze.add_argument("--run-dir", type=Path, required=True)
    oos = subparsers.add_parser("evaluate-oos", help="Refit and evaluate every frozen OOS snapshot")
    oos.add_argument("--run-dir", type=Path, required=True)
    oos.add_argument("--force", action="store_true", help="Explicitly rerun an existing OOS evaluation")
    oos.add_argument("--report", action="store_true", help="Ask FactorBacktest to generate its PDF report")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = load_config(args.config)
        if args.command == "validate":
            payload = validate_experiment(config)
        elif args.command == "prepare-cache":
            path = prepare_cache_experiment(config)
            payload = {"status": "cached", "cache_manifest": str(path), "manifest": read_json(path)}
        elif args.command == "search-backward":
            run_dir, pool_a = backward_experiment(config, args.run_dir)
            payload = {
                "status": "backward_done",
                "run_dir": str(run_dir),
                "pool_a_selection": str(pool_a),
            }
            final_pool = run_dir / "final_factor_pool.json"
            if final_pool.is_file():
                payload["final_factor_pool"] = str(final_pool)
        elif args.command == "search-forward":
            run_dir, final_pool = forward_experiment(config, args.run_dir)
            payload = {
                "status": "forward_done",
                "run_dir": str(run_dir),
                "pool_b_expansion": str(run_dir / "pool_b_expansion.json"),
                "final_factor_pool": str(final_pool),
            }
        elif args.command == "freeze":
            path = freeze_experiment(config, args.run_dir)
            payload = {"status": "frozen", "frozen_selection": str(path), "selection": read_json(path)}
        elif args.command == "evaluate-oos":
            path = evaluate_oos_experiment(
                config, args.run_dir, force=bool(args.force), report=bool(args.report)
            )
            payload = {"status": "oos_evaluated", "oos_comparison": str(path), "evaluation": read_json(path)}
        else:
            raise AssertionError(f"Unhandled command: {args.command}")
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
