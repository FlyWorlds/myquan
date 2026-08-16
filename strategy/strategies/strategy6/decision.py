"""策略六 · 决策层：因子6 ETF 组合动量轮动。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy6.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


def _as_targets(raw: object) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    return None


class Strategy6Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        binding = self.binding("factor6")
        if binding is None:
            return Decision.hold("策略六未绑定因子6")
        p = binding.params
        rule = (
            f"因子6 ETF组合动量：roc({p.get('n')})+{p.get('w')}×roc({p.get('n2')}) "
            f"Top{p.get('top_k')} / {p.get('hold_days')}日再平衡；"
            f"分数<={p.get('min_score')}空仓"
        )
        if "target" not in ctx.meta:
            return Decision.hold(
                rule,
                kind="etf_combo_momentum",
                tags=("factor6", "etf_rotation"),
            )

        symbol = str(ctx.meta.get("symbol") or "")
        target = _as_targets(ctx.meta.get("target")) or []
        in_target = bool(symbol) and symbol in target

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1不可卖",
                    tags=("t1", "factor6"),
                )
            if not in_target:
                px = float(ctx.open) if ctx.open else ctx.price
                return Decision.sell(
                    px,
                    reason="因子6轮出或动量失效空仓",
                    factor_id="factor6",
                    qty=ctx.available_qty or ctx.position_qty,
                    tags=("rotate", "factor6"),
                )
            return Decision.hold(
                "持有因子6目标ETF",
                tags=("hold", "factor6"),
            )

        if in_target:
            px = float(ctx.open) if ctx.open else ctx.price
            return Decision.buy(
                px,
                reason="因子6组合动量轮入",
                factor_id="factor6",
                tags=("rotate", "factor6"),
            )
        return Decision.hold(
            "非目标ETF或动量未过门槛空仓",
            tags=("cash", "factor6"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy6Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy6Decision(bindings=bindings)
