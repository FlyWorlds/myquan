"""Presentation labels for confirmed holdings; never grants sell availability."""
from datetime import date


def held_position_status(buy_time, session):
    """Only a confirmed purchase on the row's session is labelled already bought."""
    try:
        bought = date.fromisoformat(str(buy_time or "")[:10])
        current = date.fromisoformat(str(session or "")[:10])
    except ValueError:
        return "持有"
    return "已经买入" if bought == current else "持有"
