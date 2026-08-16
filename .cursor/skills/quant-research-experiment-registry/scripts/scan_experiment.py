#!/usr/bin/env python3
"""Read-only, layered experiment directory scanner."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache", ".ruff_cache"}
SENSITIVE_NAMES = {".env", ".env.local", "credentials", "credentials.json", "secrets.json", "id_rsa"}
TEXT_EXTENSIONS = {".py", ".ipynb", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".log", ".sh", ".ps1", ".r", ".jl", ".sql"}
DATA_EXTENSIONS = {".csv", ".parquet", ".feather", ".arrow", ".jsonl"}
SECRET_PATTERNS = [re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}"), re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"), re.compile(r"sk-[A-Za-z0-9]{20,}")]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def looks_sensitive(path: Path, sample: bytes | None = None) -> list[str]:
    reasons = []
    if path.name.lower() in SENSITIVE_NAMES or any(part.lower() in SENSITIVE_NAMES for part in path.parts):
        reasons.append("sensitive_filename")
    if sample is not None:
        text = sample.decode("utf-8", errors="replace")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            reasons.append("secret_pattern")
    return reasons


def classify(path: Path, text: str | None) -> tuple[str, float, list[str]]:
    suffix = path.suffix.lower()
    reasons: list[str] = []
    if suffix in {".yaml", ".yml", ".toml", ".json"}:
        role, confidence = "config", 0.65
    elif suffix in {".py", ".r", ".jl", ".sql", ".sh", ".ps1"}:
        role, confidence = "code", 0.7
    elif suffix in DATA_EXTENSIONS:
        role, confidence = "data", 0.55
    elif suffix in {".log", ".out", ".err"}:
        role, confidence = "log", 0.65
    elif suffix in {".md", ".txt"}:
        role, confidence = "documentation", 0.4
    else:
        role, confidence = "unclassified", 0.1
    if text and re.search(r"panda[_-]?data|pandaai", text, re.I):
        reasons.append("panda_data_reference")
        confidence = min(0.98, confidence + 0.2)
    if text and re.search(r"(sharpe|drawdown|icir|rank.?ic|annual.?return)", text, re.I):
        reasons.append("result_metric_reference")
        if role == "documentation":
            role, confidence = "result", 0.7
    return role, confidence, reasons


def scan(root: Path) -> dict:
    root = root.resolve()
    assets = []
    counts = {"scanned": 0, "content_read": 0, "excluded": 0, "sensitive": 0}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts) or path.name.lower() in SENSITIVE_NAMES:
            counts["excluded"] += 1
            continue
        counts["scanned"] += 1
        size = path.stat().st_size
        sample = None
        text = None
        if path.suffix.lower() in TEXT_EXTENSIONS and size <= 2 * 1024 * 1024:
            sample = path.read_bytes()
            text = sample.decode("utf-8", errors="replace")
            counts["content_read"] += 1
        sensitive = looks_sensitive(path, sample)
        if sensitive:
            counts["sensitive"] += 1
        role, confidence, reasons = classify(path, text)
        assets.append({
            "path": rel.as_posix(), "role": role, "confidence": confidence,
            "size_bytes": size, "sha256": sha256_file(path),
            "sensitive": bool(sensitive), "sensitivity_reasons": sensitive,
            "evidence": reasons, "content_scanned": text is not None,
        })
    return {"scan_version": 1, "root": str(root), "scanned_at": datetime.now(timezone.utc).isoformat(), "counts": counts, "assets": assets}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = scan(args.root)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
