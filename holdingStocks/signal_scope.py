"""Separate the active strategy's signals from retained real inventory and history."""
from strategy.board_rules import code_key


def retained_inventory_codes(holdings, session):
    codes = {code_key(code) for code, pos in (holdings.get('positions') or {}).items()
             if isinstance(pos, dict) and int(pos.get('qty') or 0) > 0}
    for key in ('realized_today', 'closed_today'):
        for code, record in (holdings.get(key) or {}).items():
            if isinstance(record, dict) and str(record.get('session') or record.get('time') or '')[:10] == session:
                codes.add(code_key(code))
    return codes


def align_signal_scope(holdings, *, strategy_id, strategy_codes, session):
    """Update candidate metadata only. Never edit inventory, cash, fills or cost bases."""
    allowed = set(strategy_codes)
    pool = sorted(allowed | retained_inventory_codes(holdings, session))
    changed = holdings.get('portfolio_pool') != pool
    holdings['portfolio_pool'] = pool
    if holdings.get('signal_strategy_id') != strategy_id:
        holdings['signal_strategy_id'] = strategy_id
        holdings['alert_sticky'] = {}
        changed = True
    for code, order in ((holdings.get('condition_buy_orders') or {}).get('orders') or {}).items():
        if order.get('status') in ('ARMED', 'TRIGGERED') and (
                order.get('strategy') != strategy_id or code_key(code) not in allowed):
            order.update(status='CANCELLED', reason='STRATEGY_SCOPE_CHANGED')
            changed = True
    return changed
