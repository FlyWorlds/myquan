#!/usr/bin/env python3
"""Migrate supported manifest revisions without overwriting the source."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def migrate(value: dict) -> dict:
    revision = value.get("schema_revision", 1)
    if revision == 1:
        return value
    raise ValueError(f"unsupported schema_revision: {revision}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    value = migrate(json.loads(raw.decode("utf-8")))
    value.setdefault("extensions", {})
    value["extensions"].setdefault("migration", {"source_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "source_revision": value.get("schema_revision", 1)})
    args.out.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
