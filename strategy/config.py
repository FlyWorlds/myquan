"""OpenBreak3 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.open_break import TICK_SIZE


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
    limit_down_pct: float = 0.10
    t0: bool = False
    # 买点基准：today_open=今日开盘；prev_open_on_small_yang=前日小阳时用前日开盘
    entry_ref: str = "today_open"
    # 前日过滤：yin_or_small_yang=阴线或小阳；yin_only=仅阴线（小阳次日不买）
    prev_entry_mode: str = "yin_or_small_yang"
    # 分档止盈：相对买入价涨幅触及后，按初始仓位比例减仓；None=关闭（仅止损）
    # 例 (0.15, 0.20, 0.25) + take_profit_reduce=0.20 → +15%/20%/25% 各减初始仓 20%
    take_profit_levels: tuple[float, ...] | None = None
    take_profit_reduce: float = 0.20
    # 触及判定：high=当日最高价；close=收盘价（更严）
    take_profit_trigger: str = "high"
    # 挂单相对档位再抬高的百分点：档15% + offset2% → 限价按+17%；
    # 仅当行情摸到挂单价才算该档止盈成交，否则该档本轮不减仓
    take_profit_limit_offset: float = 0.0
    # 触及止盈档后抬止损下限到 买入价×(1+lock)；None=不抬；可与减仓并用
    take_profit_lock_pct: float | None = None
    daily_cache: Path | None = None
    report_path: Path | None = None

    @property
    def slippage(self) -> dict[str, str | float]:
        return {"type": "percent", "value": self.slippage_value}

    def report_title_suffix(self) -> str:
        t1 = " T+1" if not self.t0 else " T+0"
        entry = (
            "买点=前日小阳开盘"
            if self.entry_ref == "prev_open_on_small_yang"
            else "买点=今日开盘"
        )
        prev = "仅阴后买" if self.prev_entry_mode == "yin_only" else "阴/小阳后买"
        if self.take_profit_levels:
            lv = "/".join(f"{x*100:.0f}" for x in self.take_profit_levels)
            trig = "收盘" if self.take_profit_trigger == "close" else "高点"
            off = float(self.take_profit_limit_offset or 0.0)
            if off > 0:
                parts = [f"止盈{lv}挂+{off*100:.0f}@{trig}"]
            else:
                parts = [f"止盈{lv}@{trig}"]
            if self.take_profit_reduce and self.take_profit_reduce > 0:
                parts.append(f"各减{self.take_profit_reduce*100:.0f}%")
            if self.take_profit_lock_pct is not None:
                parts.append(f"锁盈+{self.take_profit_lock_pct*100:.0f}%")
            parts.append("止损清余")
            sell = "".join(parts) if len(parts) == 1 else "+".join(parts[:1]) + "(" + ",".join(parts[1:]) + ")"
        else:
            sell = "仅止损卖"
        return (
            f"开盘±{self.threshold_pct * 100:.1f}%"
            f"({sell}/{entry}/{prev}) "
            f"滑点{self.slippage_value * 100:.1f}点{t1} "
            f"({self.start_date}~{self.end_date})"
        )


# --- 常用标的预设（backtest 脚本可直接引用）---
_DAILY_CACHE_DIR = Path(__file__).resolve().parents[1] / "data_cache"

KAICHENG = BacktestConfig(
    symbol="sh600552",
    symbol_name="凯盛科技",
    em_symbol="600552",
    threshold_pct=0.025,
    start_date="20200101",
    daily_cache=_DAILY_CACHE_DIR / "sh600552_daily_qfq.parquet",
)

HANGTIANDIANZI = BacktestConfig(
    symbol="sh600879",
    symbol_name="航天电子",
    em_symbol="600879",
    threshold_pct=0.025,
    start_date="20200101",
    daily_cache=_DAILY_CACHE_DIR / "sh600879_daily_qfq.parquet",
)

XIEXINNENGKE = BacktestConfig(
    symbol="sz002015",
    symbol_name="协鑫能科",
    em_symbol="002015",
    threshold_pct=0.025,
    start_date="20200101",
    daily_cache=_DAILY_CACHE_DIR / "sz002015_daily_qfq.parquet",
)

ZZ500_ETF = BacktestConfig(
    symbol="sh510580",
    symbol_name="中证500ETF",
    em_symbol="510580",
    threshold_pct=0.025,
    start_date="20250101",
    stamp_tax_rate=0.0,
    tick=0.001,
    daily_cache=_DAILY_CACHE_DIR / "sh510580_daily_qfq.parquet",
)
