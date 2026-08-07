"""行情上下文与决策结果（策略决策层输入/输出）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Action = Literal["buy", "sell", "hold"]


@dataclass
class MarketContext:
    """单根 K 线 / 盘中快照，供决策层使用。"""

    open: float
    high: float
    low: float
    close: float
    # 盘中最新价；未设则用 close
    last: float | None = None
    session: str = ""
    prev_open: float | None = None
    prev_close: float | None = None
    prev2_open: float | None = None
    prev2_close: float | None = None
    position_qty: float = 0.0
    # 可卖数量；有仓且 available<=0 且非 t0 → 视为 T+1 禁卖
    available_qty: float = 0.0
    buy_time: str | None = None
    entry_price: float | None = None
    t0: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def price(self) -> float:
        return float(self.last if self.last is not None else self.close)

    @property
    def holding(self) -> bool:
        return float(self.position_qty) > 0

    @property
    def has_position(self) -> bool:
        return self.holding

    @property
    def t_plus_one(self) -> bool:
        """T+1 禁卖：优先 meta；否则按买入日；勿仅凭 available=0（隔夜仓未维护会误判）。"""
        if "t_plus_one" in self.meta:
            return bool(self.meta["t_plus_one"])
        if self.t0:
            return False
        if self.buy_time and self.session:
            try:
                from strategy.open_break import is_t1_buy_day

                return bool(is_t1_buy_day(self.buy_time, self.session))
            except Exception:
                pass
        # 无买入日信息时才回退 available（兼容旧调用）
        return self.holding and float(self.available_qty) <= 0


@dataclass(frozen=True)
class Decision:
    """策略决策层输出（尚未下单）。"""

    action: Action
    reason: str = ""
    price: float | None = None
    # all | target_pct | qty
    size_mode: str = "hold"
    size_value: float | None = None
    factor_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def hold(reason: str = "持有/观望", **meta: Any) -> "Decision":
        return Decision(action="hold", reason=reason, size_mode="hold", meta=dict(meta))

    @staticmethod
    def buy(
        price: float,
        *,
        reason: str = "买入",
        factor_id: str | None = None,
        target_pct: float = 0.95,
        **meta: Any,
    ) -> "Decision":
        return Decision(
            action="buy",
            reason=reason,
            price=float(price),
            size_mode="target_pct",
            size_value=float(target_pct),
            factor_id=factor_id,
            meta=dict(meta),
        )

    @staticmethod
    def sell(
        price: float,
        *,
        reason: str = "卖出",
        factor_id: str | None = None,
        qty: float | None = None,
        **meta: Any,
    ) -> "Decision":
        return Decision(
            action="sell",
            reason=reason,
            price=float(price),
            size_mode="qty" if qty is not None else "all",
            size_value=float(qty) if qty is not None else None,
            factor_id=factor_id,
            meta=dict(meta),
        )
