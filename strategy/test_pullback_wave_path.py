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
_m = _load(
    "strategy.pullback_wave_stop",
    _DIR / "pullback_wave_stop.py",
    inject={"strategy.open_break": _ob},
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
    """中赚峰值106后回落超过 0.5×日频波动（测试用 5%）触达。"""
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
    # 已半仓后再触 10% → 清剩余
    clr = ev(
        bar_open=110.0,
        bar_high=111.0,
        bar_low=110.5,
        cost_px=100.0,
        peak_before=110.0,
        shares=500,
        can_sell=True,
        tp_stage=1,
    )
    assert clr["action"]["kind"] == "full"
    assert "clear" in clr["action"]["reason"]


def test_multi_tp_mid_gain_giveback_and_small_profit_no_giveback():
    """中赚 >3% 且 <10% 才走波动回落；小赚不回落。"""
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
    assert mid["action"]["reason"] == "vol_giveback"
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
    # 浮盈已 >3%：不再走峰值回落 2.5%，改走波动回落
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
    assert skip["action"]["reason"] == "vol_giveback"


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
    lt = fn(cost_px=100.0, peak_high=102.0, close_px=100.5, hard_pct=0.025)
    assert lt["reason"] == "t1_trail"
    assert abs(float(lt["noted_px"]) - 100.0) < 1e-9
    hard = fn(cost_px=100.0, peak_high=100.0, close_px=97.0, hard_pct=0.025, bar_low=97.0)
    assert hard["reason"] == "hard_from_cost"
    assert abs(float(hard["noted_px"]) - 97.5) < 1e-9
    small = fn(cost_px=100.0, peak_high=100.0, close_px=99.0, hard_pct=0.025, bar_low=99.0)
    assert small["noted_px"] is not None
    assert small["reason"] == "t1_trail"


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


if __name__ == "__main__":
    test_half_gain_formula()
    test_multi_tp_ladder_and_peak_once()
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
    test_simulate_overnight_hard_protect()
    test_since_buy_ignores_pre_entry_dip()
    test_micro_peak_giveback_does_not_note()
    test_t1_overnight_note_profit_gates()
    test_limit_up_clears_t1_note()
    print("ok")
