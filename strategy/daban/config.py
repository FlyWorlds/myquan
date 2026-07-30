"""打板战法 — 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.base import CommonBacktestParams
from strategy.daban.rules import (
    DEFAULT_GAP_DOWN_EXIT_PCT,
    DEFAULT_LIMIT_PCT,
    DEFAULT_SEAL_HIGH_TICKS,
    DEFAULT_TARGET_PCT,
)


@dataclass
class DaBanConfig(CommonBacktestParams):
    em_symbol: str = ""
    target_pct: float = DEFAULT_TARGET_PCT
    limit_pct: float = DEFAULT_LIMIT_PCT
    gap_down_exit_pct: float = DEFAULT_GAP_DOWN_EXIT_PCT
    seal_high_ticks: float = DEFAULT_SEAL_HIGH_TICKS
    end_date: str = field(default_factory=lambda: dt.date.today().strftime("%Y%m%d"))

    def report_title_suffix(self) -> str:
        return (
            f"打板(封板买/不连板卖) 涨停{self.limit_pct*100:.0f}% "
            f"低开{self.gap_down_exit_pct*100:.0f}%走 "
            f"仓位{self.target_pct*100:.0f}% "
            f"({self.start_date}~{self.end_date})"
        )


KAICHENG_DABAN = DaBanConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    em_symbol="600552",
    start_date="20200101",
)
