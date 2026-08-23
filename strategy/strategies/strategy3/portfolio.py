"""策略三组合执行：因子5事件候选建仓 + 因子1止损 + 空槽每日补仓。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategy.open_break import DEFAULT_PCT, stop_trigger_price
from strategy.strategies._unreg_s6.portfolio import COMMISSION, LOT, SLIP, STAMP


def _equity(
    *,
    cash: float,
    positions: list[dict[str, Any] | None],
    closes: pd.DataFrame,
    date: pd.Timestamp,
) -> float:
    value = cash
    for position in positions:
        if position is None:
            continue
        symbol = position["symbol"]
        if symbol in closes.columns and pd.notna(closes.at[date, symbol]):
            value += int(position["shares"]) * float(closes.at[date, symbol])
    return value


def simulate_factor5_event_slots_f1_stop(
    *,
    opens: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    picks: dict[pd.Timestamp, list[str]],
    bt_start: pd.Timestamp,
    max_positions: int = 5,
    stop_pct: float = DEFAULT_PCT,
    use_factor1_stop: bool = True,
    hold_days: int | None = None,
    code_themes: dict[str, str] | None = None,
    initial_cash: float = 1_000_000.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """模拟五固定槽位的事件建仓与因子1止损。

    ``picks[T]`` 为 T 日收盘后已知的因子5候选，在下一交易日开盘参与补仓。
    候选池只在有新事件时更新；无新事件时，未买入的上一次候选可用于每日补仓。
    当日开盘先填补已知空槽，盘中才判断止损，因此盘中止损释放的槽位最早次日
    开盘补回，避免以未来的盘中信息回填开盘成交。
    """
    max_positions = max(1, int(max_positions))
    all_dates = [pd.Timestamp(day) for day in closes.index]
    positions: list[dict[str, Any] | None] = [None] * max_positions
    cash = float(initial_cash)
    active_pool: list[str] = []
    pool_signal_date: pd.Timestamp | None = None
    blocked_symbols: set[str] = set()
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    n_event_entries = n_daily_entries = n_stops = n_replacements = 0
    code_themes = dict(code_themes or {})

    for day_i, day in enumerate(all_dates):
        if day < pd.Timestamp(bt_start):
            continue

        def exit_at_open(slot: int, reason: str) -> None:
            nonlocal cash, n_replacements
            position = positions[slot]
            if position is None:
                return
            symbol = position["symbol"]
            if symbol not in opens.columns or pd.isna(opens.at[day, symbol]):
                return
            open_price = float(opens.at[day, symbol])
            if open_price <= 0:
                return
            fill_price = open_price * (1.0 - SLIP)
            proceeds = int(position["shares"]) * fill_price
            fee = proceeds * (COMMISSION + STAMP)
            cash += proceeds - fee
            trade_rows.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "side": "sell",
                    "shares": position["shares"],
                    "price": fill_price,
                    "slot": slot,
                    "reason": reason,
                    "signal_date": position["entry_signal_date"],
                }
            )
            positions[slot] = None
            blocked_symbols.add(symbol)
            if reason in {"concept_replace", "new_theme_replace"}:
                n_replacements += 1

        # 到期退出在开盘处理，释放的槽位可在同一开盘按已知事件候选补入。
        if hold_days is not None:
            for slot, position in enumerate(positions):
                if position is not None and day_i - int(position["entry_i"]) >= int(hold_days):
                    exit_at_open(slot, "time_exit")

        prev_day = all_dates[day_i - 1] if day_i else None
        event_codes = list(dict.fromkeys(picks.get(prev_day, []))) if prev_day is not None else []
        if event_codes:
            active_pool = event_codes
            pool_signal_date = prev_day
            # 新事件才允许重新评估上一次候选池中已退出的同一代码。
            blocked_symbols.clear()

        # 新事件换仓：同主题替换旧票；不同主题且满仓时替换最早进入候选池的票。
        if event_codes:
            for symbol in event_codes:
                if any(pos is not None and pos["symbol"] == symbol for pos in positions):
                    continue
                theme = code_themes.get(symbol, "")
                same_theme = [
                    slot
                    for slot, pos in enumerate(positions)
                    if pos is not None and theme and pos.get("theme") == theme
                ]
                if same_theme:
                    old_slot = min(same_theme, key=lambda slot: int(positions[slot]["entry_i"]))  # type: ignore[index]
                    exit_at_open(old_slot, "concept_replace")
                elif all(pos is not None for pos in positions):
                    old_slot = min(
                        range(max_positions),
                        key=lambda slot: int(positions[slot]["entry_i"]),  # type: ignore[index]
                    )
                    exit_at_open(old_slot, "new_theme_replace")

        # 开盘时按新事件或存量候选池填补空槽。
        held_symbols = {pos["symbol"] for pos in positions if pos is not None}
        empty_slots = [idx for idx, pos in enumerate(positions) if pos is None]
        entry_reason = "event_entry" if event_codes else "daily_replenish"
        for symbol in active_pool:
            if not empty_slots:
                break
            if (
                symbol in held_symbols
                or symbol in blocked_symbols
                or symbol not in opens.columns
                or pd.isna(opens.at[day, symbol])
            ):
                continue
            open_price = float(opens.at[day, symbol])
            if open_price <= 0:
                continue
            portfolio_equity = _equity(cash=cash, positions=positions, closes=closes, date=day)
            target_value = portfolio_equity / max_positions
            fill_price = open_price * (1.0 + SLIP)
            shares = int(target_value // (fill_price * LOT)) * LOT
            if shares <= 0:
                continue
            cost = shares * fill_price
            fee = cost * COMMISSION
            if cost + fee > cash:
                continue
            slot = empty_slots.pop(0)
            cash -= cost + fee
            positions[slot] = {
                "symbol": symbol,
                "shares": shares,
                "entry_i": day_i,
                "entry_signal_date": pool_signal_date,
                "theme": code_themes.get(symbol, ""),
            }
            held_symbols.add(symbol)
            trade_rows.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "side": "buy",
                    "shares": shares,
                    "price": fill_price,
                    "slot": slot,
                    "reason": entry_reason,
                    "signal_date": pool_signal_date,
                }
            )
            if entry_reason == "event_entry":
                n_event_entries += 1
            else:
                n_daily_entries += 1

        # T+1 后可选执行因子1盘中止损；固定期限已在开盘先行处理。
        for slot, position in enumerate(positions):
            if position is None or day_i <= int(position["entry_i"]):
                continue
            symbol = position["symbol"]
            if (
                symbol not in opens.columns
                or symbol not in lows.columns
                or pd.isna(opens.at[day, symbol])
                or pd.isna(lows.at[day, symbol])
            ):
                continue
            open_price = float(opens.at[day, symbol])
            low_price = float(lows.at[day, symbol])
            if open_price <= 0:
                continue
            held_days = day_i - int(position["entry_i"])
            reason: str | None = None
            raw_fill = open_price
            if use_factor1_stop:
                stop_price = stop_trigger_price(open_price, stop_pct=stop_pct)
                if low_price <= stop_price + 1e-12:
                    raw_fill = open_price if open_price <= stop_price + 1e-12 else stop_price
                    reason = "factor1_stop"
            if reason is None:
                continue
            fill_price = raw_fill * (1.0 - SLIP)
            proceeds = int(position["shares"]) * fill_price
            fee = proceeds * (COMMISSION + STAMP)
            cash += proceeds - fee
            trade_rows.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "side": "sell",
                    "shares": position["shares"],
                    "price": fill_price,
                    "slot": slot,
                    "reason": reason,
                    "signal_date": position["entry_signal_date"],
                }
            )
            positions[slot] = None
            blocked_symbols.add(symbol)
            if reason == "factor1_stop":
                n_stops += 1

        equity = _equity(cash=cash, positions=positions, closes=closes, date=day)
        occupied = sum(position is not None for position in positions)
        equity_rows.append(
            {
                "date": day,
                "equity": equity,
                "cash": cash,
                "cash_pct": cash / equity if equity > 0 else np.nan,
                "occupied_slots": occupied,
                "empty_slots": max_positions - occupied,
            }
        )
        slot_rows.append(
            {
                "date": day,
                "occupied_slots": occupied,
                "empty_slots": max_positions - occupied,
                "active_pool": ",".join(active_pool),
                "pool_signal_date": pool_signal_date,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trade_rows)
    slots_df = pd.DataFrame(slot_rows)
    if equity_df.empty:
        return equity_df, trades_df, slots_df, {"error": "no equity"}
    equity_values = equity_df["equity"].to_numpy(dtype=float)
    returns = np.diff(equity_values) / np.where(equity_values[:-1] == 0, np.nan, equity_values[:-1])
    returns = returns[np.isfinite(returns)]
    peak = np.maximum.accumulate(equity_values)
    drawdown = (peak - equity_values) / np.where(peak == 0, np.nan, peak)
    stats = {
        "start": str(equity_df["date"].iloc[0].date()),
        "end": str(equity_df["date"].iloc[-1].date()),
        "total_return_pct": float(equity_values[-1] / initial_cash - 1.0) * 100,
        "max_drawdown_pct": float(np.nanmax(drawdown)) * 100 if len(drawdown) else 0.0,
        "sharpe": (
            float(np.mean(returns) / np.std(returns) * np.sqrt(252))
            if len(returns) and np.std(returns) > 1e-12
            else 0.0
        ),
        "end_equity": float(equity_values[-1]),
        "n_buys": int((trades_df["side"] == "buy").sum()) if not trades_df.empty else 0,
        "n_factor1_stops": n_stops,
        "n_replacements": n_replacements,
        "n_time_exits": (
            int((trades_df["reason"] == "time_exit").sum()) if not trades_df.empty else 0
        ),
        "n_event_entries": n_event_entries,
        "n_daily_replenishments": n_daily_entries,
        "max_positions": max_positions,
        "stop_pct": stop_pct,
        "use_factor1_stop": use_factor1_stop,
        "hold_days": hold_days,
    }
    return equity_df, trades_df, slots_df, stats


__all__ = ["simulate_factor5_event_slots_f1_stop"]
