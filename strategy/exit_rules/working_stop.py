"""Working-stop fallback：现价破工作卖价（paper kind=last）。

从 paper_exit_decision 的 last_hit 分支提取；不改阈值公式本身。
"""

from __future__ import annotations

from typing import Any

from strategy.core.exit_decision import ExitRuleResult, ReasonCode
from strategy.core.factor_result import DecisionContext


def evaluate_working_stop(
    ctx: DecisionContext | dict[str, Any],
) -> ExitRuleResult:
    """last <= working_stop → SELL @ working_stop（全仓）。

    不处理 path / 开盘保护 / T+1（由上层编排）。
    """
    def _g(name: str, default: Any = None) -> Any:
        if isinstance(ctx, dict):
            return ctx.get(name, default)
        return getattr(ctx, name, default)

    last_px = float(_g("current_price") or _g("last") or 0)
    stop_f = float(_g("working_stop") or 0)
    last_hit = bool(stop_f > 0 and last_px > 0 and last_px <= stop_f + 1e-12)
    if not last_hit:
        return ExitRuleResult.idle(
            reason="working_stop_idle",
            last=last_px,
            working_stop=stop_f,
        )
    return ExitRuleResult.fire(
        reason_code=ReasonCode.WORKING_STOP,
        reason="last",
        price=stop_f,
        quantity_ratio=1.0,
        last=last_px,
        working_stop=stop_f,
        kind="last",
        action_kind="full",
    )
