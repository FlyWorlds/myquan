"""三槽持仓辅助函数单测。"""

from __future__ import annotations

from watch_config import (
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    free_slot_count,
    occupied_slot_codes,
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


def test_sellable_overnight_available_zero_not_fallback():
    from watch_config import sellable_qty

    pos = {"qty": 1000, "available": 0, "buy_time": "2026-09-07 09:31:00"}
    assert sellable_qty(pos, 1000, pos["buy_time"], "2026-09-08") == 0
    pos_na = {"qty": 1000, "available": None, "buy_time": "2026-09-07 09:31:00"}
    assert sellable_qty(pos_na, 1000, pos_na["buy_time"], "2026-09-08") == 1000


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
    assert "9:30" in str(buy.get("挂单说明") or "")

    sell = _demote_pre_signal_window(
        {"alert": "已触止损", "hit_buy": False, "hit_stop": True, "因子触发": "已触发"}
    )
    assert sell["hit_stop"] is False
    assert sell["alert"] == "将止损"
    assert sell["因子触发"] == "接近"


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

