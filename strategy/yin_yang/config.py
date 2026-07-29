"""日线阴阳策略 — 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.base import CommonBacktestParams


@dataclass
class YinYangConfig(CommonBacktestParams):
    em_symbol: str = ""
    target_pct: float = 0.95
    end_date: str = field(default_factory=lambda: dt.date.today().strftime("%Y%m%d"))

    def report_title_suffix(self) -> str:
        return (
            f"日线阴阳(阳买/阴卖) 仓位{self.target_pct*100:.0f}% "
            f"({self.start_date}~{self.end_date})"
        )


KAICHENG_YIN_YANG = YinYangConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    em_symbol="600552",
    start_date="20200101",
)
