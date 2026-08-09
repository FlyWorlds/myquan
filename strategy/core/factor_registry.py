"""因子注册表：任意策略按 id 引用。"""

from __future__ import annotations

from strategy.core.protocols import FactorSpec

FACTOR_REGISTRY: dict[str, FactorSpec] = {}


def register_factor(spec: FactorSpec, *, replace: bool = False) -> FactorSpec:
    if spec.id in FACTOR_REGISTRY and not replace:
        raise ValueError(f"因子已注册: {spec.id}")
    FACTOR_REGISTRY[spec.id] = spec
    return spec


def get_factor(factor_id: str) -> FactorSpec:
    if factor_id not in FACTOR_REGISTRY:
        known = ", ".join(sorted(FACTOR_REGISTRY)) or "(空)"
        raise KeyError(f"未知因子 '{factor_id}'，可选: {known}")
    return FACTOR_REGISTRY[factor_id]


def list_factors() -> list[FactorSpec]:
    return [FACTOR_REGISTRY[k] for k in sorted(FACTOR_REGISTRY)]
