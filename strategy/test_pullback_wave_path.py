"""因子26：1 分钟 path-dependent 止损触达（防全日 OHLC 假触）。"""

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
pullback_stop_price = _m.pullback_stop_price


def _bars(rows: list[tuple[float, float]]) -> pd.DataFrame:
    ts0 = pd.Timestamp("2026-09-07 09:31:00")
    return pd.DataFrame(
        [
            {"ts": ts0 + pd.Timedelta(minutes=i), "high": h, "low": lo}
            for i, (h, lo) in enumerate(rows)
        ]
    )


def test_daily_ohlc_false_positive_avoided():
    bars = _bars([(100.0, 98.0), (110.0, 108.0)])
    day_high, day_low = 110.0, 98.0
    stop_now = pullback_stop_price(day_high, pullback_pct=0.025)
    assert day_low <= stop_now
    out = path_dependent_pullback_hit(bars, pullback_pct=0.025)
    assert out["hit_stop"] is False, out


def test_true_path_hit():
    bars = _bars([(100.0, 99.0), (100.5, 97.0)])
    out = path_dependent_pullback_hit(bars, pullback_pct=0.025)
    assert out["hit_stop"] is True, out


def test_live_last_not_day_low():
    bars = _bars([(100.0, 99.0), (110.0, 108.0)])
    bad = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, live_high=110.0, live_low=98.0
    )
    assert bad["hit_stop"] is True
    ok = path_dependent_pullback_hit(
        bars, pullback_pct=0.025, live_high=110.0, live_low=109.0
    )
    assert ok["hit_stop"] is False, ok


def test_touch_stop_is_prior_high_stop_not_raised():
    """触达价应是破位当时止损，不是之后抬高的止损。"""
    bars = _bars([(100.0, 99.0), (110.0, 97.0)])
    out = path_dependent_pullback_hit(bars, pullback_pct=0.025)
    assert out["hit_stop"] is True
    assert abs(float(out["touch_stop"]) - 97.5) < 1e-9, out
    raised = pullback_stop_price(110.0, pullback_pct=0.025)
    assert raised > float(out["touch_stop"])


def test_simulate_day_buy_then_no_same_day_sell():
    sim = _m.simulate_factor26_day_1m
    # 开盘 100，突破 102.5；其后回落不卖（T+1）
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


def test_simulate_overnight_stop_path():
    sim = _m.simulate_factor26_day_1m
    bars = _bars([(100.0, 99.0), (100.5, 97.0)])
    out = sim(
        bars,
        open_px=100.0,
        pullback_pct=0.025,
        holding_in=True,
        can_sell=True,
        allow_entry=False,
    )
    assert out["sell_px"] is not None
    assert abs(float(out["sell_px"]) - 97.5) < 1e-9
    assert out["holding_out"] is False


def test_since_buy_ignores_pre_entry_dip():
    """买入前曾破止损路径，买入后上涨 → 不应算持仓已触止损。"""
    ts0 = pd.Timestamp("2026-09-07 09:31:00")
    bars = pd.DataFrame(
        [
            {"ts": ts0, "high": 100.0, "low": 99.0},
            # 10:00 相对 100 的止损 97.5 被击穿
            {"ts": ts0 + pd.Timedelta(minutes=29), "high": 100.2, "low": 97.0},
            # 午后新高并持稳（13:00 后买入）
            {"ts": ts0 + pd.Timedelta(hours=4), "high": 112.0, "low": 109.0},
        ]
    )
    assert path_dependent_pullback_hit(bars, pullback_pct=0.025)["hit_stop"] is True
    out = path_dependent_pullback_hit(
        bars,
        pullback_pct=0.025,
        since_ts="2026-09-07 13:00:00",
        seed_high=109.0,
        live_high=112.0,
        live_low=111.0,
    )
    assert out["hit_stop"] is False, out


if __name__ == "__main__":
    test_daily_ohlc_false_positive_avoided()
    test_true_path_hit()
    test_live_last_not_day_low()
    test_touch_stop_is_prior_high_stop_not_raised()
    test_simulate_day_buy_then_no_same_day_sell()
    test_simulate_overnight_stop_path()
    test_since_buy_ignores_pre_entry_dip()
    print("ok")
