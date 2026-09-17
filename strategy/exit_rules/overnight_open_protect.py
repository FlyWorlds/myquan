"""隔夜开盘保护 exit 规则（从 paper_exit_decision 提取；算法委托 overnight_open_protect_px）。

不改交易规则；仅把 paper 中的峰值兜底 + 触达判定收成可复用函数。
"""

from __future__ import annotations

from typing import Any

from strategy.core.exit_decision import ExitRuleResult, ReasonCode
from strategy.core.factor_result import DecisionContext
from strategy.pullback_wave_stop import overnight_open_protect_px


def resolve_peak_for_open_protect(
    *,
    cost: float,
    open_px: float,
    prev_close: float | None,
    peak_high: float | None,
) -> float | None:
    """开盘保护用峰值：高开且 peak≥今开 → 回退 max(成本, 昨收)；否则用原 peak。

    与 holdingStocks.index.paper_exit_decision 内 peak_for_open 逻辑一致。
    """
    cost_f = float(cost or 0)
    open_f = float(open_px or 0)
    try:
        raw_peak = float(peak_high) if peak_high is not None else 0.0
    except (TypeError, ValueError):
        raw_peak = 0.0
    prev_f = 0.0
    try:
        prev_f = float(prev_close) if prev_close is not None else 0.0
    except (TypeError, ValueError):
        prev_f = 0.0
    if raw_peak <= 0:
        return None
    gap_up = bool(open_f > 0 and prev_f > 0 and open_f > prev_f + 1e-12)
    if gap_up and raw_peak + 1e-12 >= open_f:
        return max(x for x in (cost_f, prev_f) if x > 0) or None
    return raw_peak


def evaluate_overnight_open_protect(
    ctx: DecisionContext | dict[str, Any],
) -> ExitRuleResult:
    """若今开已破开盘保护价 → triggered（fill=今开）。

    不处理 T+1 / 锁仓（由 ExitDecisionEngine 上层编排）。
    """
    def _g(name: str, default: Any = None) -> Any:
        if isinstance(ctx, dict):
            return ctx.get(name, default)
        return getattr(ctx, name, default)

    cost = float(_g("entry_price") or _g("cost") or 0)
    open_f = float(_g("open_px") or _g("day_open") or 0)
    prev_close = _g("prev_close", None)
    peak_high = _g("peak_high", None)
    qty = int(_g("qty") or _g("shares") or 0)
    overnight_high_ok = _g("overnight_high_ok", None)
    buy_time = _g("buy_time", None)
    session = str(_g("session") or "")

    # 允许调用方预计算保护价；否则本地计算（与 paper 同序）
    protect = _g("overnight_open_protect_px", None)
    if protect is None or float(protect or 0) <= 0:
        if cost <= 0:
            return ExitRuleResult.idle(reason="no_cost")
        peak_for_open = resolve_peak_for_open_protect(
            cost=cost,
            open_px=open_f,
            prev_close=prev_close,
            peak_high=peak_high,
        )
        protect = float(
            overnight_open_protect_px(
                cost,
                prev_close,
                peak_high=peak_for_open,
                overnight_high_ok=overnight_high_ok,
                buy_time=buy_time,
                session=session,
                qty=qty,
            )
            or 0
        )
    else:
        protect = float(protect)

    open_hit = bool(open_f > 0 and protect > 0 and open_f <= protect + 1e-12)
    if not open_hit:
        return ExitRuleResult.idle(
            reason_code=ReasonCode.NONE,
            reason="open_protect_idle",
            protect_px=protect,
            open_px=open_f,
        )
    return ExitRuleResult.fire(
        reason_code=ReasonCode.OPEN_PROTECT,
        reason="open_protect",
        price=open_f,
        quantity_ratio=1.0,
        protect_px=protect,
        open_px=open_f,
        kind="open_protect",
        action_kind="full",
    )
