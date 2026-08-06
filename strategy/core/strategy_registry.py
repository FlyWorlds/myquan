"""策略注册表：支持别名（strategy1 ≡ open_break3）。"""

from __future__ import annotations

from strategy.core.protocols import StrategySpec

STRATEGY_REGISTRY: dict[str, StrategySpec] = {}
_ALIAS_TO_ID: dict[str, str] = {}


def register_strategy(spec: StrategySpec, *, replace: bool = False) -> StrategySpec:
    if spec.id in STRATEGY_REGISTRY and not replace:
        raise ValueError(f"策略已注册: {spec.id}")
    STRATEGY_REGISTRY[spec.id] = spec
    _ALIAS_TO_ID[spec.id] = spec.id
    for a in spec.aliases:
        _ALIAS_TO_ID[str(a)] = spec.id
    return spec


def resolve_strategy_id(strategy_id: str) -> str:
    key = str(strategy_id)
    if key in _ALIAS_TO_ID:
        return _ALIAS_TO_ID[key]
    if key in STRATEGY_REGISTRY:
        return key
    known = ", ".join(sorted(set(_ALIAS_TO_ID) | set(STRATEGY_REGISTRY))) or "(空)"
    raise KeyError(f"未知策略 '{strategy_id}'，可选: {known}")


def get_strategy_spec(strategy_id: str) -> StrategySpec:
    return STRATEGY_REGISTRY[resolve_strategy_id(strategy_id)]


def list_strategy_specs() -> list[StrategySpec]:
    return [STRATEGY_REGISTRY[k] for k in sorted(STRATEGY_REGISTRY)]
