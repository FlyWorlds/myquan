"""大阳过门固定 5%，不得随买入突破阈值漂移。"""
import pytest

from strategy.binding_filters import open_break_entry_filter
from strategy.open_break import entry_filters_ok, prev_day_allows_entry


@pytest.mark.parametrize('entry_pct', [0.015, 0.025, 0.06])
@pytest.mark.parametrize('close,allowed', [(10.25, True), (10.49, True), (10.50, False), (10.51, False)])
def test_big_yang_boundary_is_independent_of_entry(entry_pct, close, allowed):
    assert entry_filters_ok(10, close, 10, 9.9, entry_pct=entry_pct) is allowed
    assert open_break_entry_filter(10, close, 10, 9.9, entry_pct=entry_pct) is allowed
    assert prev_day_allows_entry(10, close, prev2_close=9.9) is allowed


def test_other_gates_remain_enabled():
    assert not entry_filters_ok(10.4, 10.6, 10, 10.2)  # 双阳跨日 >= 5%
    assert entry_filters_ok(10, 9.9, 10, 10)  # 阴线
    assert entry_filters_ok(10.5, 10.5, 10, 10)  # 十字涨幅恰好 5%
    assert not entry_filters_ok(10.51, 10.51, 10, 10)
    assert not entry_filters_ok(None, None)
