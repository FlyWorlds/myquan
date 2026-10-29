"""Portfolio-wide daily fill limits; reconstruct counts from committed trades."""

def counts(trades, session):
    sold = set()
    new = rebuy = 0
    rows = [t for t in trades if not t.get('reset_archived') and
            str(t.get('session') or t.get('time') or t.get('ts') or '')[:10] == session]
    rows.sort(key=lambda t: str(t.get('time') or t.get('ts') or ''))
    for t in rows:
        side = str(t.get('side') or '').lower()
        code = str(t.get('code') or '')
        if side in ('sell', '卖出'):
            sold.add(code)
        elif side in ('buy', '买入'):
            if t.get('is_rebuy') or code in sold:
                rebuy += 1
            else:
                new += 1
    return dict(new=new, rebuy=rebuy, total=new+rebuy)


def quota_reason(trades, session, *, is_rebuy):
    n = counts(trades, session)
    if n['total'] >= 3:
        return 'MAX_DAILY_BUY_FILLS'
    if is_rebuy and n['rebuy'] >= 1:
        return 'MAX_DAILY_REBUY_FILLS'
    if not is_rebuy and n['new'] >= 2:
        return 'MAX_DAILY_NEW_BUY_FILLS'
    return None
