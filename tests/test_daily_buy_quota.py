from holdingStocks.daily_buy_quota import counts, quota_reason
DAY='2026-10-28'
def t(code,side='buy',**kw):
    return dict(code=code,side=side,session=DAY,**kw)
def test_two_new_reserve_one_rebuy():
    rows=[t('A'),t('B')]
    assert quota_reason(rows,DAY,is_rebuy=False)=='MAX_DAILY_NEW_BUY_FILLS'
    assert quota_reason(rows,DAY,is_rebuy=True) is None
    rows += [t('A','sell'),t('A')]
    assert counts(rows,DAY)==dict(new=2,rebuy=1,total=3)
    assert quota_reason(rows,DAY,is_rebuy=True)=='MAX_DAILY_BUY_FILLS'
def test_rebuy_first_does_not_consume_new_allowance():
    rows=[t('X','sell'),t('X'),t('A')]
    assert quota_reason(rows,DAY,is_rebuy=True)=='MAX_DAILY_REBUY_FILLS'
    assert quota_reason(rows,DAY,is_rebuy=False) is None
    assert counts(rows+[t('B',reset_archived=True)],DAY)['total']==2
