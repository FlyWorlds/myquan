"""1 分钟限价补槽：槽满挂单须回落到价；空槽突破当根成交。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "slot_limit_fill", _DIR / "slot_limit_fill.py"
)
assert _spec and _spec.loader
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
first_1m_limit_buy_fill = _m.first_1m_limit_buy_fill
limit_buy_fill_from_bar = _m.limit_buy_fill_from_bar
rank_1m_slot_fills = _m.rank_1m_slot_fills


def test_bar_no_fill_when_low_above_limit():
    assert (
        limit_buy_fill_from_bar(10.0, bar_open=10.40, bar_low=10.30) is None
    )


def test_bar_fills_at_open_when_gap_through_limit():
    assert limit_buy_fill_from_bar(10.0, bar_open=9.90, bar_low=9.80) == 9.9


def test_bar_fills_at_limit_when_dip_from_above():
    assert limit_buy_fill_from_bar(10.0, bar_open=10.20, bar_low=9.95) == 10.0


def test_queued_walks_1m_after_slot_free():
    bars = pd.DataFrame(
        [
            {"ts": "2026-09-15 09:35:00", "open": 10.00, "high": 10.30, "low": 9.98},
            {"ts": "2026-09-15 10:00:00", "open": 10.40, "high": 10.60, "low": 10.35},
            {"ts": "2026-09-15 10:06:00", "open": 10.20, "high": 10.25, "low": 9.97},
        ]
    )
    # 槽满期间 09:35 已触买，10:05 才腾槽：09:35 那根不能用来成交
    miss = first_1m_limit_buy_fill(
        bars, limit_px=10.0, since_ts="2026-09-15 10:05:00", require_pullback=True
    )
    assert miss is not None
    assert miss["fill_ts"] == "2026-09-15 10:06:00"
    assert miss["fill_px"] == 10.0
    never = first_1m_limit_buy_fill(
        bars.iloc[:2],
        limit_px=10.0,
        since_ts="2026-09-15 10:05:00",
        require_pullback=True,
    )
    assert never is None


def test_fresh_breakout_uses_high_not_pullback():
    bars = pd.DataFrame(
        [
            {
                "ts": "2026-09-15 10:08:00",
                "open": 16.10,
                "high": 16.20,
                "low": 16.08,
            }
        ]
    )
    hit = first_1m_limit_buy_fill(
        bars, limit_px=16.05, since_ts="2026-09-15 10:08:00", require_pullback=False
    )
    assert hit is not None
    assert hit["fill_px"] == 16.05
    miss = first_1m_limit_buy_fill(
        bars, limit_px=16.05, since_ts="2026-09-15 10:08:00", require_pullback=True
    )
    assert miss is None


def test_rank_same_minute_earlier_trigger_wins():
    fills = [
        {
            "code": "000021",
            "fill_px": 16.0,
            "fill_ts": "2026-09-15 10:06:00",
            "trigger_ts": "2026-09-15 10:06:00",
        },
        {
            "code": "002068",
            "fill_px": 8.48,
            "fill_ts": "2026-09-15 10:06:00",
            "trigger_ts": "2026-09-15 09:40:00",
        },
        {
            "code": "600869",
            "fill_px": 23.78,
            "fill_ts": "2026-09-15 10:07:00",
            "trigger_ts": "2026-09-15 09:35:00",
        },
    ]
    one = rank_1m_slot_fills(fills, free=1, buys_left=3)
    assert [x["code"] for x in one] == ["002068"]
    two = rank_1m_slot_fills(fills, free=2, buys_left=3)
    assert [x["code"] for x in two] == ["002068", "000021"]


if __name__ == "__main__":
    test_bar_no_fill_when_low_above_limit()
    test_bar_fills_at_open_when_gap_through_limit()
    test_bar_fills_at_limit_when_dip_from_above()
    test_queued_walks_1m_after_slot_free()
    test_fresh_breakout_uses_high_not_pullback()
    test_rank_same_minute_earlier_trigger_wins()
    print("ok")
