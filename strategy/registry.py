"""策略注册表（兼容层）。

新架构真源在 strategy.core + strategy.strategies / factors。
本模块保留 StrategyEntry / get_strategy / list_strategies，供旧代码使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from strategy.core.protocols import FactorBinding, FactorSpec, StrategySpec


@dataclass(frozen=True)
class StrategyEntry:
    id: str
    name: str
    run: Callable[..., Any]
    default_config: Any
    print_rules: Callable[[], str] | None = None
    factor_ids: tuple[str, ...] = ()
    factor_bindings: tuple[FactorBinding, ...] = ()
    aliases: tuple[str, ...] = ()
    implemented: bool = True
    description: str = ""

    def factors(self) -> list[FactorSpec]:
        from strategy.core.factor_registry import get_factor

        return [get_factor(fid) for fid in self.factor_ids]

    def bindings(self, *, enabled_only: bool = True) -> list[FactorBinding]:
        rows = list(self.factor_bindings)
        if enabled_only:
            rows = [b for b in rows if b.enabled]
        return rows

    def binding_for(self, factor_id: str) -> FactorBinding | None:
        for b in self.factor_bindings:
            if b.factor_id == factor_id and b.enabled:
                return b
        return None

    @staticmethod
    def from_spec(spec: StrategySpec) -> "StrategyEntry":
        run = spec.run
        if run is None:

            def run(*_a: Any, **_k: Any) -> None:
                raise NotImplementedError(f"策略 {spec.id} 未绑定 run")

        return StrategyEntry(
            id=spec.id,
            name=spec.name,
            run=run,
            default_config=spec.default_config,
            print_rules=spec.print_rules,
            factor_ids=spec.factor_ids,
            factor_bindings=spec.factor_bindings,
            aliases=spec.aliases,
            implemented=spec.implemented,
            description=spec.description,
        )


def _ensure_plugins_loaded() -> None:
    """导入即注册因子1/2/3/4 与策略1..6。"""
    import strategy.factors  # noqa: F401
    import strategy.strategies  # noqa: F401


def get_strategy(strategy_id: str = "strategy1") -> StrategyEntry:
    _ensure_plugins_loaded()
    from strategy.core.strategy_registry import get_strategy_spec

    return StrategyEntry.from_spec(get_strategy_spec(strategy_id))


def list_strategies() -> list[StrategyEntry]:
    _ensure_plugins_loaded()
    from strategy.core.strategy_registry import list_strategy_specs

    return [StrategyEntry.from_spec(s) for s in list_strategy_specs()]


def get_strategy_factors(strategy_id: str = "strategy1") -> list[FactorSpec]:
    return get_strategy(strategy_id).factors()


def get_strategy_bindings(strategy_id: str = "strategy1") -> list[FactorBinding]:
    """返回策略侧因子绑定（含 params / filter）。"""
    return get_strategy(strategy_id).bindings(enabled_only=True)


def get_decision_engine(strategy_id: str = "strategy1"):
    """取得策略决策引擎（只产出 Decision，不直接下单）。"""
    from strategy.core.decision import get_decision_engine as _get

    return _get(strategy_id)


# 惰性视图：首次访问时加载插件
class _RegistryProxy(dict):
    def _load(self) -> None:
        if not self:
            for e in list_strategies():
                dict.__setitem__(self, e.id, e)
                for a in e.aliases:
                    dict.__setitem__(self, a, e)

    def __getitem__(self, key: str) -> StrategyEntry:  # type: ignore[override]
        self._load()
        return dict.__getitem__(self, key)

    def __contains__(self, key: object) -> bool:
        self._load()
        return dict.__contains__(self, key)

    def keys(self):  # type: ignore[override]
        self._load()
        return dict.keys(self)

    def values(self):  # type: ignore[override]
        self._load()
        return dict.values(self)

    def items(self):  # type: ignore[override]
        self._load()
        return dict.items(self)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        self._load()
        return dict.get(self, key, default)


REGISTRY: dict[str, StrategyEntry] = _RegistryProxy()  # type: ignore[assignment]
