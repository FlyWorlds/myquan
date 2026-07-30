"""OpenBreak3 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.open_break import GAP945_EXIT_MODE, TICK_SIZE


@dataclass
class BacktestConfig:
    symbol: str
    symbol_name: str
    em_symbol: str
    threshold_pct: float = 0.025
    start_date: str = "20200101"
    end_date: str = field(default_factory=lambda: dt.date.today().strftime("%Y%m%d"))
    initial_cash: float = 100_000.0
    target_pct: float = 0.95
    lot_size: int = 100
    commission_rate: float = 0.0000854
    stamp_tax_rate: float = 0.001
    slippage_value: float = 0.001
    tick: float = TICK_SIZE
    t0: bool = False
    enable_gap945: bool = True
    gap945_use_proxy: bool = False
    gap945_proxy: str = "open"  # open | mid
    gap945_exit_mode: str = GAP945_EXIT_MODE
    min1_cache: Path | None = None
    report_path: Path | None = None

    @property
    def slippage(self) -> dict[str, str | float]:
        return {"type": "percent", "value": self.slippage_value}

    def report_title_suffix(self) -> str:
        mode = "945未翻红全清" if self.enable_gap945 else "无945"
        t1 = " T+1" if not self.t0 else ""
        return (
            f"开盘±{self.threshold_pct * 100:.1f}%({mode}/阳持/阴出) "
            f"滑点{self.slippage_value * 100:.1f}点{t1} "
            f"({self.start_date}~{self.end_date})"
        )


# --- 常用标的预设（huice 脚本可直接引用）---

KAICHENG = BacktestConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    em_symbol="600552",
    threshold_pct=0.025,
    start_date="20200101",
    enable_gap945=True,
    gap945_use_proxy=True,
    gap945_proxy="open",
)

ZZ500_ETF = BacktestConfig(
    symbol="sh510580",
    symbol_name="中证500ETF",
    em_symbol="510580",
    threshold_pct=0.025,
    start_date="20250101",
    stamp_tax_rate=0.0,
    tick=0.001,
    enable_gap945=True,
    gap945_use_proxy=False,
)
