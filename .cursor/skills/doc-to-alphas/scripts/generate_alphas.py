#!/usr/bin/env python3
"""Validate alpha factor expressions against synthetic OHLCV toy data.

Usage:
    python generate_alphas.py --alphas alphas.json
    python generate_alphas.py --alphas alphas.json --output results.json
    python generate_alphas.py --alphas alphas.json --correction-context

The agent (Codex, Claude Code, etc.) generates alpha expressions using its
own LLM following the contract in references/alpha_ops.md, then this script
validates them to catch syntax errors, unsupported fields, look-ahead bias,
and numerical instability.

Use ``--correction-context`` to output a ready-to-use LLM correction prompt
for any failed alphas. The agent can then retry up to 5 times.

No API keys or external services are needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from formulas import build_correction_prompt
from validation import validate_alphas_against_toy_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate alpha expressions against synthetic OHLCV toy data."
    )
    parser.add_argument(
        "--alphas",
        type=str,
        required=True,
        help="Path to a JSON file containing alpha objects (array of {name, expression, ...}).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Output JSON file path for validation results.",
    )
    parser.add_argument(
        "--correction-context",
        action="store_true",
        help=(
            "Also print a ready-to-use LLM correction prompt for any failed "
            "alphas (for the agent's retry loop)."
        ),
    )
    args = parser.parse_args()

    alphas_path = Path(args.alphas)
    if not alphas_path.is_file():
        print(json.dumps(
            {"error": f"File not found: {args.alphas}"}, ensure_ascii=False,
        ))
        sys.exit(1)

    try:
        alphas = json.loads(alphas_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(json.dumps(
            {"error": f"Invalid JSON in {args.alphas}: {exc}"}, ensure_ascii=False,
        ))
        sys.exit(1)

    if not isinstance(alphas, list):
        print(json.dumps(
            {"error": "Alpha file must contain a JSON array."}, ensure_ascii=False,
        ))
        sys.exit(1)

    result = validate_alphas_against_toy_data(alphas)

    output_path = args.output
    if not output_path:
        import time
        output_path = f"validated_alphas_{int(time.time())}.json"

    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    result["output_path"] = output_path

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── Correction context for agent retry loop ──────────────────────────
    if args.correction_context and result.get("failed", 0) > 0:
        failed_alphas = [r for r in result.get("results", []) if not r.get("ok")]
        correction_prompt = build_correction_prompt(failed_alphas)

        print("\n" + "=" * 72)
        print("🔧 CORRECTION PROMPT (feed this to your LLM to fix failures)")
        print("=" * 72)
        print(correction_prompt)
        print("=" * 72)
        print(
            "Retry workflow: save corrected alphas → re-run validator → "
            "repeat up to 5 times until all pass."
        )


if __name__ == "__main__":
    main()
