"""Pure factor26 state transition for received quotes, independent of minute IO."""
from __future__ import annotations

import math
from datetime import datetime

from condition_buy import fresh_quote, timestamp
from strategy.pullback_wave_stop import eval_factor26_quote, resolve_t1_overnight_note
from strategy.open_break import limit_down_state
from strategy.board_rules import limit_down_pct_of


def overnight_note_updates(pos, quote, session):
    """Restore the prior close's T+1 note without replaying an unseen price path."""
    bought = str(pos.get("buy_time") or "")[:10]
    if not bought or bought >= session or pos.get("quote_exit_session") == session:
        return {}
    try:
        previous, cost = float(quote.get("prev_close") or 0), float(pos.get("cost") or 0)
        if not all(math.isfinite(v) and v > 0 for v in (previous, cost)):
            return {}
        note = resolve_t1_overnight_note(cost_px=cost, peak_high=float(pos.get("peak_high") or cost),
                                         close_px=previous, bar_low=None)
        noted_session = pos.get("quote_exit_session") or pos.get("stop_noted_session")
        if noted_session and str(noted_session) >= session:
            noted_session = None
        return dict(stop_noted=note.get("noted_px") is not None, stop_noted_px=note.get("noted_px"),
            stop_noted_session=noted_session if note.get("noted_px") is not None else None,
            stop_note_source="official_previous_close")
    except (TypeError, ValueError, OverflowError):
        return {}


def evaluate_quote_exit(pos: dict, quote: dict, *, session: str, now: datetime,
                        received_at: datetime, vol20_daily=None, tick=.01) -> dict | None:
    if not fresh_quote(quote, session, now) or not 0 <= (now-received_at).total_seconds() <= 5:
        return None
    clock = str(quote["last_ts"])[11:19]
    if not ("09:30:00" <= clock <= "11:30:00" or "13:00:00" <= clock < "15:00:00"):
        return None
    try:
        qty, cost = int(pos.get("qty") or 0), float(pos.get("cost") or 0)
        bought = timestamp(pos.get("buy_time"))
        at = timestamp(quote["last_ts"])
        if qty <= 0 or not math.isfinite(cost) or cost <= 0 or not bought or at < bought:
            return None
        peak_at = timestamp(pos.get("peak_high_at"))
        if peak_at and peak_at > at:
            return None
        watermark = pos.get("quote_exit_watermark") or {}
        if watermark.get("cycle") == pos.get("buy_time"):
            previous = timestamp(watermark.get("time"))
            if previous and (at < previous or (at == previous and watermark.get("price") == quote["last"] and watermark.get("high", pos.get("peak_high")) == quote.get("high"))):
                return None
        overnight = bought.date().isoformat() < session
        available = int(pos.get("available") or 0)
        if overnight and available <= 0:
            available = qty
        available = min(qty, available)
        if not overnight:
            available = 0
        limit = limit_down_state(prev_close=quote.get("prev_close"), open_px=float(quote["open"]),
            high_px=float(quote["high"]), low_px=float(quote["low"]), close_px=float(quote["last"]),
            limit_down_pct=limit_down_pct_of(str(pos.get("code") or "")), tick=tick)
        executable = available > 0 and not pos.get("hold_lock") and not limit["locked"]
        # Daily high belongs entirely to this holding only for overnight positions.
        # For same-day entries it can precede the purchase; keep observed prices.
        holding_peak = max(cost, float(pos.get("peak_high") or cost),
                           float(quote["high"]) if overnight else 0)
        result = eval_factor26_quote(price=float(quote["last"]), cost_px=cost,
            peak_before=holding_peak, shares=available or qty,
            tp_stage=int(pos.get("tp_stage") or 0), can_sell=executable,
            overnight_armed=overnight and bool(pos.get("stop_noted")), day_open=float(quote["open"]),
            session_peak_before=float(pos.get("quote_session_peak") or 0) if pos.get("quote_exit_session") == session else 0,
            vol20_daily=vol20_daily, tick=tick)
        updates = dict(quote_exit_session=session, available=min(qty, available),
                       peak_high=result["peak_after"], quote_session_peak=result["session_peak_after"])
        if result.get("tp_marked") and not available and result.get("noted_px"):
            updates.update(stop_noted=True, stop_noted_px=result["noted_px"], stop_noted_session=session)
        if not overnight:
            low = min(float(pos.get("quote_cycle_low") or cost), float(quote["last"]))
            updates["quote_cycle_low"] = low
            note = resolve_t1_overnight_note(cost_px=cost, peak_high=result["peak_after"],
                close_px=float(quote["last"]), bar_low=low, tick=tick)
            if note["reason"] == "profit_ge_3pct":
                updates.update(stop_noted=False, stop_noted_px=None, stop_noted_session=None)
            elif note.get("noted_px") and (note["reason"] == "hard_from_cost" or clock >= "14:57:00"):
                updates.update(stop_noted=True, stop_noted_px=note["noted_px"], stop_noted_session=session)
        action = result.get("action")
        if action:
            action = dict(action, shares=min(available, int(action["shares"])))
        return dict(updates=updates, action=action,
                    watermark=dict(cycle=pos.get("buy_time"), time=quote["last_ts"], price=quote["last"], high=quote.get("high")))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
