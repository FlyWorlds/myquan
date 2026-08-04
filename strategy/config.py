"""OpenBreak3 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.open_break import (
    DD_FULL_PCT,
    DD_HALF_PCT,
    ENABLE_DD_SIZING,
    ENABLE_SOFT_HALF_EXIT,
    GAP945_EXIT_MODE,
    TICK_SIZE,
)


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
    # 回撤仓位：权益回撤≥dd_half_pct → 半仓；回撤<dd_full_pct → 恢复全仓开仓
    enable_dd_sizing: bool = ENABLE_DD_SIZING
    dd_half_pct: float = DD_HALF_PCT
    dd_full_pct: float = DD_FULL_PCT
    # 因子1 软减半：945/阴线未触止损时减半；止损仍全清
    enable_soft_half_exit: bool = ENABLE_SOFT_HALF_EXIT
    min1_cache: Path | None = None
    min5_cache: Path | None = None
    report_path: Path | None = None

    @property
    def slippage(self) -> dict[str, str | float]:
        return {"type": "percent", "value": self.slippage_value}

    def report_title_suffix(self) -> str:
        if not self.enable_gap945:
            mode = "无945"
        elif self.enable_soft_half_exit:
            mode = "945/阴线减半"
        else:
            mode = "945未翻红全清"
        yin = "阴线减半" if self.enable_soft_half_exit else "阴出"
        t1 = " T+1" if not self.t0 else " T+0"
        entry = (
            "买点=前日小阳开盘"
            if self.entry_ref == "prev_open_on_small_yang"
            else "买点=今日开盘"
        )
        prev = "仅阴后买" if self.prev_entry_mode == "yin_only" else "阴/小阳后买"
        dd = (
            f"回撤仓位{self.dd_half_pct*100:.0f}/{self.dd_full_pct*100:.0f}"
            if self.enable_dd_sizing
            else "无回撤仓位"
        )
        return (
            f"开盘±{self.threshold_pct * 100:.1f}%({mode}/阳持/{yin}/{entry}/{prev}/{dd}) "
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

# 港股 01888 建滔积层板：默认 T+1，因子1（945 proxy + 止损 + 阴线）
HK1888 = BacktestConfig(
    symbol="hk01888",
    symbol_name="建滔积层板",
    em_symbol="01888",
    threshold_pct=0.025,
    start_date="20200101",
    t0=False,
    lot_size=500,
    tick=0.05,
    stamp_tax_rate=0.001,
    enable_gap945=True,
    gap945_use_proxy=True,
    gap945_proxy="open",
)
