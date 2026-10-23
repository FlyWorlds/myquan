from strategy.strategies.strategy3.panic_study import current_panic, summarize


def test_panic_uses_ready_denominator_and_invalid_scan_is_missing():
    scan=dict(scanned_count=2,universe_count=3,rows=[dict(status='ready',warning=True),dict(status='ready',warning=False),dict(status='stale',warning=True)])
    p=current_panic(scan,True)
    assert p['rate']==.5 and p['coverage']==2/3 and p['warningCount']==1
    assert current_panic(scan,False)['rate'] is None
    assert current_panic({},True)['rate'] is None


def test_buckets_boundary_zero_profit_and_empty():
    rows=[dict(panic_pct=10,horizon=10,return_pct=0,signal_date='2026-01-01'),dict(panic_pct=100,horizon=10,return_pct=2,signal_date='2026-01-02')]
    buckets=summarize(rows)
    assert len(buckets)==30
    first=next(b for b in buckets if b['label']=='0–10%' and b['horizon']==10)
    second=next(b for b in buckets if b['label']=='10–20%' and b['horizon']==10)
    last=next(b for b in buckets if b['label']=='90–100%' and b['horizon']==10)
    assert first['n']==0 and first['winRate'] is None
    assert second['n']==1 and second['winRate']==0
    assert last['n']==1 and last['winRate']==1
