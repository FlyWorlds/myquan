from datetime import datetime

import pandas as pd
import pytest

from strategy.factors.factor34 import compute, signal, tail_candidate
from strategy.core.factor_registry import get_factor


def bars():
    d = pd.DataFrame(dict(date=pd.bdate_range('2026-01-01', periods=63),
                         open=10., high=10., low=10., close=10., volume=100.))
    d.loc[59, 'volume'] = 20.
    d.loc[60:62, ['high', 'close', 'volume']] = [10.5, 10.5, 40.]
    return d


def test_anchor_warmup_boundary_and_once():
    d = compute(bars())
    assert not d.candidate.iloc[:60].any()
    assert d.candidate.iloc[60] and not d.candidate.iloc[61:].any()
    assert d.iloc[60].anchor_age == 1 and d.iloc[60].anchor_volume_ratio == 2


def test_prefix_invariance():
    data = bars()
    pd.testing.assert_frame_equal(compute(data.iloc[:61]), compute(data).iloc[:61])
    data.loc[62, ['volume', 'high', 'close']] = [10000, 20, 20]
    pd.testing.assert_frame_equal(compute(bars()).iloc[:61], compute(data).iloc[:61])


def test_price_body_is_not_previous_close_return():
    d = bars();d.loc[60:, ['open', 'high', 'close']] = [10.6, 10.6, 10.6]
    assert not compute(d).candidate.any()


def test_invalid_and_unconfirmed_data():
    d = bars(); d.loc[1, 'volume'] = float('nan')
    with pytest.raises(ValueError):compute(d)
    d = bars();d.loc[1, 'date'] = d.loc[0, 'date']
    with pytest.raises(ValueError):compute(d)
    d = bars().iloc[:61]
    with pytest.raises(ValueError): signal(d, as_of=d.date.iloc[-1].to_pydatetime().replace(hour=14,minute=55))
    result = signal(d, as_of=d.date.iloc[-1].to_pydatetime().replace(hour=15,minute=15))
    assert result['candidate'] and not result['hit_buy']


def test_anchor_expires_after_ten_sessions():
    d = pd.concat([bars().iloc[:60], bars().iloc[:12]], ignore_index=True)
    d['date'] = pd.bdate_range('2026-01-01',periods=len(d))
    d.loc[60:, 'volume'] = 30
    d.loc[69, ['high','close','volume']] = [10.5,10.5,40]
    assert compute(d).candidate.iloc[69]
    d.loc[69, ['high','close','volume']] = [10,10,30]
    d.loc[70, ['high','close','volume']] = [10.5,10.5,40]
    assert not compute(d).candidate.any()


def test_tail_observable_volume_freshness_and_consumption():
    h=bars().iloc[:60]
    now=bars().date.iloc[60].to_pydatetime().replace(hour=14,minute=55)
    q=dict(ts=now,open=10,high=10.5,low=10,last=10.5,volume=40,prev_close=10,source_verified=True)
    r=tail_candidate(h,quote=q,now=now)
    assert r['candidate'] and not r['hit_buy']
    assert not tail_candidate(h,quote={**q,'volume':39},now=now)['candidate']
    assert not tail_candidate(h,quote=q,now=now.replace(second=6))['candidate']
    assert not tail_candidate(h,quote={**q,'source_verified':False},now=now)['candidate']
    assert not tail_candidate(h,quote=q,now=now,consumed_anchors=[r['anchor_date']])['candidate']
    assert not tail_candidate(h,quote=q,now=now.replace(minute=57))['candidate']
    assert not tail_candidate(bars().iloc[:61],quote=q,now=now)['candidate']
    assert not tail_candidate(h,quote={**q,'high':11,'last':11},now=now)['candidate']


def test_registration_is_research_only():
    assert get_factor('factor34').meta['auto_trade'] is False
    from strategy import get_strategy_bindings
    for strategy in ['strategy1','strategy16']:
        assert not any(b.factor_id=='factor34' and b.enabled for b in get_strategy_bindings(strategy))
