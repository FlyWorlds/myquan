"""因子4 · 动量：akquant Strategy（收盘信号 → NextOpen 成交）。"""

from __future__ import annotations

from typing import Any

from akquant import Strategy

from strategy.momentum import DEFAULT_KIND, DEFAULT_PARAMS, build_momentum_signals


class MomentumStrategy(Strategy):
    """单因子动量：当日收盘目标仓位，下一根 K 开盘成交。"""

    symbol: str = "sh600552"
    symbol_name: str = "凯盛科技"
    target_pct: float = 0.95
    lot_size: int = 100
    start_date: str = "20200101"
    end_date: str = ""
    slippage_value: float = 0.001
    t0: bool = False
    tick: float = 0.01
    mom_kind: str = DEFAULT_KIND
    mom_params: dict[str, Any] | None = None
    # date(YYYY-MM-DD) → 0/1（当日收盘确认目标）
    _target_map: dict[str, float] | None = None

    def on_start(self) -> None:
        self.subscribe(self.symbol)
        # 已提交、等待 NextOpen 成交的目标仓位；避免连日重复下单
        self._submitted_target: float | None = None
        kind = self.mom_kind or DEFAULT_KIND
        params = self.mom_params or DEFAULT_PARAMS
        self.log(
            f"因子4·动量 kind={kind} params={params} "
            f"target={self.target_pct*100:.1f}% T+{'0' if self.t0 else '1'} "
            f"成交=NextOpen 滑点{self.slippage_value*100:.1f}%"
        )

    def on_bar(self, bar) -> None:
        if bar.symbol != self.symbol:
            return
        day = self.to_local_time(bar.timestamp).strftime("%Y-%m-%d")
        c = float(bar.close)
        target_map = self._target_map or {}
        tgt = float(target_map.get(day, 0.0) or 0.0)
        want_long = tgt >= 0.5
        desired = float(self.target_pct) if want_long else 0.0

        pos = float(self.get_position(self.symbol))
        long_now = pos > 1e-8

        # 仓位已与目标一致，清除挂单记忆
        if want_long and long_now:
            self._submitted_target = desired
            return
        if (not want_long) and (not long_now):
            self._submitted_target = 0.0
            return

        # 已提交相同目标、等待 NextOpen，不再重复报单
        if self._submitted_target is not None and abs(
            float(self._submitted_target) - desired
        ) < 1e-9:
            return

        self.order_target_percent(
            symbol=self.symbol,
            target_percent=desired,
            price=c,
        )
        self._submitted_target = desired
        action = "开仓" if want_long else "平仓"
        self.log(
            f"{day} 动量信号{action} target={desired*100:.1f}% "
            f"close={c:.2f} → 下一交易日开盘成交"
        )


def prepare_momentum_signals(cfg: Any, daily) -> None:
    """pipeline prepare：预计算收盘目标仓位。"""
    kind = getattr(cfg, "mom_kind", DEFAULT_KIND) or DEFAULT_KIND
    params = getattr(cfg, "mom_params", None) or dict(DEFAULT_PARAMS)
    sig = build_momentum_signals(daily, kind=kind, params=params)
    m: dict[str, float] = {}
    for _, row in sig.iterrows():
        d = row["date"]
        key = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        v = row["mom_target"]
        if v == v:
            m[key] = float(v)
    cfg._mom_target_map = m  # type: ignore[attr-defined]


def apply_momentum_config(strategy: Strategy, cfg: Any) -> Strategy:
    strategy.symbol = cfg.symbol
    strategy.symbol_name = cfg.symbol_name
    strategy.target_pct = cfg.target_pct
    strategy.lot_size = cfg.lot_size
    strategy.start_date = cfg.start_date
    strategy.end_date = cfg.end_date
    strategy.slippage_value = cfg.slippage_value
    strategy.t0 = bool(cfg.t0)
    strategy.tick = float(getattr(cfg, "tick", 0.01) or 0.01)
    strategy.mom_kind = getattr(cfg, "mom_kind", DEFAULT_KIND) or DEFAULT_KIND
    strategy.mom_params = dict(getattr(cfg, "mom_params", None) or DEFAULT_PARAMS)
    strategy._target_map = dict(getattr(cfg, "_mom_target_map", {}) or {})
    return strategy


__all__ = [
    "MomentumStrategy",
    "prepare_momentum_signals",
    "apply_momentum_config",
]
