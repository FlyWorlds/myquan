"""因子26：1 分钟 path-dependent 多层止盈触达。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load(name: str, path: Path, *, inject: dict[str, ModuleType] | None = None):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if inject:
        for k, v in inject.items():
            sys.modules[k] = v
    spec.loader.exec_module(mod)
    return mod


# 不走 strategy/__init__（会拖 factors→backtest）
_ob = _load("strategy.open_break", _DIR / "open_break.py")
_akq = _load("strategy.akq_math", _DIR / "akq_math.py")
_m = _load(
    "strategy.pullback_wave_stop",
    _DIR / "pullback_wave_stop.py",
    inject={"strategy.open_break": _ob, "strategy.akq_math": _akq},
)
path_dependent_pullback_hit = _m.path_dependent_pullback_hit
path_dependent_buy_hit = _m.path_dependent_buy_hit
half_gain_stop_price = _m.half_gain_stop_price
pullback_stop_price = _m.pullback_stop_price


def _bars(rows: list[tuple[float, float]]) -> pd.DataFrame:
    ts0 = pd.Timestamp("2026-09-07 09:31:00")
    return pd.DataFrame(
        [
            {"ts": ts0 + pd.Timedelta(minutes=i), "high": h, "low": lo}
            for i, (h, lo) in enumerate(rows)
        ]
    )


def test_half_gain_formula():
    # 成本100、最高110 → 回落一半卖价 105
    assert abs(half_gain_stop_price(110.0, 100.0) - 105.0) < 1e-9
    # 未浮盈 → 成本硬保护 97.5
    assert abs(half_gain_stop_price(100.0, 100.0, hard_pct=0.025) - 97.5) < 1e-9
    # 刚过成本即可回吐（可卖日用买入后高点，不等 2.5%）
    assert abs(half_gain_stop_price(101.0, 100.0, hard_pct=0.025) - 100.5) < 1e-9


def test_snapshot_high_must_not_seed_before_morning_low():
    """隔夜成本 28.2；早盘低 29.5、午后才到 31。若把 31 种进 seed 会误触。"""
    morning = _bars([(29.8, 29.5)])
    ok = path_dependent_pullback_hit(
        morning, pullback_pct=0.025, seed_high=28.2, cost_px=28.2, vol20_daily=0.05
    )
    assert ok["hit_stop"] is False, ok
    bad = path_dependent_pullback_hit(
        morning, pullback_pct=0.025, seed_high=31.0, cost_px=28.2, vol20_daily=0.05
    )
    assert bad["hit_stop"] is True, bad


def test_attack_buy_same_bar_low_and_high_rejected():
    """同一根 1m：低 90、高 94。须先有更早低点，不能本分钟自造攻击波。"""
    bars = _bars([(94.0, 90.0)])
    out = path_dependent_buy_hit(bars, open_px=100.0, entry_pct=0.025)
    assert out["hit_buy"] is False, out
    bars2 = _bars([(91.0, 90.0), (94.0, 93.0)])
    out2 = path_dependent_buy_hit(
        bars2, open_px=100.0, entry_pct=0.025, allow_attack=True
    )
    assert out2["hit_buy"] is True, out2
    assert out2["buy_kind"] == "attack"
    # 默认关攻击波：同样路径不买（未到开盘+2.5%）
    off = path_dependent_buy_hit(bars2, open_px=100.0, entry_pct=0.025)
    assert off["hit_buy"] is False, off


def test_attack_buy_snapshot_lookahead_rejected():
    """早盘高 101、午后低 90：全日 OHLC 会假触发攻击波；1m 顺序不应买。"""
    bars = _bars([(101.0, 100.0), (91.0, 90.0)])
    out = path_dependent_buy_hit(bars, open_px=100.0, entry_pct=0.025)
    assert out["hit_buy"] is False, out


def test_daily_ohlc_false_positive_avoided():
    """早盘低、午后高：全日 OHLC 会假触发止损；1m 顺序不应卖。"""
    bars = _bars([(100.0, 98.0), (109.5, 108.0)])
    out = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=100.0, cost_px=100.0, vol20_daily=0.05
    )
    assert out["hit_stop"] is False, out


def test_hard_protect_path_hit():
    """未抬升峰值时，成本硬保护与旧峰值2.5%同价。"""
    bars = _bars([(100.0, 99.0), (100.5, 97.0)])
    out = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=100.0, cost_px=100.0
    )
    assert out["hit_stop"] is True, out
    assert abs(float(out["touch_stop"]) - 97.5) < 1e-9, out


def test_half_gain_after_peak():
    """峰值106：一半=103、波动=103.35；同 bar 先碰到更高的波动线。"""
    bars = _bars([(106.0, 105.0), (106.0, 102.9)])
    out = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        seed_high=100.0,
        cost_px=100.0,
        vol20_daily=0.05,
    )
    assert out["hit_stop"] is True, out
    assert abs(float(out["touch_stop"]) - 103.35) < 1e-6, out
    assert out["stop_kind"] == "vol_giveback"


def test_multi_tp_ladder_and_peak_once():
    """规则1+3：同分钟只半仓一次；≥10% 后回落 2% 清仓；15%全清优先。"""
    ev = _m.eval_multi_tp_bar
    # 10% 半仓
    r = ev(
        bar_open=100.0,
        bar_high=111.0,
        bar_low=110.5,
        cost_px=100.0,
        peak_before=100.0,
        shares=1000,
        can_sell=True,
    )
    assert r["action"]["kind"] == "half"
    assert r["action"]["reason"] == "ladder_half_10"
    assert r["action"]["shares"] == 500
    assert abs(float(r["action"]["fill_px"]) - 110.0) < 1e-9
    # 15% 全清
    r15 = ev(
        bar_open=100.0,
        bar_high=116.0,
        bar_low=115.0,
        cost_px=100.0,
        peak_before=100.0,
        shares=1000,
        can_sell=True,
    )
    assert r15["action"]["kind"] == "full"
    assert r15["action"]["reason"] == "ladder_full_15"
    # 峰值回落 2%（已达 10%，高未再触阶梯）
    r3 = ev(
        bar_open=109.0,
        bar_high=109.5,
        bar_low=106.6,
        cost_px=100.0,
        peak_before=110.0,
        shares=1000,
        can_sell=True,
        tp_stage=0,
    )
    assert r3["action"]["kind"] == "full"
    assert r3["action"]["reason"] == "peak_pullback_clear"
    # 同分钟既触 10% 又触峰值回落 → 只减一次，优先阶梯
    both = ev(
        bar_open=110.0,
        bar_high=111.0,
        bar_low=106.6,
        cost_px=100.0,
        peak_before=110.0,
        shares=1000,
        can_sell=True,
    )
    assert both["action"]["kind"] == "half"
    assert both["action"]["reason"] == "ladder_half_10"
    # 已半仓后再触 10%、未回落 2% → 继续持有剩余（留给 15% / 峰值回落）
    hold = ev(
        bar_open=110.0,
        bar_high=111.0,
        bar_low=110.5,
        cost_px=100.0,
        peak_before=110.0,
        shares=500,
        can_sell=True,
        tp_stage=1,
    )
    assert hold["action"] is None, hold


def test_mid_gain_race_half_vs_vol():
    """中赚并行：从峰值往下谁先碰到走谁（同分钟价高者先触）。"""
    ev = _m.eval_multi_tp_bar
    # peak 105 / σ=5%：一半 102.50 > 波动 102.375 → 先触一半
    half_first = ev(
        bar_open=104.0,
        bar_high=105.0,
        bar_low=102.40,
        cost_px=100.0,
        peak_before=105.0,
        shares=1000,
        can_sell=True,
        vol20_daily=0.05,
    )
    assert half_first["action"]["kind"] == "full"
    assert half_first["action"]["reason"] == "half_gain"
    assert abs(float(half_first["action"]["fill_px"]) - 102.50) < 1e-9
    # peak 108 / σ=5%：波动 105.30 > 一半 104 → 先触波动
    vol_first = ev(
        bar_open=107.0,
        bar_high=108.0,
        bar_low=105.00,
        cost_px=100.0,
        peak_before=108.0,
        shares=1000,
        can_sell=True,
        vol20_daily=0.05,
    )
    assert vol_first["action"]["kind"] == "full"
    assert vol_first["action"]["reason"] == "vol_giveback"
    assert abs(float(vol_first["action"]["fill_px"]) - 105.30) < 1e-9


def test_multi_tp_mid_gain_giveback_and_small_profit_no_giveback():
    """中赚 >3% 且 <10% 才走一半/波动赛跑；小赚不回落。"""
    ev = _m.eval_multi_tp_bar
    mid = ev(
        bar_open=104.0,
        bar_high=105.0,
        bar_low=102.2,
        cost_px=100.0,
        peak_before=105.0,
        shares=1000,
        can_sell=True,
        vol20_daily=0.05,
    )
    assert mid["action"]["kind"] == "full"
    assert mid["action"]["reason"] == "half_gain"
    assert abs(float(mid["action"]["fill_px"]) - 102.50) < 1e-9
    small = ev(
        bar_open=101.2,
        bar_high=101.5,
        bar_low=100.6,
        cost_px=100.0,
        peak_before=101.5,
        shares=1000,
        can_sell=True,
        vol20_daily=0.05,
    )
    assert small["action"] is None
    # 隔夜曾冲高、今日回到成本附近：未过 3% 不按旧峰值回落
    stale = ev(
        bar_open=100.2,
        bar_high=100.5,
        bar_low=100.0,
        cost_px=100.0,
        peak_before=105.0,
        shares=1000,
        can_sell=True,
        vol20_daily=0.05,
    )
    assert stale["action"] is None


def test_multi_tp_overnight_dump():
    r = _m.eval_multi_tp_bar(
        bar_open=100.0,
        bar_high=100.5,
        bar_low=97.4,
        cost_px=100.0,
        peak_before=105.0,
        shares=1000,
        can_sell=True,
        overnight_armed=True,
        day_open=100.0,
        session_peak_before=0.0,
    )
    assert r["action"]["kind"] == "full"
    assert r["action"]["reason"] == "t1_peak_trail"


def test_hard_gap_beats_t1_trail_shenkeji():
    """深科技：今开已破买点硬保护，成交开盘，不得等到今开重置的 T1 回落。"""
    r = _m.eval_multi_tp_bar(
        bar_open=35.21,
        bar_high=35.30,
        bar_low=34.08,
        cost_px=36.35,
        peak_before=36.50,
        shares=2400,
        can_sell=True,
        overnight_armed=True,
        day_open=35.21,
        session_peak_before=36.50,
    )
    assert r["action"]["kind"] == "full"
    assert r["action"]["reason"] == "hard_from_cost"
    assert abs(float(r["action"]["fill_px"]) - 35.21) < 1e-9
    lv = _m.strategy_levels(
        35.21,
        cost_px=36.35,
        peak_high=36.50,
        overnight_armed=True,
    )
    assert lv["stop"] >= _m.cost_hard_stop_px(36.35) - 1e-12
    assert lv["stop"] > 34.32


def test_multi_tp_overnight_skips_trail_when_live_ok():
    # 浮盈已 >3%：不再走峰值回落 2.5%，改走中段（一半 102.50 先于波动 102.375）
    skip = _m.eval_multi_tp_bar(
        bar_open=103.0,
        bar_high=103.5,
        bar_low=101.8,
        cost_px=100.0,
        peak_before=105.0,
        shares=1000,
        can_sell=True,
        overnight_armed=True,
        day_open=103.0,
        vol20_daily=0.05,
    )
    assert skip["action"]["kind"] == "full"
    assert skip["action"]["reason"] == "half_gain"
    assert abs(float(skip["action"]["fill_px"]) - 102.50) < 1e-9


def test_live_last_half_gain():
    bars = _bars([(106.0, 105.0)])
    bad = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        seed_high=100.0,
        cost_px=100.0,
        live_high=106.0,
        live_low=102.9,
        vol20_daily=0.05,
    )
    assert bad["hit_stop"] is True
    ok = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        seed_high=100.0,
        cost_px=100.0,
        live_high=106.0,
        live_low=103.5,
        vol20_daily=0.05,
    )
    assert ok["hit_stop"] is False, ok


def test_open_only_skips_attack_wave():
    """关掉攻击波后：先低后反弹未到开盘+阈值 → 不买；摸到开盘阈值 → 按开盘突破买。"""
    sim = _m.simulate_factor26_day_1m
    rebound = _bars([(99.0, 98.0), (101.0, 100.5)])
    miss = sim(
        rebound,
        open_px=100.0,
        entry_pct=0.025,
        holding_in=False,
        can_sell=False,
        allow_entry=True,
        allow_attack=False,
    )
    assert miss["bought_today"] is False, miss
    hit = sim(
        _bars([(103.0, 100.0)]),
        open_px=100.0,
        entry_pct=0.025,
        holding_in=False,
        can_sell=False,
        allow_entry=True,
        allow_attack=False,
    )
    assert hit["bought_today"] is True, hit
    assert hit["buy_kind"] == "open"


def test_simulate_day_buy_then_no_same_day_sell():
    sim = _m.simulate_factor26_day_1m
    bars = _bars([(103.0, 100.0), (104.0, 101.0), (103.0, 99.0)])
    out = sim(
        bars,
        open_px=100.0,
        entry_pct=0.025,
        pullback_pct=0.025,
        holding_in=False,
        can_sell=False,
        allow_entry=True,
    )
    assert out["bought_today"] is True
    assert out["buy_px"] is not None
    assert out["sell_px"] is None
    assert out["holding_out"] is True


def test_simulate_overnight_hard_protect():
    sim = _m.simulate_factor26_day_1m
    bars = _bars([(100.0, 99.0), (100.5, 97.0)])
    out = sim(
        bars,
        open_px=100.0,
        pullback_pct=0.025,
        holding_in=True,
        can_sell=True,
        allow_entry=False,
        cost_px=100.0,
        peak_high_in=100.0,
    )
    assert out["sell_px"] is not None
    assert abs(float(out["sell_px"]) - 97.5) < 1e-9
    assert out["holding_out"] is False


def test_since_buy_ignores_pre_entry_dip():
    ts0 = pd.Timestamp("2026-09-07 09:31:00")
    bars = pd.DataFrame(
        [
            {"ts": ts0, "high": 100.0, "low": 99.0},
            {"ts": ts0 + pd.Timedelta(minutes=29), "high": 100.2, "low": 97.0},
            {"ts": ts0 + pd.Timedelta(hours=4), "high": 112.0, "low": 109.0},
        ]
    )
    assert path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=100.0, cost_px=100.0
    )["hit_stop"] is True
    out = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        since_ts="2026-09-07 13:00:00",
        seed_high=109.0,
        cost_px=109.0,
        live_high=112.0,
        live_low=111.0,
    )
    assert out["hit_stop"] is False, out


def test_micro_peak_giveback_does_not_note():
    """天通 2026-09-07：+6% 买入后封涨停，收盘盈利≥3% 不把回落记到次日。"""
    ts0 = pd.Timestamp("2026-09-07 09:32:00")
    sim = _m.simulate_factor26_day_1m
    bought = pd.DataFrame(
        [
            {"ts": ts0, "open": 27.69, "high": 28.20, "low": 27.68, "close": 28.09},
            {
                "ts": ts0 + pd.Timedelta(minutes=1),
                "open": 28.09,
                "high": 28.49,
                "low": 28.00,
                "close": 28.36,
            },
            {
                "ts": ts0 + pd.Timedelta(minutes=6),
                "open": 28.81,
                "high": 28.89,
                "low": 28.78,
                "close": 28.89,
            },
        ]
    )
    # 开盘 27.12 → 开盘突破约 27.94；09:32 高 28.20 买入后封涨停
    day = sim(
        bought,
        open_px=27.12,
        entry_pct=0.03,
        pullback_pct=0.03,
        holding_in=False,
        can_sell=False,
        allow_entry=True,
        prev_close=26.26,
    )
    assert day["bought_today"] is True
    assert day.get("stop_noted_out") in (None, 0, 0.0)


def test_t1_overnight_note_profit_gates():
    """买入日：盈利≥3%不记；盈利<3%记 T1 峰值回落；亏损≥2.5%记硬保护。"""
    fn = _m.resolve_t1_overnight_note
    ge = fn(cost_px=100.0, peak_high=110.0, close_px=103.0, hard_pct=0.025)
    assert ge["noted_px"] is None
    assert ge["reason"] == "profit_ge_3pct"
    wick_then_win = fn(
        cost_px=100.0,
        peak_high=110.0,
        close_px=110.0,
        hard_pct=0.025,
        bar_low=97.0,
    )
    assert wick_then_win["reason"] == "profit_ge_3pct"
    assert wick_then_win["noted_px"] is None
    lt = fn(cost_px=100.0, peak_high=102.0, close_px=100.5, hard_pct=0.025)
    assert lt["reason"] == "t1_trail"
    assert abs(float(lt["noted_px"]) - 100.0) < 1e-9
    hard = fn(cost_px=100.0, peak_high=100.0, close_px=97.0, hard_pct=0.025, bar_low=97.0)
    assert hard["reason"] == "hard_from_cost"
    assert abs(float(hard["noted_px"]) - 97.5) < 1e-9
    small = fn(cost_px=100.0, peak_high=100.0, close_px=99.0, hard_pct=0.025, bar_low=99.0)
    assert small["noted_px"] is not None
    assert small["reason"] == "t1_trail"


def test_overnight_session_high_requires_prev_strategy_position():
    """隔夜高点：只有昨日策略持有或策略买入才启用。天通今日新买不合格。"""
    fn = _m.overnight_session_high_ok
    assert (
        fn(
            qty=3200,
            buy_time="2026-09-14 10:08:53",
            session="2026-09-14",
        )
        is False
    )
    assert (
        fn(
            qty=0,
            buy_time=None,
            session="2026-09-14",
            replay_holding=False,
            last_buy_date="2026-09-14",
            last_sell_date="2026-09-07",
        )
        is False
    )
    assert (
        fn(
            qty=2600,
            buy_time="2026-09-11 09:43:32",
            session="2026-09-14",
        )
        is True
    )
    assert (
        fn(
            qty=0,
            buy_time="2026-09-11 09:43:32",
            session="2026-09-14",
        )
        is True
    )
    assert (
        fn(
            qty=0,
            session="2026-09-14",
            replay_holding=True,
            last_buy_date="2026-09-11",
            last_sell_date="2026-09-07",
        )
        is True
    )


def test_today_buy_open_protect_ignores_prev_high():
    """今日新买：开盘保护只用硬保护，不用昨收/昨高。"""
    hard = _m.overnight_open_protect_px(
        27.81,
        27.48,
        peak_high=30.23,
        use_prev_session_high=False,
    )
    overnight = _m.overnight_open_protect_px(
        27.81,
        27.48,
        peak_high=30.23,
        use_prev_session_high=True,
    )
    omitted = _m.overnight_open_protect_px(27.81, 27.48, peak_high=30.23)
    assert abs(hard - _m.cost_hard_stop_px(27.81)) < 1e-9
    assert abs(omitted - hard) < 1e-9
    assert overnight > hard + 0.2


def test_overnight_peak_px_requires_gate():
    """昨收/昨高只经 overnight_peak_px；看买入日，不必再传开关。"""
    assert _m.overnight_peak_px(27.81, 27.48, 30.23) == 0.0
    assert (
        _m.overnight_peak_px(
            27.81,
            27.48,
            30.23,
            buy_time="2026-09-14 10:08:53",
            session="2026-09-14",
        )
        == 0.0
    )
    peak = _m.overnight_peak_px(
        33.48,
        34.49,
        34.78,
        buy_time="2026-09-11 09:43:32",
        session="2026-09-14",
    )
    assert abs(peak - 34.78) < 1e-9
    assert _m.overnight_peak_px(
        27.81, 27.48, 30.23, overnight_high_ok=False
    ) == 0.0
    assert abs(
        _m.overnight_peak_px(
            27.81, 27.48, 30.23, overnight_high_ok=True
        )
        - 30.23
    ) < 1e-9


def test_simulate_flat_ignores_injected_prev_peak():
    """空仓不得把传入的昨高/昨收种进峰值。"""
    ts0 = pd.Timestamp("2026-09-14 09:31:00")
    bars = pd.DataFrame(
        [
            {
                "ts": ts0,
                "open": 27.90,
                "high": 28.00,
                "low": 27.65,
                "close": 27.80,
            }
        ]
    )
    out = _m.simulate_factor26_day_1m(
        bars,
        open_px=27.90,
        holding_in=False,
        can_sell=False,
        allow_entry=False,
        peak_high_in=30.23,
        prev_close=27.48,
        overnight_high_ok=True,
    )
    assert out.get("bought_today") is False
    assert float(out.get("peak_high_out") or 0) == 0.0
    assert out.get("sell_px") is None


def test_open_auction_touch_ts_rewrites_first_bar_label():
    """竞价核：首根 1m 标成 09:32、成交价=开盘 → 记 09:30。"""
    ts = pd.Timestamp("2026-09-14 09:32:00")
    assert (
        _m.open_auction_touch_ts(
            ts, fill_px=16.93, day_open=16.93, first_bar=True
        )
        == "2026-09-14 09:30:00"
    )
    assert (
        _m.open_auction_touch_ts(
            ts, fill_px=16.80, day_open=16.93, first_bar=True
        )
        == ts
    )
    later = pd.Timestamp("2026-09-14 09:45:00")
    assert (
        _m.open_auction_touch_ts(
            later, fill_px=16.93, day_open=16.93, first_bar=False
        )
        == later
    )
    # 即使误标 first_bar，非 09:31/09:32 也不得因 fill≈open 改写
    assert (
        _m.open_auction_touch_ts(
            later, fill_px=16.93, day_open=16.93, first_bar=True
        )
        == later
    )


def test_path_hit_open_fill_uses_0930_not_first_1m_label():
    """特发：今开已破回落一半，第一根 1m 即使标 09:32 也记 09:30 开盘成交。"""
    ts0 = pd.Timestamp("2026-09-14 09:32:00")
    bars = pd.DataFrame(
        [
            {
                "ts": ts0,
                "open": 16.93,
                "high": 16.95,
                "low": 16.80,
                "close": 16.88,
            }
        ]
    )
    hit = _m.path_dependent_pullback_hit(
        bars,
        seed_high=17.65,
        cost_px=16.29,
        day_open=16.93,
        overnight_armed=False,
    )
    assert hit.get("hit_stop") is True
    assert abs(float(hit.get("touch_stop") or 0) - 16.93) < 1e-6
    ts_s = str(hit.get("touch_ts") or "")
    assert "09:30:00" in ts_s
    assert "09:32" not in ts_s


def test_today_buy_first_session_fill_ignores_prev_close():
    """今日新买：1m 第一次成交不得把昨收当隔夜峰值去武装 T1。"""
    ts0 = pd.Timestamp("2026-09-14 09:31:00")
    bars = pd.DataFrame(
        [
            {
                "ts": ts0,
                "open": 27.90,
                "high": 28.00,
                "low": 27.65,
                "close": 27.80,
            }
        ]
    )
    leaked = _m.first_session_exit_fill(
        bars,
        cost_px=27.81,
        prev_close=28.40,
        day_open=27.90,
        overnight_high_ok=True,
    )
    gated = _m.first_session_exit_fill(
        bars,
        cost_px=27.81,
        prev_close=28.40,
        day_open=27.90,
        overnight_high_ok=False,
    )
    assert leaked is not None
    assert gated is None


def test_limit_up_clears_t1_note():
    """T+1 曾因回吐记价，随后封涨停应收盘作废已记。"""
    inv = _m.stop_note_invalidated_by_recovery
    assert inv(last_px=28.89, noted_px=28.06, prev_close=26.26) is True
    assert inv(last_px=28.10, noted_px=28.06, prev_close=26.26) is False
    ts0 = pd.Timestamp("2026-09-07 09:31:00")
    bars = pd.DataFrame(
        [
            {"ts": ts0, "open": 100.0, "high": 110.0, "low": 109.0, "close": 109.5},
            {
                "ts": ts0 + pd.Timedelta(minutes=1),
                "open": 109.0,
                "high": 110.0,
                "low": 104.0,
                "close": 105.0,
            },
            {
                "ts": ts0 + pd.Timedelta(minutes=2),
                "open": 110.0,
                "high": 110.0,
                "low": 109.8,
                "close": 110.0,
            },
        ]
    )
    sim = _m.simulate_factor26_day_1m
    out = sim(
        bars,
        open_px=100.0,
        entry_pct=0.025,
        pullback_pct=0.025,
        holding_in=False,
        can_sell=False,
        allow_entry=True,
        prev_close=100.0,
    )
    assert out["bought_today"] is True
    # 第二根低点触回吐，第三根封涨停 → 已记作废
    assert out.get("stop_noted_out") in (None, 0, 0.0), out


def test_open_only_near_buy_ignores_attack_from_dump():
    """生产关闭攻击波：一字开板下砸后，不得用低点派生价触发「将买入」。"""
    from strategy.pullback_wave_stop import strategy_levels, strategy_signal

    lv = strategy_levels(
        4.8,
        entry_pct=0.03,
        pullback_pct=0.025,
        high_px=4.8,
        low_px=4.51,
        allow_attack=False,
    )
    assert abs(float(lv["open_buy"]) - 4.95) < 1e-9
    assert abs(float(lv["attack_buy"]) - 4.65) < 1e-9
    assert abs(float(lv["buy_trigger"]) - 4.95) < 1e-9

    sig = strategy_signal(
        open_px=4.8,
        high_px=4.8,
        low_px=4.51,
        last_px=4.66,
        session="2026-09-10",
        qty=0,
        buy_time=None,
        vs_open_pts=-2.92,
        entry_pct=0.03,
        stop_pct=0.025,
        allow_entry=True,
        allow_attack=False,
        buy_trigger=4.65,  # 故意传入攻击波价，也应被忽略
    )
    assert sig.get("alert") == "空仓"
    assert abs(float(sig.get("因子价") or 0) - 4.95) < 1e-9
    assert "将买入" not in str(sig.get("alert") or "")


def test_first_session_exit_fill_uses_path_not_open_gap():
    """隔夜已过 3%：第一次卖出价走 1m 触达，不是用今开去撞盘中抬高后的止损。"""
    ts0 = pd.Timestamp("2026-09-11 09:31:00")
    bars = pd.DataFrame(
        [
            {
                "ts": ts0,
                "open": 76.0,
                "high": 76.99,
                "low": 75.90,
                "close": 76.92,
            },
            {
                "ts": ts0 + pd.Timedelta(minutes=8),
                "open": 76.09,
                "high": 77.34,
                "low": 76.00,
                "close": 77.30,
            },
        ]
    )
    fill = _m.first_session_exit_fill(
        bars,
        cost_px=70.21,
        prev_close=76.45,
        day_open=76.0,
        overnight_high_ok=True,
    )
    assert fill is not None
    assert abs(float(fill) - 77.23) < 0.02
    assert abs(float(fill) - 76.0) > 0.01


def test_simulate_ladder_half_reduces_shares_then_peak_trail_clears_rest():
    """隔夜仓：先 10% 半仓减股，再峰值回落 2% 清剩余；不得把半仓当成「只改状态不清仓」。"""
    ts0 = pd.Timestamp("2026-09-09 09:31:00")
    bars = pd.DataFrame(
        [
            {"ts": ts0, "open": 111.0, "high": 111.2, "low": 110.6, "close": 111.0},
            {
                "ts": ts0 + pd.Timedelta(minutes=1),
                "open": 109.5,
                "high": 109.8,
                "low": 107.5,
                "close": 108.0,
            },
        ]
    )
    sim = _m.simulate_factor26_day_1m(
        bars,
        open_px=111.0,
        holding_in=True,
        can_sell=True,
        allow_entry=False,
        cost_px=100.0,
        peak_high_in=100.0,
    )
    assert sim.get("half_px") is not None, sim
    assert abs(float(sim["half_px"]) - 110.0) < 1e-9
    assert int(sim.get("half_shares") or 0) == 500
    assert sim.get("sell_px") is not None, sim
    assert sim.get("sell_reason") == "peak_pullback_clear"
    assert sim.get("holding_out") is False
    assert int(sim.get("shares_out") or 0) == 0


def test_working_stop_not_ladder_when_peak_already_extended():
    """隔夜峰值已过 10%/15% 时，未触达的工作卖价必须是峰值回落 2%，不能是阶梯目标。"""
    # 峰值 112、今日高未再过 10%、低未破 112×0.98
    mid = path_dependent_pullback_hit(
        _bars([(109.90, 109.85)]),
        pullback_pct=0.025,
        seed_high=112.0,
        cost_px=100.0,
    )
    assert mid["hit_stop"] is False, mid
    assert abs(float(mid["stop_px"]) - 109.76) < 1e-9, mid
    assert mid["stop_kind"] == "peak_pullback"
    # 峰值 116：无新 1m 时工作线必须是 113.68，不能是阶梯 115
    kind, px = _m.working_stop_price(cost_px=100.0, peak_high=116.0)
    assert kind == "peak_pullback"
    assert abs(float(px) - 113.68) < 1e-9
    empty = path_dependent_pullback_hit(
        _bars([]),
        pullback_pct=0.025,
        seed_high=116.0,
        cost_px=100.0,
    )
    assert empty["hit_stop"] is False, empty
    assert abs(float(empty["stop_px"]) - 113.68) < 1e-9, empty
    assert empty["stop_kind"] == "peak_pullback"


def test_path_dependent_ladder_half_uses_real_shares_and_stage():
    """盯盘路径：真实股数 + tp_stage；半仓后 exclusive since 不再打同一根 10% K。"""
    ts0 = pd.Timestamp("2026-09-08 10:00:00")
    bars = pd.DataFrame(
        [
            {
                "ts": ts0,
                "open": 110.5,
                "high": 111.0,
                "low": 110.4,
                "close": 110.8,
            },
            {
                "ts": ts0 + pd.Timedelta(minutes=1),
                "open": 109.5,
                "high": 109.8,
                "low": 109.2,
                "close": 109.4,
            },
        ]
    )
    first = path_dependent_pullback_hit(
        bars,
        cost_px=100.0,
        seed_high=100.0,
        shares=400,
        tp_stage=0,
    )
    assert first["hit_stop"] is True, first
    assert first["action_kind"] == "half", first
    assert first["stop_kind"] == "ladder_half_10", first
    assert int(first["sell_shares"]) == 200, first
    # 半仓后从触达分钟 exclusive 再放：同一根 10% 不得再打
    after = path_dependent_pullback_hit(
        bars,
        cost_px=100.0,
        seed_high=111.0,
        shares=200,
        tp_stage=1,
        since_ts=first["touch_ts"],
        since_exclusive=True,
    )
    assert after["hit_stop"] is False, after
    assert after.get("action_kind") in ("", None)
    # 若忘记推进 since / stage，同一根会把剩余当「10% 后再触 10%」清掉
    replay = path_dependent_pullback_hit(
        bars,
        cost_px=100.0,
        seed_high=100.0,
        shares=200,
        tp_stage=0,
    )
    assert replay["hit_stop"] is True
    assert replay["action_kind"] == "half"


def test_strategy_signal_half_alert_not_full_stop():
    sig = _m.strategy_signal(
        open_px=100.0,
        high_px=111.0,
        low_px=110.5,
        last_px=110.8,
        session="2026-09-08",
        qty=400,
        buy_time="2026-09-07 10:00:00",
        vs_open_pts=10.8,
        cost_px=100.0,
        peak_high=111.0,
        t0=True,
        hit_stop=True,
        stop_kind="ladder_half_10",
        stop_px=110.0,
    )
    assert sig.get("alert") == "半仓止盈", sig
    assert "阶梯10%半仓" in str(sig.get("挂单说明") or ""), sig


def test_strategy_signal_hang_text_is_multi_tp():
    """持仓挂单说明必须写多层止盈工作线，不能再写「回落波=分时最高×(1-2.5%)」。"""
    sig = _m.strategy_signal(
        open_px=100.0,
        high_px=105.0,
        low_px=104.0,
        last_px=104.5,
        session="2026-09-08",
        qty=100,
        buy_time="2026-09-07 10:00:00",
        vs_open_pts=4.5,
        cost_px=100.0,
        peak_high=105.0,
        t0=True,
    )
    note = str(sig.get("挂单说明") or "")
    assert "回落波止损" not in note, note
    assert "中赚回落一半" in note or "中赚波动回落" in note, note
    assert sig.get("stop_kind") in ("half_gain", "vol_giveback")


def test_simulate_ladder_half_only_keeps_remainder():
    """只触 10%、未触回落：应半仓后继续持有剩余。"""
    ts0 = pd.Timestamp("2026-09-09 09:31:00")
    bars = pd.DataFrame(
        [{"ts": ts0, "open": 111.0, "high": 111.2, "low": 110.6, "close": 111.0}]
    )
    sim = _m.simulate_factor26_day_1m(
        bars,
        open_px=111.0,
        holding_in=True,
        can_sell=True,
        allow_entry=False,
        cost_px=100.0,
        peak_high_in=100.0,
    )
    assert sim.get("holding_out") is True, sim
    assert sim.get("sell_px") is None, sim
    assert int(sim.get("shares_out") or 0) == 500
    assert int(sim.get("tp_stage_out") or 0) == 1
    sim2 = _m.simulate_factor26_day_1m(
        _bars([(111.2, 110.8)]),
        open_px=111.0,
        holding_in=True,
        can_sell=True,
        allow_entry=False,
        cost_px=100.0,
        peak_high_in=111.2,
        tp_stage_in=1,
        shares_in=500,
    )
    assert sim2.get("holding_out") is True, sim2
    assert sim2.get("sell_px") is None, sim2
    assert int(sim2.get("shares_out") or 0) == 500


if __name__ == "__main__":
    test_half_gain_formula()
    test_multi_tp_ladder_and_peak_once()
    test_mid_gain_race_half_vs_vol()
    test_multi_tp_mid_gain_giveback_and_small_profit_no_giveback()
    test_multi_tp_overnight_dump()
    test_snapshot_high_must_not_seed_before_morning_low()
    test_attack_buy_same_bar_low_and_high_rejected()
    test_attack_buy_snapshot_lookahead_rejected()
    test_daily_ohlc_false_positive_avoided()
    test_hard_protect_path_hit()
    test_half_gain_after_peak()
    test_live_last_half_gain()
    test_simulate_day_buy_then_no_same_day_sell()
    test_open_only_skips_attack_wave()
    test_open_only_near_buy_ignores_attack_from_dump()
    test_simulate_overnight_hard_protect()
    test_since_buy_ignores_pre_entry_dip()
    test_micro_peak_giveback_does_not_note()
    test_t1_overnight_note_profit_gates()
    test_overnight_session_high_requires_prev_strategy_position()
    test_today_buy_open_protect_ignores_prev_high()
    test_overnight_peak_px_requires_gate()
    test_simulate_flat_ignores_injected_prev_peak()
    test_open_auction_touch_ts_rewrites_first_bar_label()
    test_path_hit_open_fill_uses_0930_not_first_1m_label()
    test_today_buy_first_session_fill_ignores_prev_close()
    test_limit_up_clears_t1_note()
    test_first_session_exit_fill_uses_path_not_open_gap()
    test_simulate_ladder_half_reduces_shares_then_peak_trail_clears_rest()
    test_simulate_ladder_half_only_keeps_remainder()
    test_working_stop_not_ladder_when_peak_already_extended()
    test_path_dependent_ladder_half_uses_real_shares_and_stage()
    test_strategy_signal_half_alert_not_full_stop()
    test_strategy_signal_hang_text_is_multi_tp()
    print("ok")
