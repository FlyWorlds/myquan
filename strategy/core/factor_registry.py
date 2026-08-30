"""因子注册表：任意策略按 id 引用。"""

from __future__ import annotations

import re

from strategy.core.protocols import FactorSpec

FACTOR_REGISTRY: dict[str, FactorSpec] = {}

_FACTOR_NUM_RE = re.compile(r"^factor(\d+)$", re.I)
_CF_NUM_RE = re.compile(r"^cf(\d+)$", re.I)


def factor_sort_key(factor_id: str) -> tuple[int, int, str]:
    """factor1…factor13 按编号，cf* 其后，其余按 id。"""
    fid = str(factor_id)
    m = _FACTOR_NUM_RE.match(fid)
    if m:
        return (0, int(m.group(1)), fid)
    m = _CF_NUM_RE.match(fid)
    if m:
        return (1, int(m.group(1)), fid)
    return (2, 0, fid)


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
    return [FACTOR_REGISTRY[k] for k in sorted(FACTOR_REGISTRY, key=factor_sort_key)]
