"""策略隔离：各策略绑定独立，默认策略16，基础算法不含策略编号。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.binding_filters import open_break_entry_filter
from strategy.core.protocols import bind_factor
from strategy.core.strategy_registry import get_strategy_spec
from strategy.registry import get_strategy_bindings
import strategy.strategies  # noqa: F401  注册全部策略
from strategy.strategies.strategy1.decision import Strategy1Decision
from strategy.strategies.strategy16.decision import Strategy16Decision
from watch_config import FACTOR_ID, STRATEGY_ID


def test_default_watch_strategy_is_16():
    assert STRATEGY_ID == "strategy16"
    assert FACTOR_ID == "factor26"
    assert get_strategy_spec("strategy16").meta.get("default") is True
    assert get_strategy_spec("strategy1").meta.get("default") is False


def test_strategy16_does_not_share_binding_params_with_strategy1():
    s1 = next(b for b in get_strategy_bindings("strategy1") if b.factor_id == "factor26")
    s16 = next(b for b in get_strategy_bindings("strategy16") if b.factor_id == "factor26")
    assert s1 is not s16
    assert s1.params is not s16.params
    orig = s1.params.get("entry_pct")
    try:
        s1.params["entry_pct"] = 0.999
        assert s16.params.get("entry_pct") == orig
    finally:
        s1.params["entry_pct"] = orig


def test_strategy16_universe_independent_of_strategy1():
    ids1 = {b.factor_id for b in get_strategy_bindings("strategy1")}
    ids16 = {b.factor_id for b in get_strategy_bindings("strategy16")}
    assert "factor13a" in ids1 and "factor16" in ids1
    assert "factor27" in ids16
    assert "factor13a" not in ids16
    assert "factor27" not in ids1


def test_decision_engines_are_separate_types():
    e1 = Strategy1Decision()
    e16 = Strategy16Decision()
    assert e1.strategy_id == "strategy1"
    assert e16.strategy_id == "strategy16"
    assert type(e1) is not type(e16)
    assert e1.__class__.__mro__[1].__name__ == "Factor26Decision"
    assert e16.__class__.__mro__[1].__name__ == "Factor26Decision"


def test_open_break_filter_is_strategy_agnostic():
    assert open_break_entry_filter.__module__ == "strategy.binding_filters"
    b = bind_factor("factor26", entry_pct=0.02, filter=open_break_entry_filter)
    assert b.filter is open_break_entry_filter
