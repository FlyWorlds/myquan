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
    """因子 / Exit 纯计算输入（尽量不读全局 / holdingStocks / akquant）。

    与 MarketContext 并存：MarketContext 服务旧 DecisionEngine 日线/快照路径；
    DecisionContext 服务 Factor26 / ExitDecisionEngine 统一入口。
    """

    symbol: str = ""
    current_price: float = 0.0
    entry_price: float | None = None
    bars: list[Any] = field(default_factory=list)
    position: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None
    # 因子26 单 bar 常用字段
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
    # ---- Phase 2：paper exit 对齐所需显式上下文（禁止读 holdingStocks 全局）----
    working_stop: float | None = None
    overnight_open_protect_px: float | None = None
    prev_close: float | None = None
    peak_high: float | None = None
    open_px: float | None = None
    path_hit: bool = False
    path_fill_px: float | None = None
    path_action_kind: str = ""
    path_stop_kind: str = ""
    path: Any | None = None  # 可选：完整 path 对象；当前以 path_* 标量为主
    t1_today: bool = False
    hold_locked: bool = False
    stop_locked: bool = False
    sellable: int = 0
    signal_ok: bool = True
    overnight_high_ok: bool | None = None
    buy_time: str | None = None
    session: str = ""
    qty: int = 0
