"""Strategy 1's additional opening-price protection (observed quotes only)."""
from strategy.open_break import floor_to_tick


def morning_stop_price(open_px, clock, *, tick=.01):
    """09:30 inclusive, 10:00 exclusive; sell ticks at/below open × 99%."""
    if not "09:30:00" <= clock < "10:00:00" or open_px <= 0:
        return None
    return floor_to_tick(open_px * .99, tick=tick)
