"""OpenBreak3 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.open_break import GAP945_EXIT_MODE, PULLBACK_PCT, TICK_SIZE


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
    # 买点基准：today_open=今日开盘；prev_open_on_small_yang=前日小阳时用前日开盘
    entry_ref: str = "today_open"
    # 前日过滤：yin_or_small_yang=阴线或小阳；yin_only=仅阴线（小阳次日不买）
    prev_entry_mode: str = "yin_or_small_yang"
    # 因子2：开盘迄今最高回落 → 减半仓（总开关 ENABLE_FACTOR2，当前关）
    enable_factor2: bool = False
    pullback_pct: float = PULLBACK_PCT
    min1_cache: Path | None = None
    report_path: Path | None = None

    @property
    def slippage(self) -> dict[str, str | float]:
        return {"type": "percent", "value": self.slippage_value}

    def report_title_suffix(self) -> str:
        mode = "945未翻红全清" if self.enable_gap945 else "无945"
        t1 = " T+1" if not self.t0 else ""
        entry = (
            "买点=前日小阳开盘"
            if self.entry_ref == "prev_open_on_small_yang"
            else "买点=今日开盘"
        )
        prev = "仅阴后买" if self.prev_entry_mode == "yin_only" else "阴/小阳后买"
        f2 = (
            f"高回落{self.pullback_pct * 100:.1f}%减半"
            if self.enable_factor2
            else "无因子2"
        )
        return (
            f"开盘±{self.threshold_pct * 100:.1f}%({mode}/阳持/阴出/{entry}/{prev}/{f2}) "
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

HANGTIANDIANZI = BacktestConfig(
    symbol="sh600879",
    symbol_name="航天电子",
    em_symbol="600879",
    threshold_pct=0.025,
    start_date="20200101",
    enable_gap945=True,
    gap945_use_proxy=True,
    gap945_proxy="open",
)

XIEXINNENGKE = BacktestConfig(
    symbol="sz002015",
    symbol_name="协鑫能科",
    em_symbol="002015",
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
