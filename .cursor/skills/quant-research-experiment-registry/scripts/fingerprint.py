#!/usr/bin/env python3
"""Stable SHA-256 fingerprints for normalized experiment inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    value = json.loads(args.json_file.read_text(encoding="utf-8"))
    print(json.dumps({"fingerprint": fingerprint(value)}, indent=2))


if __name__ == "__main__":
    main()
