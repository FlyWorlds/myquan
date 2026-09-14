"""三槽持仓辅助函数单测。"""

from __future__ import annotations

from watch_config import (
    MAX_PORTFOLIO_SLOTS,
    SLOT_FIRST_TIER_MAX_OVERSHOOT,
    SLOT_WEIGHT,
    append_slot_freed_at,
    free_slot_count,
    occupied_slot_codes,
    peek_slot_freed_at,
    pop_slot_freed_at,
    slot_fill_decision,
    slot_meta,
)


def test_occupied_ignores_realized_and_zero_qty():
    holdings = {
        "positions": {
            "600552": {"qty": 400, "name": "凯盛科技"},
            "600338": {"qty": 0, "name": "西藏珠峰", "pool": True},
        },
        "realized_today": {
            "600330": {"session": "2026-09-07", "qty": 100, "reason": "止损"},
        },
        "portfolio_pool": ["600552", "600338"],
    }
    assert occupied_slot_codes(holdings) == ["600552"]
    assert free_slot_count(holdings) == MAX_PORTFOLIO_SLOTS - 1
    meta = slot_meta(holdings)
    assert meta["max"] == 3
    assert meta["weight"] == SLOT_WEIGHT
    assert meta["free"] == 2
    assert meta["occupiedCount"] == 1


def test_slot_fill_fresh_empty_uses_signal_px():
    dec = slot_fill_decision(
        signal_px=10.0,
        last_px=9.80,
        trigger_ts="2026-09-14 09:40:00",
        freed_at=None,
    )
    assert dec is not None
    assert dec["kind"] == "signal"
    assert abs(float(dec["fill_px"]) - 10.0) < 1e-9


def test_slot_fill_first_tier_uses_last_within_1pct():
    assert abs(SLOT_FIRST_TIER_MAX_OVERSHOOT - 0.01) < 1e-12
    dec = slot_fill_decision(
        signal_px=10.0,
        last_px=9.85,
        trigger_ts="2026-09-14 09:40:00",
        freed_at="2026-09-14 10:30:00",
    )
    assert dec is not None
    assert dec["kind"] == "last"
    assert abs(float(dec["fill_px"]) - 9.85) < 1e-9
    over = slot_fill_decision(
        signal_px=10.0,
        last_px=10.08,
        trigger_ts="2026-09-14 09:40:00",
        freed_at="2026-09-14 10:30:00",
    )
    assert over is not None
    assert over["kind"] == "last"
    assert abs(float(over["fill_px"]) - 10.08) < 1e-9
    too_high = slot_fill_decision(
        signal_px=10.0,
        last_px=10.11,
        trigger_ts="2026-09-14 09:40:00",
        freed_at="2026-09-14 10:30:00",
    )
    assert too_high is None


def test_slot_fill_after_close_uses_signal_px():
    dec = slot_fill_decision(
        signal_px=21.07,
        last_px=21.20,
        trigger_ts="2026-09-14 09:40:17",
        freed_at="2026-09-14 09:30:00",
    )
    assert dec is not None
    assert dec["kind"] == "signal"
    assert abs(float(dec["fill_px"]) - 21.07) < 1e-9


def test_slot_queue_freed_at_fifo():
    h: dict = {}
    append_slot_freed_at(h, "2026-09-14", "2026-09-14 09:30:00")
    append_slot_freed_at(h, "2026-09-14", "2026-09-14 10:08:00")
    assert peek_slot_freed_at(h, "2026-09-14") == "2026-09-14 09:30:00"
    assert pop_slot_freed_at(h, "2026-09-14") == "2026-09-14 09:30:00"
    assert peek_slot_freed_at(h, "2026-09-14") == "2026-09-14 10:08:00"
    pop_slot_freed_at(h, "2026-09-14")
    assert peek_slot_freed_at(h, "2026-09-14") is None


def test_today_slot_buy_ranks_first_touch_wins():
    from index import today_slot_buy_ranks

    text = "\n".join(
        [
            '{"time": "2026-09-08 09:47:34", "side": "buy", "code": "002093", "note": "槽位触买(自动·3成)"}',
            '{"time": "2026-09-08 09:47:34", "side": "buy", "code": "002104", "note": "槽位触买(自动·3成)"}',
            '{"time": "2026-09-08 09:47:34", "side": "buy", "code": "002015", "note": "槽位触买(自动·3成)"}',
            '{"time": "2026-09-08 11:11:57", "side": "buy", "code": "002093", "note": "槽位触买(自动·3成)"}',
            '{"time": "2026-09-08 10:00:00", "side": "buy", "code": "603626", "note": "用户确认持有"}',
        ]
    )
    ranks = today_slot_buy_ranks("2026-09-08", text=text)
    assert ranks == {"002093": 0, "002104": 1, "002015": 2}


def test_row_trigger_ts_orders_slot_queue():
    from index import _row_trigger_ts

    a = {"交易日": "2026-09-14", "信号时刻": "2026-09-14 09:31:02"}
    b = {"交易日": "2026-09-14", "买信号时间": "09:40:17"}
    c = {"交易日": "2026-09-14"}
    assert _row_trigger_ts(a) < _row_trigger_ts(b) < _row_trigger_ts(c)


def test_sellable_overnight_available_zero_unlocks():
    from watch_config import sellable_qty, unlock_overnight_available

    pos = {"qty": 1000, "available": 0, "buy_time": "2026-09-07 09:31:00"}
    assert sellable_qty(pos, 1000, pos["buy_time"], "2026-09-08") == 1000
    pos_t1 = {"qty": 1000, "available": 0, "buy_time": "2026-09-08 09:31:00"}
    assert sellable_qty(pos_t1, 1000, pos_t1["buy_time"], "2026-09-08") == 0
    data = {
        "positions": {
            "000070": {"qty": 5500, "available": 0, "buy_time": "2026-09-11 09:43:32"}
        }
    }
    assert unlock_overnight_available(data, "2026-09-14") is True
    assert data["positions"]["000070"]["available"] == 5500


def test_market_phase_lunch_and_close():
    from datetime import datetime

    from watch_config import is_close_confirmed, is_signal_window, market_phase

    assert market_phase(datetime(2026, 9, 8, 10, 0)) == "continuous"
    assert market_phase(datetime(2026, 9, 8, 11, 45)) == "lunch"
    assert is_signal_window(datetime(2026, 9, 8, 11, 45)) is False
    assert market_phase(datetime(2026, 9, 8, 13, 10)) == "continuous"
    assert market_phase(datetime(2026, 9, 8, 15, 1)) == "closed"
    assert is_signal_window(datetime(2026, 9, 8, 15, 1)) is False
    assert is_close_confirmed(datetime(2026, 9, 8, 14, 56)) is False
    assert is_close_confirmed(datetime(2026, 9, 8, 14, 57)) is True


def test_forming_minute_skips_live_low_against_raised_peak():
    import pandas as pd
    from index import _bars_cover_current_minute

    ts = pd.Timestamp("2026-09-08 11:20:00")
    bars = pd.DataFrame([{"ts": ts, "high": 31.0, "low": 29.7}])
    assert _bars_cover_current_minute(bars, now=pd.Timestamp("2026-09-08 11:20:40")) is True
    assert _bars_cover_current_minute(bars, now=pd.Timestamp("2026-09-08 11:21:05")) is False


def test_full_slots():
    holdings = {
        "positions": {
            "600552": {"qty": 100},
            "600301": {"qty": 200},
            "002104": {"qty": 300},
        }
    }
    assert free_slot_count(holdings) == 0
    assert len(occupied_slot_codes(holdings)) == 3


def test_stop_trace_in_slot_area_not_occupying():
    """已平仓：槽位留痕不占槽；实仓仍可满 3。"""
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600552", "名称": "凯盛", "持仓": 100, "持仓状态": "已经买入", "距买点%": 1},
        {"代码": "600301", "名称": "华锡", "持仓": 100, "持仓状态": "已经买入", "距买点%": 2},
        {"代码": "601020", "名称": "华钰", "持仓": 100, "持仓状态": "已经买入", "距买点%": 3},
        {
            "代码": "600330",
            "名称": "天通",
            "持仓": 0,
            "持仓状态": "已平仓",
            "已实现": True,
            "预警": "已触止损",
            "距买点%": 0,
        },
    ]
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "600301", "601020", "600330"},
        strategy_codes={"600552", "600301", "601020", "600330"},
        phase="continuous",
    )
    pinned = [r for r in picked if r.get("置顶")]
    traces = [r for r in picked if r.get("槽位留痕")]
    assert len(pinned) == 3
    assert all(int(r.get("持仓") or 0) > 0 for r in pinned)
    assert len(traces) == 1
    assert traces[0]["代码"] == "600330"
    assert traces[0].get("槽位占用") is False
    assert traces[0].get("置顶") is False


def test_stop_trace_visible_outside_continuous():
    """盘前/收盘：已平仓留痕仍进持仓 Tab（次日才清）。"""
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600552", "名称": "凯盛", "持仓": 100, "持仓状态": "已经买入"},
        {
            "代码": "600330",
            "名称": "天通",
            "持仓": 0,
            "持仓状态": "已平仓",
            "已实现": True,
            "预警": "已触止损",
        },
        {
            "代码": "002104",
            "名称": "恒宝",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "将买入",
            "近买点": True,
        },
    ]
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "600330"},
        strategy_codes={"600552", "600330", "002104"},
        phase="pre_auction",
    )
    codes = [r["代码"] for r in picked]
    assert "600552" in codes
    assert "600330" in codes
    assert "002104" not in codes
    assert next(r for r in picked if r["代码"] == "600330").get("槽位留痕") is True


def test_lunch_keeps_buy_alert_in_holdings():
    """午休：已触买仍进持仓预警栏，不因非连续竞价被藏掉。"""
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600552", "名称": "凯盛", "持仓": 100, "持仓状态": "已经买入"},
        {
            "代码": "600330",
            "名称": "天通",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "已触买·槽满",
            "已触买": "是",
            "当日预警": True,
            "槽位候选": True,
            "过门OK": True,
        },
    ]
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "600330"},
        strategy_codes={"600552", "600330"},
        phase="lunch",
    )
    codes = [str(r["代码"]) for r in picked]
    assert "600552" in codes
    assert "600330" in codes
    closed = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "600330"},
        strategy_codes={"600552", "600330"},
        phase="closed",
    )
    assert "600330" in [str(r["代码"]) for r in closed]


def test_closed_keeps_buy_hit_drops_near_buy():
    """收盘：已触买留在预警栏；将买入等接近信号不留。"""
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600552", "名称": "凯盛", "持仓": 100, "持仓状态": "已经买入"},
        {
            "代码": "600330",
            "名称": "天通",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "已触买·槽满",
            "已触买": "是",
            "当日预警": True,
            "过门OK": True,
        },
        {
            "代码": "000151",
            "名称": "中成",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "将买入",
            "已触买": "否",
            "当日预警": True,
            "近买点": True,
            "过门OK": True,
        },
    ]
    closed = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "600330", "000151"},
        strategy_codes={"600552", "600330", "000151"},
        phase="closed",
    )
    codes = [str(r["代码"]) for r in closed]
    assert "600552" in codes
    assert "600330" in codes
    assert "000151" not in codes
    auction = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "600330", "000151"},
        strategy_codes={"600552", "600330", "000151"},
        phase="auction",
    )
    assert "600330" not in [str(r["代码"]) for r in auction]
    assert "000151" not in [str(r["代码"]) for r in auction]


def test_filter_includes_alert_without_pool():
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600552", "名称": "凯盛", "持仓": 400, "持仓状态": "已经买入", "距买点%": 0},
        {
            "代码": "002104",
            "名称": "恒宝",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "将买入",
            "近买点": True,
            "距买点%": 0.5,
        },
        {"代码": "600301", "名称": "华锡", "持仓": 0, "持仓状态": "空仓", "预警": "空仓", "距买点%": 5},
    ]
    # 预警须在默认策略池内；portfolio_codes 空壳不再单独进 Tab
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552"},
        strategy_codes={"600552", "002104", "600301"},
        phase="continuous",
    )
    codes = [str(r["代码"]) for r in picked]
    assert "600552" in codes
    assert "002104" in codes
    assert "600301" not in codes
    assert codes[0] == "600552"
    assert picked[0].get("置顶") is True
    assert picked[0].get("持仓状态") == "已经买入"
    alert = next(r for r in picked if r["代码"] == "002104")
    assert alert.get("当日预警") is True
    assert int(alert.get("持仓") or 0) == 0
    assert alert.get("盈亏说明") == "当日预警·未登记持仓"
    assert alert.get("置顶") is False


def test_filter_skips_stale_pool_shell_and_off_strategy_alert():
    """旧 portfolio_pool 空壳、非默认策略池预警不进持仓 Tab。"""
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600552", "名称": "凯盛", "持仓": 100, "持仓状态": "已经买入", "距买点%": 0},
        {"代码": "002015", "名称": "旧池空壳", "持仓": 0, "持仓状态": "空仓", "预警": "-", "距买点%": 9},
        {
            "代码": "002093",
            "名称": "旧池预警",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "将买入",
            "近买点": True,
            "距买点%": 0.2,
        },
    ]
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600552", "002015", "002093"},
        strategy_codes={"600552"},  # 默认策略仅凯盛
        phase="continuous",
    )
    codes = [str(r["代码"]) for r in picked]
    assert codes == ["600552"]


def test_prune_portfolio_pool_drops_stale():
    from watch_config import prune_portfolio_pool

    holdings = {
        "portfolio_pool": ["600552", "002015", "002636", "600353"],
        "positions": {
            "600552": {"qty": 0},
            "002636": {"qty": 400, "cost": 70.0},  # 非策略但仍持仓，保留
            "002015": {"qty": 0},
        },
        "realized_today": {"600353": {"qty": 100, "reason": "止损成交"}},
    }
    # monkey: strategy pool = only 600552
    import watch_config as wc

    old = wc.strategy_watchlist_codes
    wc.strategy_watchlist_codes = lambda: {"600552"}  # type: ignore[assignment]
    try:
        pruned = prune_portfolio_pool(holdings)
    finally:
        wc.strategy_watchlist_codes = old
    assert "600552" in pruned
    assert "002636" in pruned
    assert "600353" in pruned
    assert "002015" not in pruned
    assert holdings["portfolio_pool"] == pruned


def test_pin_top3_slots():
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "600301", "名称": "华锡", "持仓": 100, "持仓状态": "已经买入", "距买点%": 3},
        {"代码": "600552", "名称": "凯盛", "持仓": 200, "持仓状态": "待卖出", "距买点%": 1},
        {"代码": "600330", "名称": "天通", "持仓": 300, "持仓状态": "已经买入", "距买点%": 2},
        {"代码": "002104", "名称": "恒宝", "持仓": 0, "持仓状态": "待买入", "预警": "已触买", "距买点%": 0},
    ]
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"600301", "600552", "600330", "002104"},
        strategy_codes={"600301", "600552", "600330", "002104"},
        phase="continuous",
    )
    pinned = [r for r in picked if r.get("置顶")]
    assert len(pinned) == 3
    assert all(int(r.get("持仓") or 0) > 0 for r in pinned)
    # 待卖出优先于已经买入
    assert pinned[0]["代码"] == "600552"
    assert picked[3]["代码"] == "002104"
    assert picked[3].get("置顶") is False


def test_demote_pre_signal_window():
    from index import _demote_pre_signal_window

    buy = _demote_pre_signal_window(
        {
            "alert": "已触买",
            "hit_buy": True,
            "hit_stop": False,
            "因子触发": "已触发",
            "持仓状态": "待买入",
            "挂单说明": "限价买@10",
        }
    )
    assert buy["hit_buy"] is False
    assert buy["alert"] == "将买入"
    assert buy["因子触发"] == "接近"
    assert "9:25 可挂单" in str(buy.get("挂单说明") or "")

    sell = _demote_pre_signal_window(
        {"alert": "已触止损", "hit_buy": False, "hit_stop": True, "因子触发": "已触发"}
    )
    assert sell["hit_stop"] is False
    assert sell["alert"] == "将止损"
    assert sell["因子触发"] == "接近"


def test_should_demote_pre_signal_skips_lunch_and_close():
    from index import _should_demote_pre_signal

    assert _should_demote_pre_signal("open_set") is True
    assert _should_demote_pre_signal("auction_locked") is True
    assert _should_demote_pre_signal("continuous") is False
    assert _should_demote_pre_signal("lunch") is False
    assert _should_demote_pre_signal("closed") is False


def test_empty_1m_keeps_daily_high_buy_hit():
    import pandas as pd
    from index import _merge_path_buy_hit

    hit, px, ts = _merge_path_buy_hit(True, None, open_px=10.0, entry_pct=0.025, tick=0.01)
    assert hit is True
    assert px is None
    assert ts is None
    empty = pd.DataFrame(columns=["ts", "high", "low"])
    hit2, _, _ = _merge_path_buy_hit(True, empty, open_px=10.0, entry_pct=0.025, tick=0.01)
    assert hit2 is True
    miss, _, _ = _merge_path_buy_hit(False, None, open_px=10.0, entry_pct=0.025, tick=0.01)
    assert miss is False
    # 1m 未走过买点时，仍保留日线最高已触（预警当天不摘）
    miss_1m = pd.DataFrame({"ts": [1, 2], "high": [10.1, 10.05], "low": [10.0, 10.0]})
    keep, _, _ = _merge_path_buy_hit(
        True, miss_1m, open_px=10.0, entry_pct=0.025, tick=0.01
    )
    assert keep is True


def test_stamp_buy_touched_sticky():
    from index import _stamp_buy_touched

    sticky: dict = {}
    _stamp_buy_touched(
        sticky,
        "600552",
        session="2026-09-11",
        ts="2026-09-11 09:41:07",
    )
    assert sticky["600552"]["buy_touched"] is True
    assert sticky["600552"]["session"] == "2026-09-11"
    assert sticky["600552"]["buy_hit_ts"].endswith("09:41:07")
    sticky["600552"]["stop_touched"] = True
    _stamp_buy_touched(
        sticky,
        "600552",
        session="2026-09-11",
        ts="2026-09-11 10:00:00",
    )
    assert sticky["600552"]["stop_touched"] is True
    assert sticky["600552"]["buy_touched"] is True
    assert sticky["600552"]["buy_hit_ts"].endswith("09:41:07")


def test_fill_row_signal_times_hms():
    from index import _fill_row_signal_times

    sticky = {
        "600330": {
            "session": "2026-09-14",
            "buy_touched": True,
            "buy_hit_ts": "2026-09-14 09:48:03",
        }
    }
    row: dict = {"已触买": "是"}
    _fill_row_signal_times(row, sticky, "600330", hit_buy=True)
    assert row["信号时间"] == "09:48:03"
    assert row["买信号时间"] == "09:48:03"


def test_fill_row_signal_times_uses_buy_time_after_slot():
    """已入槽后本轮未必再算触买，仍用 buy_time 出时分秒。"""
    from index import _fill_row_signal_times

    row: dict = {"已触买": "是", "持仓": 3200}
    _fill_row_signal_times(
        row,
        {},
        "600330",
        hit_buy=False,
        buy_time="2026-09-14 10:08:53",
    )
    assert row["信号时间"] == "10:08:53"
    assert row["买信号时间"] == "10:08:53"


def test_restore_session_buy_hit_ignores_1m_pullback():
    """有分钟线、现价已离开买点：当日 sticky 仍把已触买留住。"""
    from index import _restore_session_buy_hit, _sticky_drop_sell_keep_buy

    sticky = {
        "000151": {"session": "2026-09-11", "buy_touched": True, "bg_class": "warn-sell"}
    }
    assert (
        _restore_session_buy_hit(
            False,
            qty=0,
            sticky_row=sticky["000151"],
            session="2026-09-11",
        )
        is True
    )
    assert (
        _restore_session_buy_hit(
            False,
            qty=0,
            sticky_row=sticky["000151"],
            session="2026-09-12",
        )
        is False
    )
    _sticky_drop_sell_keep_buy(sticky, "000151", "2026-09-11")
    assert sticky["000151"]["buy_touched"] is True
    assert "bg_class" not in sticky["000151"]


def test_today_alert_row_keeps_buy_hit_without_alert_text():
    from watch_buy_signal import is_today_alert_row

    row = {
        "代码": "000151",
        "持仓": 0,
        "持仓状态": "空仓",
        "预警": "空仓",
        "已触买": "是",
        "过门OK": True,
    }
    assert is_today_alert_row(row) is True


def test_buy_distance_and_sort_helpers():
    from index import _buy_distance_pct, sort_watch_rows

    near = {"代码": "002104", "现价": 10.0, "买点": 10.2, "持仓": 0, "距买点%": None}
    far = {"代码": "600301", "现价": 10.0, "买点": 11.0, "持仓": 0, "距买点%": None}
    held = {"代码": "600552", "现价": 20.0, "买点": 19.0, "持仓": 400, "距买点%": 0.0}
    near["距买点%"] = _buy_distance_pct(near)
    far["距买点%"] = _buy_distance_pct(far)
    assert near["距买点%"] < far["距买点%"]
    ordered = sort_watch_rows([far, near, held])
    assert ordered[0]["代码"] == "600552"
    assert ordered[1]["代码"] == "002104"
    assert ordered[2]["代码"] == "600301"


def test_finalize_t1_never_pending_sell():
    """今日买入 T+1：即使已触止损字段为是，持仓状态仍已经买入。"""
    from index import _finalize_position_row

    row = {
        "持仓": 1000,
        "可用": 0,
        "持仓状态": "待卖出",
        "预警": "已触止损·T+1暂不可卖",
        "已触止损": "是",
        "当日禁买": False,
        "策略回放持有": False,
        "买入时间": "2026-09-07 13:00:00",
        "交易日": "2026-09-07",
    }
    _finalize_position_row(row)
    assert row["持仓状态"] == "已经买入"
    assert row["可执行"] is False
    assert "T+1" in row["预警"] or "止损已记" in row["预警"]


def test_finalize_real_hold_not_empty_on_hit_stop():
    """实仓触止损但未平仓：状态已经买入，勿写成空仓。"""
    from index import _finalize_position_row

    row = {
        "持仓": 1000,
        "可用": 0,
        "持仓状态": "空仓",
        "预警": "已触买",
        "已触止损": "是",
        "当日禁买": False,
        "策略回放持有": False,
    }
    _finalize_position_row(row)
    assert row["持仓状态"] == "已经买入"
    assert row["预警"] == "已触止损·暂不可卖"


def test_finalize_sold_today_is_stopped():
    from index import _finalize_position_row

    row = {
        "持仓": 0,
        "可用": 0,
        "持仓状态": "空仓",
        "预警": "止损",
        "当日禁买": True,
        "策略回放持有": False,
    }
    _finalize_position_row(row)
    assert row["持仓状态"] == "已平仓"


def test_finalize_slot_closed_not_paper_replay():
    from index import _finalize_position_row, SIGNAL_STOP_HIT

    row = {
        "持仓": 0,
        "持仓状态": "已平仓",
        "预警": "策略回放·今日已止损",
        "当日禁买": True,
        "三槽平仓": True,
        "卖出数量": 1800,
    }
    _finalize_position_row(row)
    assert row["预警"] == SIGNAL_STOP_HIT
    assert row["持仓状态"] == "已平仓"


def test_finalize_sold_today_rebuy_banned():
    """当日卖出后再触买：仍记当日禁买（三槽规则）。"""
    from index import _finalize_position_row

    row = {
        "持仓": 0,
        "可用": 0,
        "持仓状态": "待买入",
        "预警": "卖出后再触买",
        "当日禁买": True,
        "已触买": "是",
        "策略回放持有": False,
        "已实现": True,
    }
    _finalize_position_row(row)
    # 禁买优先于待买入
    assert row.get("当日禁买") is True


def test_apply_trigger_sold_today_bans_rebuy():
    """过门通过时，当日卖出仍设当日禁买。"""
    from index import _apply_trigger_date_fields

    row = {
        "持仓状态": "已平仓",
        "预警": "止损",
        "已触买": "否",
        "买点": 10.5,
        "止损": 9.8,
        "成交价": 9.8,
    }
    sig = {"hit_buy": False, "hit_stop": True, "因子触发": "已触发", "持仓状态": "已平仓"}
    _apply_trigger_date_fields(
        row,
        sig=sig,
        session="2026-09-07",
        last_px=10.2,
        px_digits=2,
        buy_time="2026-09-05",
        qty=0,
        replay={"holding": False},
        code="600330",
        allow_entry=True,
    )
    assert row.get("当日禁买") is True


def test_apply_trigger_holding_today_buy_marks_triggered():
    """今日入槽实仓：因子触发写「已触发 M/D」，即使 T+1 止损已记。"""
    from index import _apply_trigger_date_fields

    row = {
        "持仓状态": "已经买入",
        "预警": "持有·T+1·止损已记",
        "已触买": "是",
        "已触止损": "是",
        "买点": 16.29,
        "止损": 17.24,
    }
    sig = {
        "hit_buy": True,
        "hit_stop": True,
        "因子触发": "已触发",
        "持仓状态": "已经买入",
    }
    _apply_trigger_date_fields(
        row,
        sig=sig,
        session="2026-09-11",
        last_px=17.0,
        px_digits=2,
        buy_time="2026-09-11 09:43:32",
        qty=5500,
        replay={"holding": False, "last_buy_px": 16.29, "last_buy_date": "2026-09-11"},
        code="000070",
        allow_entry=True,
    )
    assert str(row.get("因子触发") or "").startswith("已触发")
    assert "9/11" in str(row.get("因子触发") or "")
    assert row.get("已触发因子侧") == "买入"


def test_apply_trigger_holding_today_buy_not_unavailable():
    """今日入槽但信号文案是不可用：仍标已触发，不写不可用。"""
    from index import _apply_trigger_date_fields

    row = {
        "持仓状态": "已经买入",
        "预警": "持有·T+1",
        "已触买": "是",
        "已触止损": "否",
        "买点": 33.48,
        "止损": 32.64,
    }
    sig = {
        "hit_buy": True,
        "hit_stop": False,
        "因子触发": "不可用",
        "持仓状态": "已经买入",
    }
    _apply_trigger_date_fields(
        row,
        sig=sig,
        session="2026-09-11",
        last_px=32.91,
        px_digits=2,
        buy_time="2026-09-11 09:43:32",
        qty=2600,
        replay={"holding": False, "last_buy_px": 33.48, "last_buy_date": "2026-09-11"},
        code="600522",
        allow_entry=True,
    )
    assert row.get("因子触发") == "已触发 9/11"


def test_overlay_does_not_rewrite_real_qty():
    from index import _overlay_buy_signal_on_hold

    sig = {"持仓状态": "已经买入", "alert": "已经买入", "因子触发": "9/7"}
    out = _overlay_buy_signal_on_hold(
        sig,
        hit_buy=True,
        allow_entry=True,
        paper_active=False,
        qty=1000,
        buy_time="2026-09-07 12:58:35",
        session="2026-09-07",
        buy_trigger=25.48,
        stop_px=25.3,
        last_px=25.6,
        px_digits=2,
    )
    assert out["持仓状态"] == "已经买入"
    assert out.get("alert") == "已经买入"


def test_annotate_unfilled_buy_signals_slot_full_and_gate():
    """触买信号与入槽拆开：槽满仍预警；未过门不算触买、不进预警。"""
    from index import _annotate_unfilled_buy_signals
    from watch_snapshot import filter_portfolio_holdings

    hit = {
        "代码": "600869",
        "名称": "远东",
        "持仓": 0,
        "已触买": "是",
        "预警": "已触买",
        "持仓状态": "待买入",
        "过门OK": True,
        "买点": 24.81,
        "买入侧价": 24.81,
        "价位小数": 2,
        "挂单说明": "",
    }
    gate = {
        "代码": "002068",
        "名称": "黑猫",
        "持仓": 0,
        "已触买": "否",
        "预警": "空仓",
        "持仓状态": "空仓",
        "过门OK": False,
        "过门": "前日大阳·不过门",
        "最高": 11.0,
        "买点": 10.27,
        "挂单说明": "",
    }
    stale = {
        "代码": "000070",
        "名称": "特发",
        "持仓": 0,
        "已触买": "否",
        "预警": "触买价·未过门",
        "持仓状态": "空仓",
        "过门OK": False,
        "过门": "前日大阳·不过门",
        "最高": 12.0,
        "买点": 11.0,
        "当日预警": True,
        "bg_class": "warn-buy",
        "挂单说明": "最高已过买点@11.00，但前日大阳·不过门·不入槽",
    }
    _annotate_unfilled_buy_signals(
        [hit, gate, stale],
        {"freeBuy": 0, "buysLeft": 0, "free": 0},
    )
    assert hit["预警"] == "已触买·槽满"
    assert hit["持仓状态"] == "待买入"
    assert hit["槽位候选"] is True
    assert gate["预警"] == "空仓"
    assert gate.get("当日预警") is not True
    assert stale["预警"] == "空仓"
    assert stale.get("当日预警") is False

    picked = filter_portfolio_holdings(
        [hit, gate, stale],
        portfolio_codes=set(),
        strategy_codes={"600869", "002068", "000070"},
        phase="continuous",
    )
    codes = {str(r["代码"]) for r in picked}
    assert codes == {"600869"}


def test_enrich_skips_paper_replay_without_lots():
    """中钨高新这类回放已止损、从未入三槽：不算平仓、不折算 30 万槽位。"""
    from index import _enrich_closed_day_pnl, _is_closed_trace_row

    row = {
        "代码": "000657",
        "名称": "中钨高新",
        "持仓": 0,
        "持仓状态": "已平仓",
        "当日禁买": True,
        "已触止损": "是",
        "成本": 59.45,
        "昨收": 59.42,
        "现价": 56.4,
        "开盘": 57.83,
        "最低": 56.4,
        "止损": 56.38,
        "预警": "策略回放·今日已止损",
    }
    assert _is_closed_trace_row(row, lots={}) is False
    _enrich_closed_day_pnl(row, lots={})
    assert row.get("三槽平仓") is not True
    assert not row.get("卖出数量")
    assert row.get("当日盈亏") is None


def test_closed_trace_cleared_next_session():
    """今日已平仓下一交易日不再展示，即使成交流水仍有昨仓。"""
    from index import _is_closed_trace_row

    lots = {"601208": {"qty": 600, "cost": 47.67}}
    today = {
        "代码": "601208",
        "持仓": 0,
        "交易日": "2026-09-11",
        "当日禁买": True,
        "已触止损": "是",
    }
    traces_today = {"601208": {"session": "2026-09-11", "qty": 1800}}
    assert _is_closed_trace_row(today, lots=lots, traces=traces_today) is True

    nxt = dict(today)
    nxt["交易日"] = "2026-09-14"
    assert _is_closed_trace_row(nxt, lots=lots, traces=traces_today) is False


def test_closed_trace_first_detect_today_without_stamp():
    """当日尚未落库 closed_today：成交流水+当日禁买仍算今日平仓。"""
    from index import _is_closed_trace_row

    row = {
        "代码": "601208",
        "持仓": 0,
        "交易日": "2026-09-11",
        "当日禁买": True,
        "已触止损": "是",
    }
    assert (
        _is_closed_trace_row(
            row, lots={"601208": {"qty": 600, "cost": 47.67}}, traces={}
        )
        is True
    )


def test_filter_skips_paper_replay_closed():
    """策略回放已平仓、从未入三槽：进预警栏，不进已平仓留痕。"""
    from watch_snapshot import filter_portfolio_holdings

    rows = [
        {"代码": "000070", "名称": "特发", "持仓": 100, "持仓状态": "已经买入"},
        {
            "代码": "000657",
            "名称": "中钨高新",
            "持仓": 0,
            "持仓状态": "已平仓",
            "当日禁买": True,
            "预警": "策略回放·今日已止损",
            "已触止损": "是",
        },
        {
            "代码": "601208",
            "名称": "东材",
            "持仓": 0,
            "持仓状态": "已平仓",
            "卖出数量": 1800,
            "三槽平仓": True,
            "预警": "已触止损",
        },
    ]
    picked = filter_portfolio_holdings(
        rows,
        portfolio_codes={"000070", "000657", "601208"},
        strategy_codes={"000070", "000657", "601208"},
        phase="continuous",
    )
    codes = [str(r["代码"]) for r in picked]
    assert "000070" in codes
    assert "601208" in codes
    assert "000657" in codes
    replay = next(r for r in picked if r["代码"] == "000657")
    assert replay.get("槽位留痕") is not True
    assert replay.get("当日预警") is True
    assert next(r for r in picked if r["代码"] == "601208").get("槽位留痕") is True


def test_closed_day_pnl_gap_open():
    """已平仓：低开跌破止损，平仓价=开盘，当日浮亏相对昨收。"""
    from index import _enrich_closed_day_pnl

    row = {
        "代码": "601208",
        "持仓": 0,
        "持仓状态": "已平仓",
        "当日禁买": True,
        "已触止损": "是",
        "现价": 47.07,
        "昨收": 48.59,
        "开盘": 46.97,
        "最低": 46.88,
        "止损": 47.71,
    }
    _enrich_closed_day_pnl(
        row, lots={"601208": {"qty": 600, "cost": 47.67}}
    )
    from index import _paper_slot_qty

    qty = _paper_slot_qty(47.67)
    assert qty == 1800
    assert row["成交价"] == 46.97
    assert row["卖出数量"] == qty
    assert row["当日盈亏"] == round((46.97 - 48.59) * qty, 2)
    assert row["当日盈亏%"] == round((46.97 / 48.59 - 1.0) * 100.0, 2)
    assert row["浮盈"] == round((46.97 - 47.67) * qty, 2)


def test_closed_day_pnl_path_stop():
    """已平仓：开盘已破买点硬保护，平仓价=开盘，不是更低的 T1 回落。"""
    from index import _enrich_closed_day_pnl

    row = {
        "代码": "000021",
        "持仓": 0,
        "槽位留痕": True,
        "持仓状态": "已平仓",
        "已触止损": "是",
        "现价": 34.43,
        "昨收": 36.5,
        "开盘": 35.21,
        "最低": 34.08,
        "止损": 34.32,
    }
    _enrich_closed_day_pnl(
        row, lots={"000021": {"qty": 800, "cost": 36.35}}
    )
    from index import _paper_slot_qty

    qty = _paper_slot_qty(36.35)
    assert qty == 2400
    assert row["成交价"] == 35.21
    assert row["卖出数量"] == qty
    assert row["当日盈亏"] == round((35.21 - 36.5) * qty, 2)


def test_closed_day_pnl_locks_stop_not_last():
    """已触止损但日线最低未到：仍按止损锁定，不跟现价。"""
    from index import _enrich_closed_day_pnl

    row = {
        "代码": "002636",
        "持仓": 0,
        "持仓状态": "已平仓",
        "当日禁买": True,
        "已触止损": "是",
        "现价": 75.38,
        "昨收": 76.45,
        "开盘": 76.0,
        "最低": 75.18,
        "止损": 74.1,
    }
    _enrich_closed_day_pnl(
        row, lots={"002636": {"qty": 400, "cost": 70.21}}
    )
    from index import _paper_slot_qty

    qty = _paper_slot_qty(70.21)
    assert qty == 1200
    assert row["成交价"] == 74.1
    locked = row["当日盈亏"]
    assert locked == round((74.1 - 76.45) * qty, 2)
    row["现价"] = 80.0
    _enrich_closed_day_pnl(
        row, lots={"002636": {"qty": 400, "cost": 70.21}}
    )
    assert row["成交价"] == 74.1
    assert row["当日盈亏"] == locked


def test_closed_jinan_rejects_eod_stop_vs_open():
    """金安昨仓已过 3%：禁止用收盘后抬高的止损去撞今开。"""
    from index import _enrich_closed_day_pnl

    row = {
        "代码": "002636",
        "持仓": 0,
        "持仓状态": "已平仓",
        "当日禁买": True,
        "已触止损": "是",
        "现价": 82.46,
        "昨收": 76.45,
        "开盘": 76.0,
        "最高": 84.0,
        "最低": 73.0,
        "止损": 82.32,
        "成交价": 76.0,
        "交易日": "2026-09-11",
    }
    _enrich_closed_day_pnl(
        row, lots={"002636": {"qty": 400, "cost": 70.21, "time": "2026-09-10 10:00:00"}}
    )
    assert row.get("成交价") != 76.0


def test_closed_jinan_path_ladder_not_open():
    """金安 1m：先触 10% 阶梯半仓，成交价不是今开。"""
    import pandas as pd
    from index import _enrich_closed_day_pnl

    bars = pd.DataFrame(
        [
            {
                "ts": "2026-09-11 09:31:00",
                "open": 76.0,
                "high": 76.99,
                "low": 75.90,
                "close": 76.92,
            },
            {
                "ts": "2026-09-11 09:39:00",
                "open": 76.09,
                "high": 77.34,
                "low": 76.00,
                "close": 77.30,
            },
        ]
    )
    row = {
        "代码": "002636",
        "持仓": 0,
        "持仓状态": "已平仓",
        "当日禁买": True,
        "已触止损": "是",
        "现价": 82.46,
        "昨收": 76.45,
        "开盘": 76.0,
        "最高": 84.0,
        "最低": 73.0,
        "止损": 82.32,
        "成交价": 76.0,
        "交易日": "2026-09-11",
        "_day_bars": bars,
    }
    _enrich_closed_day_pnl(
        row, lots={"002636": {"qty": 400, "cost": 70.21, "time": "2026-09-10 10:00:00"}}
    )
    assert abs(float(row["成交价"]) - 77.23) < 0.02
    assert row["成交价"] != 76.0


def test_closed_day_pnl_keeps_realized_without_open():
    from index import _enrich_closed_day_pnl

    row = {
        "代码": "600330",
        "持仓": 0,
        "已实现": True,
        "当日盈亏": -100.0,
        "昨收": 20.0,
        "现价": 19.0,
    }
    _enrich_closed_day_pnl(
        row, lots={"600330": {"qty": 1000, "cost": 20.0}}
    )
    assert row["当日盈亏"] == -100.0


def test_enrich_keeps_realized_ledger_qty():
    """已实现成交不得被纸面槽位股数覆盖。"""
    from index import _enrich_closed_day_pnl, _paper_slot_qty

    row = {
        "代码": "601208",
        "持仓": 0,
        "持仓状态": "已平仓",
        "已实现": True,
        "卖出数量": 600,
        "当日盈亏": -12.5,
        "当日盈亏%": -0.44,
        "成交价": 46.97,
        "开盘": 46.97,
        "成本": 47.67,
        "昨收": 48.59,
    }
    _enrich_closed_day_pnl(
        row, lots={"601208": {"qty": 600, "cost": 47.67}}
    )
    assert _paper_slot_qty(47.67) == 1800
    assert row["卖出数量"] == 600
    assert row["当日盈亏"] == -12.5
    assert row["三槽平仓"] is True


def test_purge_stale_closed_today():
    from index import _purge_stale_realized

    data = {
        "realized_today": {
            "601208": {"session": "2026-09-10", "qty": 600},
            "000070": {"session": "2026-09-11", "qty": 100},
        },
        "closed_today": {
            "601208": {"session": "2026-09-10", "qty": 1800},
            "000021": {"session": "2026-09-11", "qty": 2400},
        },
    }
    _purge_stale_realized(data, "2026-09-11")
    assert "601208" not in data["realized_today"]
    assert "000070" in data["realized_today"]
    assert "601208" not in data["closed_today"]
    assert data["closed_today"]["000021"]["qty"] == 2400


def test_parse_open_lots_last_buy():
    from index import _parse_open_lots

    text = "\n".join(
        [
            '{"time":"2026-09-10 13:42:30","side":"buy","code":"601208","price":47.67,"qty":600,"after_qty":600,"avg_cost":47.67}',
            '{"time":"2026-09-10 13:50:00","side":"sell","code":"601208","price":47.0,"qty":600,"after_qty":0,"avg_cost":47.67}',
            '{"time":"2026-09-10 13:42:30","side":"buy","code":"002636","price":70.21,"qty":400,"after_qty":400,"avg_cost":70.21}',
        ]
    )
    lots = _parse_open_lots(text)
    assert "601208" not in lots
    assert lots["002636"]["qty"] == 400
    assert lots["002636"]["cost"] == 70.21


def test_calc_day_pnl_today_buy_vs_cost():
    """今买：今日盈亏=现价相对买入价（akq_math / akquant）。"""
    from watch_config import calc_day_pnl

    pnl, pct, base = calc_day_pnl(
        last=17.0,
        qty=5500,
        available=0,
        cost=16.29,
        prev_close=16.18,
        open_px=15.31,
        today_cost=16.29,
        buy_time="2026-09-11 09:43:32",
        session="2026-09-11",
    )
    assert pnl == round((17.0 - 16.29) * 5500, 2)
    assert base == round(16.29 * 5500, 2)
    assert pct == round((17.0 / 16.29 - 1.0) * 100.0, 2)


def test_calc_day_pnl_overnight_vs_prev_close():
    """昨仓：今日盈亏=现价相对昨收，等于 akquant vec_returns。"""
    from watch_config import calc_day_pnl

    pnl, pct, base = calc_day_pnl(
        last=46.97,
        qty=1800,
        available=1800,
        cost=47.67,
        prev_close=48.59,
        open_px=46.97,
        buy_time="2026-09-10 13:42:30",
        session="2026-09-11",
    )
    assert pnl == round((46.97 - 48.59) * 1800, 2)
    assert base == round(48.59 * 1800, 2)
    assert pct == round((46.97 / 48.59 - 1.0) * 100.0, 2)


def test_account_summary_sums_hold_and_closed_day_pnl():
    """今日盈亏 = 三槽持仓当日盈亏 + 已平仓当日盈亏。"""
    from index import _build_watch_account_summary

    acc = _build_watch_account_summary(
        [
            {
                "代码": "000070",
                "持仓": 5500,
                "浮盈": 3575.0,
                "当日盈亏": 3575.0,
                "市值": 90000.0,
                "成本额": 86000.0,
            },
            {
                "代码": "601208",
                "持仓": 0,
                "三槽平仓": True,
                "浮盈": -1260.0,
                "当日盈亏": 0.0,
                "开盘": 46.97,
                "卖出数量": 1800,
                "成本": 47.67,
            },
            {
                "代码": "000021",
                "持仓": 0,
                "三槽平仓": True,
                "浮盈": -4872.0,
                "当日盈亏": -2136.0,
                "开盘": 35.21,
                "卖出数量": 2400,
                "成本": 36.35,
            },
            {
                "代码": "000657",
                "持仓": 0,
                "持仓状态": "已平仓",
                "当日盈亏": -9999.0,
            },
        ]
    )
    assert acc["dayPnl"] == round(3575.0 + 0.0 - 2136.0, 2)
    assert acc["settledCount"] == 2
    assert acc["settledDayPnl"] == round(0.0 - 2136.0, 2)

