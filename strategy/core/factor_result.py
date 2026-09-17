"""因子输出与决策上下文（Contract 雏形；不改交易算法）。

Factor → FactorResult → DecisionEngine → Decision
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DecisionAction(str, Enum):
    """稳定动作枚举；现有 Decision.action 仍为小写字符串，后续可渐进对齐。"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class FactorResult:
    """单因子评估结果（触发与否 + 原因 + 透传元数据）。"""

    triggered: bool
    factor_id: str
    reason: str = ""
    price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def idle(factor_id: str, *, reason: str = "", **meta: Any) -> "FactorResult":
        return FactorResult(
            triggered=False,
            factor_id=str(factor_id),
            reason=reason,
            metadata=dict(meta),
        )

    @staticmethod
    def fire(
        factor_id: str,
        *,
        reason: str,
        price: float | None = None,
        **meta: Any,
    ) -> "FactorResult":
        return FactorResult(
            triggered=True,
            factor_id=str(factor_id),
            reason=reason,
            price=float(price) if price is not None else None,
            metadata=dict(meta),
        )


@dataclass
class DecisionContext:
    """因子纯计算输入（尽量不读全局 / holdingStocks / akquant）。

    与 MarketContext 并存：MarketContext 服务 DecisionEngine 日线/快照路径；
    DecisionContext 服务单因子（尤其因子26 1m bar）characterization / 统一入口。
    """

    symbol: str = ""
    current_price: float = 0.0
    entry_price: float | None = None
    bars: list[Any] = field(default_factory=list)
    position: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None
    # 因子26 单 bar 常用字段（避免强行塞进 position）
    bar_open: float = 0.0
    bar_high: float = 0.0
    bar_low: float = 0.0
    peak_before: float = 0.0
    shares: int = 0
    tp_stage: int = 0
    can_sell: bool = True
    overnight_armed: bool = False
    day_open: float | None = None
    session_peak_before: float = 0.0
    vol20_daily: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
