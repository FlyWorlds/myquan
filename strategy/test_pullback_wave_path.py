"""因子26：1 分钟 path-dependent 浮盈回落一半触达。"""

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


def test_snapshot_high_must_not_seed_before_morning_low():
    """隔夜成本 28.2；早盘低 29.5、午后才到 31。若把 31 种进 seed 会误触 29.6。"""
    bars = _bars([(29.8, 29.5), (31.0, 30.5), (30.8, 29.7)])
    ok = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=28.2, cost_px=28.2
    )
    assert ok["hit_stop"] is False, ok
    bad = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=31.0, cost_px=28.2
    )
    assert bad["hit_stop"] is True, bad


def test_attack_buy_same_bar_low_and_high_rejected():
    """同一根 1m：低 90、高 94。须先有更早低点，不能本分钟自造攻击波。"""
    bars = _bars([(94.0, 90.0)])
    out = path_dependent_buy_hit(bars, open_px=100.0, entry_pct=0.025)
    assert out["hit_buy"] is False, out
    bars2 = _bars([(91.0, 90.0), (94.0, 93.0)])
    out2 = path_dependent_buy_hit(bars2, open_px=100.0, entry_pct=0.025)
    assert out2["hit_buy"] is True, out2
    assert out2["buy_kind"] == "attack"


def test_attack_buy_snapshot_lookahead_rejected():
    """早盘高 101、午后低 90：全日 OHLC 会假触发攻击波；1m 顺序不应买。"""
    bars = _bars([(101.0, 100.0), (91.0, 90.0)])
    out = path_dependent_buy_hit(bars, open_px=100.0, entry_pct=0.025)
    assert out["hit_buy"] is False, out


def test_daily_ohlc_false_positive_avoided():
    """早盘低、午后高：全日 OHLC 会假触发止损；1m 顺序不应卖。"""
    bars = _bars([(100.0, 98.0), (110.0, 108.0)])
    out = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=100.0, cost_px=100.0
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
    """峰值110后回落到105触浮盈一半。"""
    bars = _bars([(110.0, 109.0), (110.0, 105.0)])
    out = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, seed_high=100.0, cost_px=100.0
    )
    assert out["hit_stop"] is True, out
    assert abs(float(out["touch_stop"]) - 105.0) < 1e-9, out
    # 旧峰值2.5%卖价约107.25，本规则更宽
    old = pullback_stop_price(110.0, pullback_pct=0.025)
    assert float(out["touch_stop"]) < old


def test_live_last_half_gain():
    bars = _bars([(110.0, 109.0)])
    bad = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        seed_high=100.0,
        cost_px=100.0,
        live_high=110.0,
        live_low=104.0,
    )
    assert bad["hit_stop"] is True
    ok = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        seed_high=100.0,
        cost_px=100.0,
        live_high=110.0,
        live_low=106.0,
    )
    assert ok["hit_stop"] is False, ok


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


if __name__ == "__main__":
    test_half_gain_formula()
    test_snapshot_high_must_not_seed_before_morning_low()
    test_attack_buy_same_bar_low_and_high_rejected()
    test_attack_buy_snapshot_lookahead_rejected()
    test_daily_ohlc_false_positive_avoided()
    test_hard_protect_path_hit()
    test_half_gain_after_peak()
    test_live_last_half_gain()
    test_simulate_day_buy_then_no_same_day_sell()
    test_simulate_overnight_hard_protect()
    test_since_buy_ignores_pre_entry_dip()
    print("ok")
