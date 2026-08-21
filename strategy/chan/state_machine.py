"""一买候选、二买确认、二/三卖退出的确定性状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from strategy.chan.signals import ChanSignalSnapshot


class ChanState(str, Enum):
    FLAT = "flat"
    WAIT_BUY2 = "wait_buy2"
    LONG = "long"


@dataclass(frozen=True)
class ChanTransition:
    action: str
    state: ChanState
    reason: str
    strengthened: bool = False


class ChanStateMachine:
    def __init__(self, *, candidate_timeout_bars: int = 20) -> None:
        self.state = ChanState.FLAT
        self.candidate_timeout_bars = int(candidate_timeout_bars)
        self.waited_bars = 0
        self.entry_date: pd.Timestamp | None = None

    def reset(self) -> None:
        self.state = ChanState.FLAT
        self.waited_bars = 0
        self.entry_date = None

    def update(
        self,
        when: pd.Timestamp | str,
        signals: ChanSignalSnapshot,
        *,
        has_position: bool | None = None,
        can_sell: bool = True,
    ) -> ChanTransition:
        ts = pd.Timestamp(when)
        if has_position is True and self.state is not ChanState.LONG:
            self.state = ChanState.LONG
        elif has_position is False and self.state is ChanState.LONG:
            self.reset()

        if self.state is ChanState.LONG:
            sell_hit = signals.sell2 or signals.sell3
            if sell_hit:
                same_day = self.entry_date is not None and ts.date() == self.entry_date.date()
                if same_day or not can_sell or signals.limit_down or signals.suspended:
                    return ChanTransition(
                        "hold",
                        self.state,
                        "二/三卖已出现，T+1/跌停/停牌顺延",
                    )
                reason = "二卖退出" if signals.sell2 else "三卖退出"
                self.reset()
                return ChanTransition("sell", self.state, reason)
            return ChanTransition(
                "hold",
                self.state,
                "三买增强" if signals.buy3 else "持仓等待二卖/三卖",
                strengthened=signals.buy3,
            )

        if self.state is ChanState.WAIT_BUY2:
            self.waited_bars += 1
            if signals.suspended or signals.limit_up:
                return ChanTransition("candidate", self.state, "候选期停牌或涨停，暂缓确认")
            if signals.buy2:
                self.state = ChanState.LONG
                self.entry_date = ts
                self.waited_bars = 0
                return ChanTransition("buy", self.state, "一买候选后二买确认")
            if signals.sell1 or signals.sell2 or self.waited_bars >= self.candidate_timeout_bars:
                reason = "候选结构失效" if (signals.sell1 or signals.sell2) else "一买候选超时"
                self.reset()
                return ChanTransition("hold", self.state, reason)
            if signals.buy1:
                self.waited_bars = 0
            return ChanTransition("candidate", self.state, "等待二买确认")

        if signals.suspended or signals.limit_up:
            return ChanTransition("hold", self.state, "停牌或涨停，禁止新开仓")
        if signals.buy1 and signals.buy2:
            self.state = ChanState.LONG
            self.entry_date = ts
            self.waited_bars = 0
            return ChanTransition("buy", self.state, "一买与二买同根确认")
        if signals.buy1:
            self.state = ChanState.WAIT_BUY2
            self.waited_bars = 0
            return ChanTransition("candidate", self.state, "一买进入候选")
        return ChanTransition("hold", self.state, "无一买候选")


__all__ = ["ChanState", "ChanStateMachine", "ChanTransition"]
