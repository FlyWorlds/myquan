"""Exit Decision Contract（Phase 2A · 仅模型，不改调用路径）。

ExitDecision = 策略决定要不要卖 / 卖多少比例；不是 Order / Fill / Broker。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExitAction(str, Enum):
    HOLD = "HOLD"
    SELL = "SELL"


class ReasonCode(str, Enum):
    """程序对齐用；人类可读文案仍用 reason 字段。"""

    NONE = "NONE"
    T1_BLOCK = "T1_BLOCK"
    HOLD_LOCK = "HOLD_LOCK"
    LIMIT_DOWN = "LIMIT_DOWN"
    NOT_SELLABLE = "NOT_SELLABLE"
    WAIT_AUCTION = "WAIT_AUCTION"
    OPEN_PROTECT = "OPEN_PROTECT"
    PATH = "PATH"
    WORKING_STOP = "WORKING_STOP"  # paper kind=last：现价破 working_stop
    FACTOR_26 = "FACTOR_26"
    HARD_GAP = "HARD_GAP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExitRuleResult:
    """单条 exit 规则结果（开盘保护 / working_stop 等；不必称 Factor）。"""

    triggered: bool
    reason_code: ReasonCode = ReasonCode.NONE
    reason: str = ""
    price: float | None = None
    quantity_ratio: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def idle(
        *,
        reason_code: ReasonCode = ReasonCode.NONE,
        reason: str = "",
        **meta: Any,
    ) -> "ExitRuleResult":
        return ExitRuleResult(
            triggered=False,
            reason_code=reason_code,
            reason=reason,
            metadata=dict(meta),
        )

    @staticmethod
    def fire(
        *,
        reason_code: ReasonCode,
        reason: str = "",
        price: float | None = None,
        quantity_ratio: float = 1.0,
        **meta: Any,
    ) -> "ExitRuleResult":
        return ExitRuleResult(
            triggered=True,
            reason_code=reason_code,
            reason=reason or reason_code.value,
            price=float(price) if price is not None else None,
            quantity_ratio=float(quantity_ratio),
            metadata=dict(meta),
        )


@dataclass(frozen=True)
class ExitDecision:
    """统一卖出决策（编排层输出）。"""

    action: ExitAction
    price: float | None = None
    factor_id: str | None = None
    reason: str | None = None
    reason_code: ReasonCode = ReasonCode.NONE
    quantity_ratio: float = 1.0
    # hit_show=True 但不成交（T+1 / 锁仓等）
    show_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    trace: tuple[dict[str, Any], ...] = ()

    @staticmethod
    def hold(
        *,
        reason: str = "",
        reason_code: ReasonCode = ReasonCode.NONE,
        show_only: bool = False,
        trace: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
        **meta: Any,
    ) -> "ExitDecision":
        return ExitDecision(
            action=ExitAction.HOLD,
            reason=reason or None,
            reason_code=reason_code,
            show_only=bool(show_only),
            metadata=dict(meta),
            trace=tuple(trace or ()),
        )

    @staticmethod
    def sell(
        *,
        price: float | None,
        reason: str = "",
        reason_code: ReasonCode,
        quantity_ratio: float = 1.0,
        factor_id: str | None = None,
        trace: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
        **meta: Any,
    ) -> "ExitDecision":
        return ExitDecision(
            action=ExitAction.SELL,
            price=float(price) if price is not None else None,
            factor_id=factor_id,
            reason=reason or reason_code.value,
            reason_code=reason_code,
            quantity_ratio=float(quantity_ratio),
            show_only=False,
            metadata=dict(meta),
            trace=tuple(trace or ()),
        )


def paper_reason_to_code(reason: str | None, kind: str | None = None) -> ReasonCode:
    """将 legacy paper_exit_decision 的 reason/kind 映射为 ReasonCode。"""
    r = str(reason or "").strip().lower()
    k = str(kind or "").strip().lower()
    key = r or k
    mapping = {
        "t1": ReasonCode.T1_BLOCK,
        "hold_lock": ReasonCode.HOLD_LOCK,
        "limit_down": ReasonCode.LIMIT_DOWN,
        "not_sellable": ReasonCode.NOT_SELLABLE,
        "wait_auction": ReasonCode.WAIT_AUCTION,
        "open_protect": ReasonCode.OPEN_PROTECT,
        "path": ReasonCode.PATH,
        "last": ReasonCode.WORKING_STOP,
    }
    return mapping.get(key, ReasonCode.UNKNOWN if key else ReasonCode.NONE)
