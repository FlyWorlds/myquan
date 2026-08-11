"""OpenBreak3 回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
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
    limit_down_pct: float = 0.10
    t0: bool = False
    # 买点基准：today_open=今日开盘；prev_open_on_small_yang=前日小阳时用前日开盘
    entry_ref: str = "today_open"
    # 前日过滤：yin_or_small_yang=阴线或小阳；yin_only=仅阴线；any=不限制前日
    prev_entry_mode: str = "yin_or_small_yang"
    # True=禁前面双阳（默认可加跨日门槛）；False=关闭双阳过滤
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG
    # True=前日为阳则禁买（可与双阳叠加）；默认关闭
    ban_single_yang: bool = DEFAULT_BAN_SINGLE_YANG
    # 计为阳线的最小涨幅（相对开盘）；0=仅需实体≥1跳
    yang_min_pct: float = 0.0
    # 双阳：第二根（前日）阳线涨幅下限；更弱则排除、不禁买；None=不额外要求
    double_yang_second_min_pct: float | None = None
    # 双阳：合计/跨日涨幅下限；默认 span≥5%；None=任意双阳都禁
    double_yang_combined_min_pct: float | None = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT
    # sum_body=两实体涨幅相加；span=第一根开盘→第二根收盘（核心默认）
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE
    # 单阳禁买时前日阳线涨幅下限；None=用 yang_min_pct
    single_yang_min_pct: float | None = None
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
    # 连续 N 次止损后：跳过下一次策略买入，再下一次才买；0=关闭
    # 例 N=2 → 止损、止损、跳过第3次买点、第4次买点才买；循环
    skip_buy_after_consec_stops: int = 0
    # 当天买入、下一交易日即止损：跳过下一次买点，再下一次才买；循环
    skip_buy_after_overnight_stop: bool = False
    # 因子2（策略一默认叠加）：None=用 strategy1 bindings / dd_topup 默认
    factor2_enabled: bool | None = None
    factor2_add_pct: float | None = None  # 均匀每档；与 factor2_add_pcts 二选一
    factor2_add_pcts: tuple[float, ...] | None = None  # 各档相对总本金比例
    factor2_levels: tuple[float, ...] | None = None
    factor2_max_inject_pct: float | None = None  # 累计追加上限（相对总本金）
    daily_cache: Path | None = None
    report_path: Path | None = None
    # 因子4·动量（单因子策略用；默认=高低点时间距离）
    mom_kind: str = "dist_hl"
    mom_params: dict | None = None

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
        if self.prev_entry_mode == "yin_only":
            prev = "仅阴后买"
        elif self.prev_entry_mode == "any":
            prev = "不限前日"
        else:
            prev = "阴/小阳后买"
        if not self.ban_double_yang:
            prev += "/不禁双阳"
        elif self.double_yang_combined_min_pct is not None:
            tag = "跨日" if self.double_yang_combined_mode == "span" else "实体和"
            prev += f"/禁双阳{tag}≥{self.double_yang_combined_min_pct*100:.0f}%"
        else:
            prev += "/禁任意双阳"
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
        skip_n = int(self.skip_buy_after_consec_stops or 0)
        skip_bits: list[str] = []
        if skip_n > 0:
            skip_bits.append(f"连止损{skip_n}跳买")
        if self.skip_buy_after_overnight_stop:
            skip_bits.append("隔日止损跳买")
        skip = ("/" + "+".join(skip_bits)) if skip_bits else ""
        return (
            f"开盘±{self.threshold_pct * 100:.1f}%"
            f"({sell}/{entry}/{prev}{skip}) "
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

TIANTONG = BacktestConfig(
    symbol="sh600330",
    symbol_name="天通股份",
    em_symbol="600330",
    threshold_pct=0.03,
    start_date="20200101",
    daily_cache=_DAILY_CACHE_DIR / "sh600330_daily_qfq.parquet",
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
