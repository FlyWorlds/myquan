"""akquant 回测：OpenBreak3Strategy 与报告。"""

from __future__ import annotations

from typing import Any

import akquant as aq
import pandas as pd
from akquant import Strategy

from strategy.costs import COMMISSION_RATE, MISC_FEE_RATE, SLIPPAGE_VALUE, STAMP_TAX_RATE, fee_rules_text
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    ENTRY_PCT,
    PREV_SMALL_YANG_PCT,
    STOP_PCT,
    TICK_SIZE,
    entry_trigger_price,
    is_yang,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)


class OpenBreak3Strategy(Strategy):
    """相对开盘±pct买入；默认仅止损全清；可选分档止盈减仓。"""

    symbol: str = "sh600552"
    symbol_name: str = "凯盛科技"
    target_pct: float = 0.95
    lot_size: int = 100
    start_date: str = "20250101"
    end_date: str = ""
    slippage_value: float = SLIPPAGE_VALUE
    commission_rate: float = COMMISSION_RATE
    misc_fee_rate: float = MISC_FEE_RATE
    stamp_tax_rate: float = STAMP_TAX_RATE
    entry_pct: float = ENTRY_PCT
    stop_pct: float = STOP_PCT
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT
    tick: float = TICK_SIZE
    limit_down_pct: float = 0.10
    t0: bool = False
    # today_open | prev_open_on_small_yang
    entry_ref: str = "today_open"
    # yin_or_small_yang | yin_only | any
    prev_entry_mode: str = "yin_or_small_yang"
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG
    ban_single_yang: bool = DEFAULT_BAN_SINGLE_YANG
    yang_min_pct: float = 0.0
    double_yang_second_min_pct: float | None = None
    double_yang_combined_min_pct: float | None = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE  # span | sum_body
    single_yang_min_pct: float | None = None
    # 分档止盈：相对买入价；每档减 initial_qty × take_profit_reduce；余仓止损全清
    take_profit_levels: tuple[float, ...] = ()
    take_profit_reduce: float = 0.20
    take_profit_trigger: str = "high"  # high | close | prev_high
    # 档位激活后挂单价 = 买入价×(1+档位+offset)；仅摸到挂单价才减仓
    take_profit_limit_offset: float = 0.0
    take_profit_lock_pct: float | None = None
    # 因子9 动能门控 / 夏普衰减门控（date -> 允许买入）；空 dict=关闭
    energy_allowed_by_date: dict[str, bool] = {}
    halt_by_date: dict[str, bool] = {}
    # 行情 regime 调整止盈（与因子4 止损暂停独立）
    regime_tp_enabled: bool = False
    regime_by_date: dict[str, str] = {}
    regime_tp_bull: tuple[float, ...] = ()
    regime_tp_sideways: tuple[float, ...] = (0.15,)
    regime_tp_bear: tuple[float, ...] = (0.10,)
    # 连续 N 次止损后跳过下一次买点、再下一次才买；0=关闭
    skip_buy_after_consec_stops: int = 0
    # 当天买、下一交易日止损 → 跳过下一次买点，再下一次才买
    skip_buy_after_overnight_stop: bool = False
    # 当日止损后尾盘再买（新仓当日不可卖）；默认关
    allow_same_day_rebuy_after_stop: bool = False
    rebuy_require_yang: bool = True
    rebuy_above_stop_pct: float = 0.0
    rebuy_from_low_pct: float = 0.0
    # 因子4：牛市持股 regime（由 runner 注入 bull_by_date）
    factor4_enabled: bool = False
    factor4_bull_entry: bool = False
    factor4_skip_f1_entry_in_bull: bool = False
    factor4_kind: str = "roc_ma"
    bull_by_date: dict[str, bool] = {}
    factor4_stop_widen_mult: float = 0.0

    def _is_bull_today(self, day: str) -> bool:
        if not bool(self.factor4_enabled):
            return False
        return bool(self.bull_by_date.get(day, False))

    def _try_bull_entry(
        self,
        *,
        day: str,
        open_px: float,
    ) -> bool:
        """牛市 regime 内空仓 → 开盘建仓持股（修复趋势踏空）。"""
        if not self._is_bull_today(day) or not bool(self.factor4_bull_entry):
            return False
        pos = float(self.get_position(self.symbol))
        if (not self.armed) or pos > 0:
            return False
        tgt = float(self.target_pct)
        self.order_target_percent(
            symbol=self.symbol,
            target_percent=tgt,
            price=open_px,
        )
        self.armed = False
        self.entry_price = open_px
        self.buy_day = day
        self.bars_held = 0
        self.log(
            f"{day} 因子4牛市开盘建仓(持股不动) target={tgt*100:.1f}% "
            f"限价={open_px:.2f} 持有收益=+0.00%"
        )
        return True

    def on_start(self) -> None:
        self.subscribe(self.symbol)
        self.lot_size = self.lot_size
        self.armed = True
        self.entry_price: float | None = None
        self.prev_open: float | None = None
        self.prev_close: float | None = None
        self.prev_high: float | None = None
        self.prev2_open: float | None = None
        self.prev2_close: float | None = None
        self.buy_day: str | None = None
        self.initial_qty: float | None = None
        self.tp_done: set[int] = set()
        self.stop_floor: float | None = None
        self.bars_held: int = 0
        self.consec_stops: int = 0
        self.same_day_rebuy_count: int = 0
        # normal | skip_next | take_next
        self.entry_gate: str = "normal"
        entry_txt = (
            "买点=前日小阳开盘×(1+pct)"
            if self.entry_ref == "prev_open_on_small_yang"
            else "买点=今日开盘×(1+pct)"
        )
        if self.prev_entry_mode == "yin_only":
            prev_txt = "前日仅阴线（小阳次日不买）"
        elif self.prev_entry_mode == "any":
            prev_txt = "不限前日"
        else:
            prev_txt = f"前日须阴线或小阳(<{self.prev_small_yang_pct*100:.1f}%)"
        yang_bits: list[str] = []
        if self.ban_single_yang:
            sthr = self.single_yang_min_pct
            yang_bits.append(
                f"禁单阳≥{(sthr if sthr is not None else self.yang_min_pct)*100:.1f}%"
            )
        if self.ban_double_yang:
            bits = ["禁双阳"]
            if self.yang_min_pct > 0:
                bits.append(f"阳≥{self.yang_min_pct*100:.1f}%")
            if self.double_yang_second_min_pct is not None:
                bits.append(f"第2根≥{self.double_yang_second_min_pct*100:.1f}%")
            if self.double_yang_combined_min_pct is not None:
                tag = (
                    "跨日"
                    if self.double_yang_combined_mode == "span"
                    else "实体和"
                )
                bits.append(
                    f"{tag}≥{self.double_yang_combined_min_pct*100:.1f}%"
                )
            yang_bits.append("+".join(bits) if len(bits) > 1 else bits[0])
        yang_txt = "；".join(yang_bits) if yang_bits else "不禁阳线"
        if self.take_profit_levels or bool(self.regime_tp_enabled):
            lv = "/".join(f"{x*100:.0f}" for x in self.take_profit_levels) or "regime"
            trig_map = {"close": "收盘", "prev_high": "前日高点→开盘", "high": "高点"}
            trig = trig_map.get(str(self.take_profit_trigger), "高点")
            off = float(self.take_profit_limit_offset or 0.0)
            bits = [
                f"止盈{lv}挂+{off*100:.0f}@{trig}" if off > 0 else f"止盈{lv}@{trig}"
            ]
            red = float(self.take_profit_reduce or 0.0)
            if red >= 1.0 - 1e-12:
                bits.append("全清")
            elif red > 0:
                bits.append(f"各减{red*100:.0f}%")
            if self.take_profit_lock_pct is not None:
                bits.append(f"锁{self.take_profit_lock_pct*100:.0f}%")
            sell_txt = "+买/" + "/".join(bits) + "/余仓止损"
        else:
            sell_txt = "+买/-止损，仅止损全清"
        skip_bits: list[str] = []
        skip_n = int(self.skip_buy_after_consec_stops or 0)
        if skip_n > 0:
            skip_bits.append(f"连止损{skip_n}次后跳过下一次买入、再下一次才买(循环)")
        if self.skip_buy_after_overnight_stop:
            skip_bits.append("隔日止损后跳过下一次买入、再下一次才买(循环)")
        if bool(self.allow_same_day_rebuy_after_stop):
            rb = ["止损当日尾盘再买(新仓T+1)"]
            if bool(self.rebuy_require_yang):
                rb.append("须收阳")
            above = float(self.rebuy_above_stop_pct or 0.0)
            from_low = float(self.rebuy_from_low_pct or 0.0)
            if above > 0:
                rb.append(f"收盘>止损+{above*100:.1f}点")
            else:
                rb.append("收盘≥止损价")
            if from_low > 0:
                rb.append(f"距最低≥{from_low*100:.1f}点")
            skip_bits.append("+".join(rb))
        skip_txt = (" | " + "；".join(skip_bits)) if skip_bits else ""
        f4_bits: list[str] = []
        if bool(self.factor4_enabled):
            f4_bits.append(f"因子4={self.factor4_kind}")
            if self.factor4_bull_entry:
                f4_bits.append("牛市开盘建仓")
            widen = float(self.factor4_stop_widen_mult or 0.0)
            if widen > 1.0:
                f4_bits.append(f"牛市止损放宽{widen:g}倍")
            else:
                f4_bits.append("牛市暂停止损")
            if self.factor4_skip_f1_entry_in_bull:
                f4_bits.append("牛市跳过F1买点")
        f4_txt = (" | " + "；".join(f4_bits)) if f4_bits else ""
        if abs(float(self.entry_pct) - float(self.stop_pct)) < 1e-12:
            thr_txt = f"开盘±{self.entry_pct*100:.1f}%"
        else:
            thr_txt = (
                f"开盘+{self.entry_pct*100:.1f}%/-{self.stop_pct*100:.1f}%"
            )
        self.log(
            f"{self.symbol_name}({self.symbol}) {thr_txt} "
            f"({sell_txt}) | "
            f"{prev_txt}，{yang_txt} | "
            f"{entry_txt}{skip_txt}{f4_txt} | "
            f"{fee_rules_text(etf=bool(self.stamp_tax_rate == 0.0))} | "
            f"{self.start_date}~{self.end_date}"
        )

    def _entry_skip_enabled(self) -> bool:
        return int(self.skip_buy_after_consec_stops or 0) > 0 or bool(
            self.skip_buy_after_overnight_stop
        )
    def _hold_pnl_pct(self, mark_px: float) -> float | None:
        if self.entry_price is None or self.entry_price <= 0:
            return None
        return (float(mark_px) / float(self.entry_price) - 1.0) * 100.0

    def _fmt_hold(self, mark_px: float) -> str:
        pct = self._hold_pnl_pct(mark_px)
        if pct is None:
            return "持有收益=n/a"
        return f"持有收益={pct:+.2f}%"

    def _reset_trade_state(self) -> None:
        self.armed = True
        self.entry_price = None
        self.buy_day = None
        self.initial_qty = None
        self.tp_done = set()
        self.stop_floor = None
        self.bars_held = 0

    def _sync_position_state(self) -> float:
        pos = float(self.get_position(self.symbol))
        if pos <= 0:
            self._reset_trade_state()
        else:
            self.armed = False
            if self.initial_qty is None:
                self.initial_qty = pos
        return pos

    def _on_stop_exit(
        self,
        day: str,
        *,
        bars_held: int = 0,
        buy_day: str | None = None,
    ) -> None:
        """止损清仓后的买入门控。

        - skip_buy_after_overnight_stop：买后下一交易日即止损 → 跳过下次买点
        - skip_buy_after_consec_stops：连续 N 次止损 → 跳过下次买点
        """
        if bool(self.skip_buy_after_overnight_stop) and int(bars_held) == 1:
            self.entry_gate = "skip_next"
            self.consec_stops = 0
            self.log(
                f"{day} 隔日止损(买{buy_day}→止{day}) → "
                f"下次策略买点跳过，再下一次才买入"
            )
            return

        n = int(self.skip_buy_after_consec_stops or 0)
        if n <= 0:
            return
        self.consec_stops = int(getattr(self, "consec_stops", 0) or 0) + 1
        gate = str(getattr(self, "entry_gate", "normal") or "normal")
        if gate == "normal" and self.consec_stops >= n:
            self.entry_gate = "skip_next"
            self.log(
                f"{day} 连续止损达{n}次 → 下次策略买点跳过，再下一次才买入"
                f" (consec_stops={self.consec_stops})"
            )
        else:
            self.log(f"{day} 连止损计数={self.consec_stops}/{n} gate={gate}")

    def _reset_entry_gate(self) -> None:
        self.consec_stops = 0
        self.entry_gate = "normal"

    def _exit_all(
        self,
        *,
        day: str,
        avail: float,
        pos: float,
        price: float,
        reason: str,
        is_stop: bool = False,
    ) -> bool:
        hold_txt = self._fmt_hold(price)
        bars_held = int(getattr(self, "bars_held", 0) or 0)
        buy_day = self.buy_day
        if avail > 0:
            self.sell(self.symbol, avail, price=price)
            self.log(f"{day} {reason} qty={avail:.0f} 限价={price:.2f} {hold_txt}")
            self._reset_trade_state()
            if is_stop:
                self._on_stop_exit(day, bars_held=bars_held, buy_day=buy_day)
            else:
                self._reset_entry_gate()
            return True
        if pos > 0:
            self.log(
                f"{day} {reason} 跳过(T+1 买入日不可卖) avail=0 pos={pos:.0f} {hold_txt}"
            )
        return False

    def _tp_slice_qty(self, avail: float) -> float:
        """按初始仓位比例取整手减仓数量。"""
        base = float(self.initial_qty or 0)
        if base <= 0 or avail <= 0:
            return 0.0
        lot = float(self.lot_size)
        if float(self.take_profit_reduce or 0.0) >= 1.0 - 1e-12:
            return float(avail)
        raw = base * float(self.take_profit_reduce)
        qty = float(int(raw // lot) * lot)
        if qty < lot and avail >= lot:
            qty = lot
        return min(qty, float(avail))

    def _try_take_profits(
        self,
        *,
        day: str,
        high_px: float,
        close_px: float,
        avail: float,
        pos: float,
    ) -> tuple[float, float]:
        """止盈档：可选「档位+offset」挂单，仅摸到挂单价才减仓；可选抬止损。

        例：档15%、offset=2% → 限价按买入价×1.17；当日/持仓期内 high(或close)
        未到挂单价则该档本轮不减仓（挂单未成交）。
        prev_high 触发在开盘已处理，这里跳过。
        """
        if str(self.take_profit_trigger) == "prev_high":
            return avail, pos
        levels = self._effective_tp_levels(day)
        if (
            not levels
            or self.entry_price is None
            or float(self.entry_price) <= 0
        ):
            return avail, pos
        mark = close_px if self.take_profit_trigger == "close" else high_px
        offset = float(self.take_profit_limit_offset or 0.0)
        for i, lvl in enumerate(levels):
            if i in self.tp_done:
                continue
            # 挂单价 = 激活档 + offset；须摸到挂单价才成交
            limit_lvl = float(lvl) + offset
            tp_px = float(self.entry_price) * (1.0 + limit_lvl)
            if mark + 1e-12 < tp_px:
                continue
            self.tp_done.add(i)
            # 抬止损：锁住部分浮盈（相对买入价）
            if self.take_profit_lock_pct is not None and self.entry_price is not None:
                floor = float(self.entry_price) * (
                    1.0 + float(self.take_profit_lock_pct)
                )
                if self.stop_floor is None or floor > float(self.stop_floor):
                    self.stop_floor = floor
                    self.log(
                        f"{day} 止盈档+{float(lvl)*100:.0f}%抬止损下限@"
                        f"{floor:.2f}(锁+{float(self.take_profit_lock_pct)*100:.0f}%)"
                    )
            # 减仓（reduce=0 则只抬止损）
            if self.take_profit_reduce and self.take_profit_reduce > 0 and avail > 0:
                qty = self._tp_slice_qty(avail)
                if qty > 0:
                    self.sell(self.symbol, qty, price=tp_px)
                    avail -= qty
                    pos -= qty
                    self.log(
                        f"{day} 止盈档+{float(lvl)*100:.0f}%→挂+{limit_lvl*100:.0f}%成交 "
                        f"减仓{self.take_profit_reduce*100:.0f}% "
                        f"qty={qty:.0f} 限价={tp_px:.2f} "
                        f"(初始仓={float(self.initial_qty or 0):.0f}) "
                        f"{self._fmt_hold(tp_px)}"
                    )
            if avail <= 0 or pos <= 0:
                self._reset_trade_state()
                # 止盈全清视为打断连止损
                self._reset_entry_gate()
                return max(avail, 0.0), max(pos, 0.0)
        return avail, pos

    def _roll_prev_bars(
        self, open_px: float, close_px: float, high_px: float | None = None
    ) -> None:
        self.prev2_open = self.prev_open
        self.prev2_close = self.prev_close
        self.prev_open = open_px
        self.prev_close = close_px
        self.prev_high = float(high_px) if high_px is not None else None

    def _yang_blocked(self) -> bool:
        return should_block_entry_by_yang(
            self.prev2_open,
            self.prev2_close,
            self.prev_open,
            self.prev_close,
            tick=float(self.tick),
            ban_double_yang=bool(self.ban_double_yang),
            ban_single_yang=bool(self.ban_single_yang),
            yang_min_pct=float(self.yang_min_pct or 0.0),
            double_yang_second_min_pct=self.double_yang_second_min_pct,
            double_yang_combined_min_pct=self.double_yang_combined_min_pct,
            double_yang_combined_mode=str(
                getattr(
                    self,
                    "double_yang_combined_mode",
                    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                )
                or DEFAULT_DOUBLE_YANG_COMBINED_MODE
            ),
            single_yang_min_pct=self.single_yang_min_pct,
        )

    def _effective_tp_levels(self, day: str) -> tuple[float, ...]:
        if not bool(getattr(self, "regime_tp_enabled", False)):
            return tuple(self.take_profit_levels or ())
        regime = str((getattr(self, "regime_by_date", None) or {}).get(day, "sideways"))
        if regime == "bull":
            return tuple(getattr(self, "regime_tp_bull", ()) or ())
        if regime == "bear":
            return tuple(getattr(self, "regime_tp_bear", (0.10,)) or ())
        return tuple(getattr(self, "regime_tp_sideways", (0.15,)) or ())

    def _try_prev_high_take_profit(
        self,
        *,
        day: str,
        open_px: float,
        avail: float,
        pos: float,
    ) -> bool:
        """昨日最高价已触及止盈 → 今日开盘全清（无同日最高价前视）。"""
        if str(self.take_profit_trigger) != "prev_high":
            return False
        levels = self._effective_tp_levels(day)
        if (
            not levels
            or self.entry_price is None
            or float(self.entry_price) <= 0
            or self.prev_high is None
        ):
            return False
        offset = float(self.take_profit_limit_offset or 0.0)
        mark = float(self.prev_high)
        for lvl in levels:
            tp_px = float(self.entry_price) * (1.0 + float(lvl) + offset)
            if mark + 1e-12 < tp_px:
                continue
            return bool(
                self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=float(open_px),
                    reason=(
                        f"前日高点止盈+{float(lvl)*100:.0f}%"
                        f"(昨高={mark:.2f} 开盘={open_px:.2f})"
                    ),
                    is_stop=False,
                )
            )
        return False

    def _can_enter_by_prev_filter(self) -> bool:
        tick = float(self.tick)
        if self.prev_entry_mode != "any":
            if self.prev_open is None or self.prev_close is None:
                return False
            if not prev_day_allows_entry(
                self.prev_open,
                self.prev_close,
                prev_small_yang_pct=self.prev_small_yang_pct,
                prev_entry_mode=self.prev_entry_mode,
                tick=tick,
            ):
                return False
        if self._yang_blocked():
            return False
        return True

    def _try_enter(
        self,
        *,
        day: str,
        entry_px: float,
        open_px: float,
        high_px: float,
    ) -> bool:
        """空仓且过滤通过时按目标仓位限价买入。

        若启用跳买门控：gate=skip_next 时本笔有效买点跳过，并切到 take_next；
        take_next 买入后重置门控。
        """
        pos = float(self.get_position(self.symbol))
        if (not self.armed) or pos > 0:
            return False
        if not self._can_enter_by_prev_filter():
            return False
        energy_map = getattr(self, "energy_allowed_by_date", None) or {}
        if energy_map and not bool(energy_map.get(day, False)):
            self.log(
                f"{day} 动能门控未入选，跳过买入 "
                f"限价={entry_px:.2f} (open={open_px:.2f} high={high_px:.2f})"
            )
            return False
        halt_map = getattr(self, "halt_by_date", None) or {}
        if halt_map and bool(halt_map.get(day, False)):
            self.log(
                f"{day} 夏普衰减门控，跳过买入 "
                f"限价={entry_px:.2f} (open={open_px:.2f} high={high_px:.2f})"
            )
            return False

        gate = str(getattr(self, "entry_gate", "normal") or "normal")
        skip_on = self._entry_skip_enabled()
        if skip_on and gate == "skip_next":
            self.entry_gate = "take_next"
            why = (
                "隔日止损后"
                if self.skip_buy_after_overnight_stop
                else f"连止损{int(self.skip_buy_after_consec_stops or 0)}次后"
            )
            self.log(
                f"{day} {why}跳过本次买入 "
                f"限价={entry_px:.2f} (open={open_px:.2f} high={high_px:.2f}) "
                f"→ 下次买点才买入"
            )
            return False

        tgt = float(self.target_pct)
        self.order_target_percent(
            symbol=self.symbol,
            target_percent=tgt,
            price=entry_px,
        )
        self.armed = False
        self.entry_price = entry_px
        self.buy_day = day
        self.bars_held = 0
        gate_note = ""
        if skip_on and gate == "take_next":
            gate_note = " [跳买后恢复买入，重置门控]"
            self._reset_entry_gate()
        self.log(
            f"{day} 开盘+{self.entry_pct*100:.1f}%买入(全仓"
            f" target={tgt*100:.1f}%) 限价={entry_px:.2f} "
            f"(open={open_px:.2f} high={high_px:.2f}) 持有收益=+0.00%{gate_note}"
        )
        return True

    def _same_day_rebuy_ok(
        self,
        *,
        open_px: float,
        low_px: float,
        close_px: float,
        stop_px: float,
    ) -> bool:
        """止损当日尾盘再买过滤：可选收阳 / 高于止损价X点 / 距最低价反弹X点。"""
        if bool(self.rebuy_require_yang) and not is_yang(
            open_px, close_px, tick=float(self.tick)
        ):
            return False
        above = float(self.rebuy_above_stop_pct or 0.0)
        if close_px + 1e-12 < float(stop_px) * (1.0 + above):
            return False
        from_low = float(self.rebuy_from_low_pct or 0.0)
        if from_low > 0:
            base = float(open_px) if float(open_px) > 0 else float(stop_px)
            if base <= 0:
                return False
            if (float(close_px) - float(low_px)) / base + 1e-12 < from_low:
                return False
        return True

    def _try_same_day_rebuy_after_stop(
        self,
        *,
        day: str,
        open_px: float,
        high_px: float,
        low_px: float,
        close_px: float,
        stop_px: float,
    ) -> bool:
        """止损清仓后，若开启则按尾盘条件再买；买入日记为当日 → T+1 当日不可卖。"""
        if not bool(self.allow_same_day_rebuy_after_stop):
            return False
        # 刚 _exit_all 后引擎仓位可能尚未结算，以 armed/buy_day 为准
        if not self.armed or self.buy_day is not None:
            return False
        if not self._same_day_rebuy_ok(
            open_px=open_px, low_px=low_px, close_px=close_px, stop_px=stop_px
        ):
            return False

        px = float(close_px)
        if px <= 0:
            return False
        # 同日刚 sell 后，order_target_percent 易与未结算仓位打架；按购买力显式买
        lot = float(self.lot_size)
        try:
            bp = float(self.buying_power)
        except Exception:  # noqa: BLE001
            bp = 0.0
        budget = bp * float(self.target_pct)
        raw_qty = budget / px if px > 0 else 0.0
        qty = float(int(raw_qty // lot) * lot)
        if qty < lot:
            self.log(
                f"{day} 止损后尾盘再买资金不足 "
                f"bp={bp:.2f} px={px:.3f} target={self.target_pct*100:.1f}%"
            )
            return False
        oid = self.buy(self.symbol, qty, price=px)
        if not oid:
            self.log(f"{day} 止损后尾盘再买下单失败 qty={qty:.0f} px={px:.3f}")
            return False
        self.armed = False
        self.entry_price = px
        self.buy_day = day
        self.bars_held = 0
        self.initial_qty = qty
        self.same_day_rebuy_count = int(getattr(self, "same_day_rebuy_count", 0) or 0) + 1
        above = float(self.rebuy_above_stop_pct or 0.0)
        from_low = float(self.rebuy_from_low_pct or 0.0)
        yang_txt = "收阳+" if bool(self.rebuy_require_yang) else ""
        self.log(
            f"{day} 止损后尾盘再买({yang_txt}高于止损{above*100:.1f}点/"
            f"距低≥{from_low*100:.1f}点) "
            f"qty={qty:.0f} 限价={px:.3f} stop={stop_px:.3f} low={low_px:.3f} "
            f"oid={oid} 持有收益=+0.00%"
        )
        return True

    def on_bar(self, bar) -> None:
        if bar.symbol != self.symbol:
            return

        o = float(bar.open)
        h = float(bar.high)
        low = float(bar.low)
        c = float(bar.close)
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")

        bought_today = False
        try:
            pos = self._sync_position_state()
            # 买点基准：默认今日开盘；优化版在前日小阳时改用前日开盘
            entry_base = o
            if (
                self.entry_ref == "prev_open_on_small_yang"
                and self.prev_open is not None
                and self.prev_close is not None
                and is_yang(self.prev_open, self.prev_close, tick=float(self.tick))
                and prev_day_allows_entry(
                    self.prev_open,
                    self.prev_close,
                    prev_small_yang_pct=self.prev_small_yang_pct,
                    tick=float(self.tick),
                )
            ):
                entry_base = float(self.prev_open)
            entry_px = entry_trigger_price(
                entry_base, entry_pct=self.entry_pct, tick=self.tick
            )
            stop_px = stop_trigger_price(o, stop_pct=self.stop_pct, tick=self.tick)
            if self.stop_floor is not None:
                stop_px = max(float(stop_px), float(self.stop_floor))
            bull_today = self._is_bull_today(day)
            widen = float(getattr(self, "factor4_stop_widen_mult", 0.0) or 0.0)
            if bull_today and widen > 1.0 and bool(self.factor4_enabled):
                wide_pct = float(self.stop_pct) * widen
                stop_px_wide = stop_trigger_price(
                    o, stop_pct=wide_pct, tick=self.tick
                )
                if self.stop_floor is not None:
                    stop_px_wide = max(float(stop_px_wide), float(self.stop_floor))
                stop_px = min(float(stop_px), float(stop_px_wide))
            hit_entry = h + 1e-12 >= entry_px

            if self.armed and pos <= 0:
                if self._try_bull_entry(day=day, open_px=o):
                    bought_today = True
                elif bull_today and bool(self.factor4_skip_f1_entry_in_bull):
                    if hit_entry:
                        self.log(
                            f"{day} 因子4牛市跳过因子1买点 "
                            f"限价={entry_px:.2f} (open={o:.2f} high={h:.2f})"
                        )
                elif hit_entry:
                    if self._try_enter(
                        day=day, entry_px=entry_px, open_px=o, high_px=h
                    ):
                        bought_today = True
                    elif self.prev_entry_mode != "any" and (
                        self.prev_open is not None and self.prev_close is not None
                    ):
                        if not prev_day_allows_entry(
                            self.prev_open,
                            self.prev_close,
                            prev_small_yang_pct=self.prev_small_yang_pct,
                            prev_entry_mode=self.prev_entry_mode,
                            tick=float(self.tick),
                        ):
                            need = (
                                "须阴线(小阳次日不买)"
                                if self.prev_entry_mode == "yin_only"
                                else f"须阴线或小阳<{self.prev_small_yang_pct*100:.1f}%"
                            )
                            self.log(f"{day} 触及买点但前日不符({need}) skip")
                        elif self._yang_blocked():
                            self.log(f"{day} 触及买点但阳线过滤 skip")
                    elif self._yang_blocked():
                        self.log(f"{day} 触及买点但阳线过滤 skip")

            if not self.t0 and (bought_today or self.buy_day == day):
                return

            pos = float(self.get_position(self.symbol))
            avail = float(self.get_available_position(self.symbol))
            if pos <= 0 and avail <= 0:
                return
            if self.initial_qty is None and pos > 0:
                self.initial_qty = pos
            # 非买入日持仓：累计持有交易日（隔日止损判定用）
            if self.buy_day is not None and self.buy_day != day:
                self.bars_held = int(getattr(self, "bars_held", 0) or 0) + 1

            if self._try_prev_high_take_profit(
                day=day, open_px=o, avail=avail, pos=pos
            ):
                return

            # 同日：先兑现止盈（减仓/抬止损），再对余仓判止损
            avail, pos = self._try_take_profits(
                day=day, high_px=h, close_px=c, avail=avail, pos=pos
            )
            if pos <= 0 and avail <= 0:
                return
            if self.stop_floor is not None:
                stop_px = max(float(stop_px), float(self.stop_floor))
            hit_stop = low <= stop_px + 1e-12

            if hit_stop and bull_today and bool(self.factor4_enabled):
                widen_mult = float(getattr(self, "factor4_stop_widen_mult", 0.0) or 0.0)
                if widen_mult <= 1.0:
                    self.log(
                        f"{day} 因子4牛市持股：触止损 {stop_px:.2f} 暂不卖 "
                        f"(open={o:.2f} low={low:.2f}) {self._fmt_hold(c)}"
                    )
                    return

            if hit_stop:
                limit_state = limit_down_state(
                    prev_close=self.prev_close,
                    open_px=o,
                    high_px=h,
                    low_px=low,
                    close_px=c,
                    limit_down_pct=self.limit_down_pct,
                    tick=self.tick,
                )
                if bool(limit_state["locked"]):
                    self.log(
                        f"{day} 一字跌停封单，止损不可成交 "
                        f"(limit={float(limit_state['limit_px']):.2f}) 持仓延续"
                    )
                    return
                exit_px = float(
                    limit_state["limit_px"]
                    if bool(limit_state["opened"])
                    else stop_px
                )
                reason = (
                    f"跌停开板按跌停价止损"
                    f"(limit={exit_px:.2f} open={o:.2f} low={low:.2f})"
                    if bool(limit_state["opened"])
                    else (
                        f"开盘-{self.stop_pct*100:.1f}%止损"
                        f"(open={o:.2f} low={low:.2f})"
                    )
                )
                exited = self._exit_all(
                    day=day,
                    avail=avail,
                    pos=pos,
                    price=exit_px,
                    reason=reason,
                    is_stop=True,
                )
                if exited:
                    self._try_same_day_rebuy_after_stop(
                        day=day,
                        open_px=o,
                        high_px=h,
                        low_px=low,
                        close_px=c,
                        stop_px=float(stop_px),
                    )
                return
        finally:
            self._roll_prev_bars(o, c, h)


def _metric(metrics_df: pd.DataFrame, name: str) -> float:
    if name not in metrics_df.index:
        return float("nan")
    return float(metrics_df.loc[name, "value"])


metric = _metric


def print_summary(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    symbol_name: str,
    symbol: str,
    initial_cash: float,
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_value: float,
    misc_fee_rate: float | None = None,
    entry_pct: float = ENTRY_PCT,
    stop_pct: float = STOP_PCT,
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT,
) -> None:
    m = result.metrics_df
    c0 = float(data.iloc[0]["close"])
    c1 = float(data.iloc[-1]["close"])
    bh_pct = (c1 / c0 - 1.0) * 100.0

    print("\n========== 回测摘要 ==========")
    print(f"标的: {symbol_name} ({symbol})")
    print(f"区间: {data['date'].iloc[0]} → {data['date'].iloc[-1]}")
    print(f"日线根数: {len(data)}")
    print(f"买入: high>=ceil(open×{1+entry_pct:.3f})，止损 low<=floor(open×{1-stop_pct:.3f})")
    print(
        f"      前日须阴线或收盘严格<open×{1+prev_small_yang_pct:.3f}，"
        f"禁双阳跨日≥{DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT*100:.0f}%"
    )
    misc = MISC_FEE_RATE if misc_fee_rate is None else float(misc_fee_rate)
    print("卖出: 仅止损@触发价清仓；未触止损继续持有；买入日不卖（分档止盈见配置）")
    print(
        f"佣金: 万{commission_rate * 10000:.2f}；"
        f"杂费: 万{misc * 10000:.2f}（买卖）；"
        f"印花税(卖): 万{stamp_tax_rate * 10000:.1f}；"
        f"滑点: {slippage_value * 100:.1f}%"
    )
    print(f"总盈亏: {_metric(m, 'total_pnl'):.2f}")
    print(f"累计收益%: {_metric(m, 'total_return_pct'):.4f}")
    print(f"最大回撤%: {_metric(m, 'max_drawdown_pct'):.4f}")
    print(f"胜率%: {_metric(m, 'win_rate'):.4f}")
    print(f"闭环交易: {_metric(m, 'closed_trade_count'):.0f}")
    print(f"夏普: {_metric(m, 'sharpe_ratio'):.4f}")
    print(f"期末市值: {_metric(m, 'end_market_value'):.2f}")
    print(f"买入持有(首收→末收): {bh_pct:.2f}%  ({c0:.2f} → {c1:.2f})")
    print_yearly(result, data, initial_cash=initial_cash)
    print_monthly(result, data, initial_cash=initial_cash)

    if not result.executions_df.empty:
        print("\n--- 成交明细（节选前 40）---")
        cols = [
            c
            for c in ("symbol", "side", "quantity", "price", "commission", "timestamp")
            if c in result.executions_df.columns
        ]
        print(result.executions_df[cols].head(40).to_string(index=False))
        print(f"... 共 {len(result.executions_df)} 笔成交")


def print_yearly(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    initial_cash: float,
) -> None:
    prepared = _prepare_equity_and_close(result, data)
    if prepared is None:
        print("\n========== 分年数据 ==========")
        print("(无权益曲线，跳过)")
        return

    eq, px_daily = prepared
    exec_df = result.executions_df
    trades_df = result.trades_df if hasattr(result, "trades_df") else pd.DataFrame()

    years = sorted(set(eq.index.year.tolist()) | set(px_daily.index.year.tolist()))
    rows: list[dict[str, Any]] = []
    for y in years:
        eq_y = eq[eq.index.year == y]
        px_y = px_daily[px_daily.index.year == y]
        if eq_y.empty:
            continue
        end_eq = float(eq_y.iloc[-1])
        prev = eq[eq.index.year < y]
        base_eq = float(prev.iloc[-1]) if not prev.empty else initial_cash
        strat_pct = (end_eq / base_eq - 1.0) * 100.0 if base_eq > 0 else float("nan")

        if not px_y.empty:
            c0 = float(px_y.iloc[0])
            c1 = float(px_y.iloc[-1])
            prev_px = px_daily[px_daily.index.year < y]
            base_px = float(prev_px.iloc[-1]) if not prev_px.empty else c0
            bh_pct = (c1 / base_px - 1.0) * 100.0 if base_px > 0 else float("nan")
        else:
            c0 = c1 = bh_pct = float("nan")

        n_buy = n_sell = 0
        if exec_df is not None and not exec_df.empty and "timestamp" in exec_df.columns:
            ts = pd.to_datetime(exec_df["timestamp"])
            if getattr(ts.dt, "tz", None) is not None:
                ts = ts.dt.tz_convert("Asia/Shanghai")
            mask = ts.dt.year == y
            side = exec_df.loc[mask, "side"].astype(str).str.lower()
            n_buy = int((side == "buy").sum())
            n_sell = int((side == "sell").sum())

        n_closed = 0
        win_rate = float("nan")
        if trades_df is not None and not trades_df.empty:
            close_col = next(
                (
                    c
                    for c in ("exit_time", "close_time", "end_time", "timestamp")
                    if c in trades_df.columns
                ),
                None,
            )
            pnl_col = next(
                (c for c in ("pnl", "realized_pnl", "profit") if c in trades_df.columns),
                None,
            )
            if close_col is not None:
                cts = pd.to_datetime(trades_df[close_col])
                if getattr(cts.dt, "tz", None) is not None:
                    cts = cts.dt.tz_convert("Asia/Shanghai")
                tmask = cts.dt.year == y
                n_closed = int(tmask.sum())
                if pnl_col is not None and n_closed > 0:
                    pnls = pd.to_numeric(trades_df.loc[tmask, pnl_col], errors="coerce")
                    wins = (pnls > 0).sum()
                    win_rate = float(wins) / float(n_closed) * 100.0

        peak = eq_y.cummax()
        dd = (eq_y / peak - 1.0) * 100.0
        max_dd = float(dd.min()) if not dd.empty else float("nan")

        rows.append(
            {
                "年份": y,
                "策略收益%": round(strat_pct, 2),
                "买入持有%": round(bh_pct, 2) if bh_pct == bh_pct else None,
                "年初权益": round(base_eq, 2),
                "年末权益": round(end_eq, 2),
                "年内回撤%": round(max_dd, 2),
                "买入笔数": n_buy,
                "卖出笔数": n_sell,
                "闭环交易": n_closed,
                "胜率%": None if win_rate != win_rate else round(win_rate, 2),
                "首收": None if c0 != c0 else round(c0, 2),
                "末收": None if c1 != c1 else round(c1, 2),
            }
        )

    print("\n========== 分年数据 ==========")
    if not rows:
        print("(无)")
        return
    print(pd.DataFrame(rows).to_string(index=False))
    print("说明: 策略收益%=该年末权益/上年年末权益-1；首年相对 INITIAL_CASH。")
    print("     买入持有%=该年末收盘/上年年末收盘-1（首年用当年首收）。")


def _prepare_equity_and_close(
    result: aq.BacktestResult,
    data: pd.DataFrame,
) -> tuple[pd.Series, pd.Series] | None:
    eq = result.equity_curve_daily
    if eq is None or eq.empty:
        return None

    eq = eq.copy()
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq = eq.sort_index()

    px = data.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    else:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai")
    px = px.set_index("date").sort_index()
    px_daily = px["close"].resample("D").last().dropna()
    return eq, px_daily


def monthly_returns_df(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    initial_cash: float,
) -> pd.DataFrame:
    prepared = _prepare_equity_and_close(result, data)
    if prepared is None:
        return pd.DataFrame(columns=["月份", "策略收益%", "持有收益%"])

    eq, px_daily = prepared
    months = sorted(
        set(eq.index.to_period("M").astype(str).tolist())
        | set(px_daily.index.to_period("M").astype(str).tolist())
    )
    rows: list[dict[str, Any]] = []
    for month in months:
        period = pd.Period(month, freq="M")
        eq_m = eq[eq.index.to_period("M") == period]
        px_m = px_daily[px_daily.index.to_period("M") == period]
        if eq_m.empty and px_m.empty:
            continue

        if not eq_m.empty:
            end_eq = float(eq_m.iloc[-1])
            prev_eq = eq[eq.index.to_period("M") < period]
            base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else initial_cash
            strat_pct = (end_eq / base_eq - 1.0) * 100.0 if base_eq > 0 else float("nan")
        else:
            strat_pct = float("nan")

        if not px_m.empty:
            c0 = float(px_m.iloc[0])
            c1 = float(px_m.iloc[-1])
            prev_px = px_daily[px_daily.index.to_period("M") < period]
            base_px = float(prev_px.iloc[-1]) if not prev_px.empty else c0
            bh_pct = (c1 / base_px - 1.0) * 100.0 if base_px > 0 else float("nan")
        else:
            bh_pct = float("nan")

        rows.append(
            {
                "月份": month,
                "策略收益%": round(strat_pct, 2) if strat_pct == strat_pct else None,
                "持有收益%": round(bh_pct, 2) if bh_pct == bh_pct else None,
            }
        )
    return pd.DataFrame(rows)


def print_monthly(
    result: aq.BacktestResult,
    data: pd.DataFrame,
    *,
    initial_cash: float,
) -> None:
    df = monthly_returns_df(result, data, initial_cash=initial_cash)
    print("\n========== 分月数据 ==========")
    if df.empty:
        print("(无)")
        return
    print(df.to_string(index=False))
    print("说明: 策略收益%=该月末权益/上月末权益-1；首月相对 INITIAL_CASH。")
    print("     持有收益%=该月末收盘/上月末收盘-1（首月用当月首收）。")
