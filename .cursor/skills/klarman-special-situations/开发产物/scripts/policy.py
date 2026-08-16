"""Immutable research policies for V7 qualification and validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ResearchPolicy:
    name: str = "v7-baseline"
    version: str = "1"
    minimum_margin_of_safety: float = 0.20
    failure_probability_stress: float = 0.30
    placement_gain_alert_threshold: float = 0.20

    @property
    def policy_id(self) -> str:
        payload = {
            "name": self.name,
            "version": self.version,
            "minimum_margin_of_safety": self.minimum_margin_of_safety,
            "failure_probability_stress": self.failure_probability_stress,
            "placement_gain_alert_threshold": self.placement_gain_alert_threshold,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"{self.name}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"

    def with_overrides(self, **kwargs: Any) -> "ResearchPolicy":
        return replace(self, **kwargs)


def default_policy() -> ResearchPolicy:
    return ResearchPolicy()


def load_policy(path: str | Path | None = None) -> ResearchPolicy:
    if path is None:
        return default_policy()
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError("policy 文件必须是映射")
    allowed = {
        "name",
        "version",
        "minimum_margin_of_safety",
        "failure_probability_stress",
        "placement_gain_alert_threshold",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"policy 含未知字段: {unknown}")
    return ResearchPolicy(**dict(raw))
