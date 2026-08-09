"""决策层协议：因子出信号 → 策略做买卖决策。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from strategy.core.context import Decision, MarketContext
from strategy.core.factor_registry import get_factor
from strategy.core.protocols import FactorBinding, StrategySpec


@runtime_checkable
class DecisionEngine(Protocol):
    """策略决策引擎：只产出 Decision，不直接下单。"""

    strategy_id: str

    def decide(self, ctx: MarketContext) -> Decision: ...


class BaseDecisionEngine:
    """带因子绑定的决策基类。"""

    strategy_id: str = ""
    strategy_name: str = ""

    def __init__(self, bindings: tuple[FactorBinding, ...] = ()) -> None:
        self.bindings = tuple(b for b in bindings if b.enabled)

    def binding(self, factor_id: str) -> FactorBinding | None:
        for b in self.bindings:
            if b.factor_id == factor_id:
                return b
        return None

    def factor_allowed(self, binding: FactorBinding, ctx: MarketContext) -> bool:
        return binding.passes_filter(
            ctx.prev_open,
            ctx.prev_close,
            ctx.prev2_open,
            ctx.prev2_close,
        )

    def levels_for(self, binding: FactorBinding, ctx: MarketContext) -> dict[str, Any]:
        """统一价位键：buy / stop（兼容因子返回 buy_trigger）。"""
        factor = get_factor(binding.factor_id)
        if factor.levels is None:
            return {}
        params = binding.merged_params()
        entry_pct = float(params.get("entry_pct", params.get("threshold_pct", 0.025)))
        stop_pct = float(params.get("stop_pct", entry_pct))
        tick = float(params.get("tick", 0.01))
        raw = factor.levels(
            ctx.open, entry_pct=entry_pct, stop_pct=stop_pct, tick=tick
        )
        out = dict(raw or {})
        if "buy" not in out and "buy_trigger" in out:
            out["buy"] = out["buy_trigger"]
        return out

    def decide(self, ctx: MarketContext) -> Decision:
        raise NotImplementedError


def engine_from_spec(spec: StrategySpec) -> DecisionEngine | None:
    """从 StrategySpec.decision_factory（或 meta 兼容键）取引擎。"""
    factory = spec.decision_factory or spec.meta.get("decision_factory")
    if callable(factory):
        return factory(spec)  # type: ignore[no-any-return]
    eng = spec.meta.get("decision_engine")
    return eng  # type: ignore[return-value]


def get_decision_engine(strategy_id: str = "strategy1") -> DecisionEngine:
    """按策略 id/别名取得决策引擎实例。"""
    from strategy.core.strategy_registry import get_strategy_spec

    spec = get_strategy_spec(strategy_id)
    eng = engine_from_spec(spec)
    if eng is None:
        raise NotImplementedError(f"策略 {spec.id} 未绑定 decision_factory")
    return eng
