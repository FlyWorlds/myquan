from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal


Direction = Literal["baseline", "backward", "forward", "oos"]


@dataclass(frozen=True)
class CandidateSpec:
    factors: tuple[str, ...]
    direction: Direction
    seed: int
    stage: str
    iteration: int
    group_id: str = ""
    changed_factors: tuple[str, ...] = ()

    def normalized(self) -> "CandidateSpec":
        return CandidateSpec(
            factors=tuple(sorted(set(self.factors))),
            direction=self.direction,
            seed=int(self.seed),
            stage=str(self.stage),
            iteration=int(self.iteration),
            group_id=str(self.group_id),
            changed_factors=tuple(sorted(set(self.changed_factors))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True)
class EvaluationResult:
    candidate_id: str
    factors: tuple[str, ...]
    metrics: dict[str, Any]
    candidate_dir: Path
    cached: bool = False

    @property
    def factor_count(self) -> int:
        return len(self.factors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "factors": list(self.factors),
            "factor_count": self.factor_count,
            "metrics": self.metrics,
            "candidate_dir": str(self.candidate_dir),
            "cached": self.cached,
        }
