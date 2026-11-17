"""Portfolio-wide daily fill limits; reconstruct counts from committed trades."""
try:
    from watch_config import dynamic_max_new_symbols_per_session
except ImportError:
    from holdingStocks.watch_config import dynamic_max_new_symbols_per_session


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
    try:
        max_new = dynamic_max_new_symbols_per_session()
    except Exception:
        max_new = 2
    max_total = max_new + 1  # 额外保留 1 笔止损反弹买回配额

    if n['total'] >= max_total:
        return 'MAX_DAILY_BUY_FILLS'
    if is_rebuy and n['rebuy'] >= 1:
        return 'MAX_DAILY_REBUY_FILLS'
    if not is_rebuy and n['new'] >= max_new:
        return 'MAX_DAILY_NEW_BUY_FILLS'
    return None
