"""Explicit, one-time legacy strategy16 checkpoints; never import during startup."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from database_strategy_books import request_books


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("strategy_sim_state.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    frozen = args.out / "checkpoints.json"
    if frozen.exists():
        saved = json.loads(frozen.read_text())
        if saved.get("source") != str(args.source.resolve()):
            raise ValueError("Existing migration snapshot belongs to another source")
        books = saved["books"]
    else:
        raw = json.loads(args.source.read_text())
        books = {key.split(":",1)[1]: book for key,book in raw.get("positions", {}).items() if key.startswith("strategy16:")}
        # Generated audit evidence, not a live local ledger. Retries reuse this exact snapshot.
        frozen.write_text(json.dumps({"source": str(args.source.resolve()), "books": books}, ensure_ascii=False, indent=2))
    applied, errors = [], []
    if args.apply:
        for code, book in books.items():
            try:
                result = request_books("POST", book, suffix=f"/{code}/checkpoint")
                if result.get("history_status") != "legacy_checkpoint_unverified":
                    raise ValueError("Checkpoint history status not retained")
                applied.append(code)
            except Exception as exc:
                errors.append(dict(code=code, error=str(exc)))
    report = dict(source_books=len(books), applied=len(applied), errors=errors,
                  history_status="legacy_checkpoint_unverified", snapshot=str(frozen))
    (args.out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
