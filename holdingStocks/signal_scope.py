"""Separate the active strategy's signals from retained real inventory and history.

生命周期状态机原则（完整交易闭环 ＋ 信号当日留存 ＋ 次日重置清理）：
1. 闭环原则：
   在策略换池时，凡是「已有持仓（qty > 0）」或「已触发买入信号但尚未完成卖出动作」的股票，
   必须保留在监听队列中（常驻行情拉取），直到其触发卖出闭环。
2. 延迟清理原则（关键）：
   当股票触发「卖出信号」或执行平仓时，当日严禁从系统中清理，必须在前端界面持续展示该卖出信号状态，
   以便用户盘中核对。
3. 次日重置清理：
   真正的清理销毁动作，必须放在触发卖出信号的下一个交易日的早盘重置时间（如 9:00）执行。
"""
from __future__ import annotations
from typing import Any
from strategy.board_rules import code_key


def unclosed_lifecycle_codes(holdings: dict[str, Any], session: str) -> set[str]:
    """获取所有尚未完成卖出闭环的股票代码。

    未闭环条件：
    1. 实际持仓 qty > 0；或者
    2. 已触发买入信号（orders 状态为 TRIGGERED 或 FILLED，或者 alert_sticky 有触买记录），
       且在 realized_today / closed_today 中尚未产生该交易日的全仓平仓记录。
    """
    closed_codes = set()
    for key in ('realized_today', 'closed_today'):
        for code, record in (holdings.get(key) or {}).items():
            if isinstance(record, dict) and record.get('full_exit', True):
                closed_codes.add(code_key(code))

    unclosed = set()
    # 1. 实际持仓必定未闭环
    for code, pos in (holdings.get('positions') or {}).items():
        if isinstance(pos, dict) and int(pos.get('qty') or 0) > 0:
            unclosed.add(code_key(code))

    # 2. 已触发买入但未产生平仓记录的股票
    orders = (holdings.get('condition_buy_orders') or {}).get('orders') or {}
    for code, order in orders.items():
        c = code_key(code)
        if order.get('status') in ('TRIGGERED', 'FILLED'):
            if c not in closed_codes:
                unclosed.add(c)

    return unclosed


def retained_inventory_codes(holdings: dict[str, Any], session: str) -> set[str]:
    """保留在行情拉取与卖出监听队列中的代码集合。

    1. 闭环原则：所有未闭环的股票（已有持仓 或 已触发买入尚未卖出），必须常驻拉行情并监听卖出。
    2. 延迟清理原则：当日触发卖出/平仓的股票（realized_today session == session），当日必须留存供核对。
    """
    codes = set(unclosed_lifecycle_codes(holdings, session))
    for key in ('realized_today', 'closed_today'):
        for code, record in (holdings.get(key) or {}).items():
            if isinstance(record, dict) and str(record.get('session') or record.get('time') or '')[:10] == session:
                codes.add(code_key(code))
    return codes


def align_signal_scope(holdings: dict[str, Any], *, strategy_id: str, strategy_codes: set[str], session: str) -> bool:
    """策略换池或范围对齐。

    闭环原则：
    凡是「已有持仓」或「已触发买入信号但尚未完成卖出动作」的股票，必须保留在监听队列中。
    延迟清理原则：
    当日已平仓/已卖出的股票，当日必须保留供用户核对。
    """
    allowed = {code_key(c) for c in strategy_codes}
    retained = retained_inventory_codes(holdings, session)
    pool = sorted(allowed | retained)
    changed = holdings.get('portfolio_pool') != pool
    holdings['portfolio_pool'] = pool
    if holdings.get('signal_strategy_id') != strategy_id:
        holdings['signal_strategy_id'] = strategy_id
        holdings['alert_sticky'] = {}
        changed = True

    orders = (holdings.get('condition_buy_orders') or {}).get('orders')
    if isinstance(orders, dict):
        unclosed = unclosed_lifecycle_codes(holdings, session)
        for code, order in orders.items():
            c = code_key(code)
            # 只有既不在新目标池、又未触发买入（即纯未触发状态）的股票，才取消其挂单
            if c not in allowed and c not in unclosed:
                if order.get('status') in ('ARMED',):
                    order.update(status='CANCELLED', reason='STRATEGY_SCOPE_CHANGED')
                    changed = True
    return changed


def purge_closed_signals_at_next_session(
    holdings: dict[str, Any], *, active_strategy_codes: set[str], session: str
) -> bool:
    """次日早盘 9:00 重置清理状态机。

    执行时机：触发卖出信号的下一个交易日的早盘 9:00 重置时间。
    清理逻辑：
    1. 闭环原则：
       只要股票尚未完成卖出动作（实仓 qty > 0，或已触买尚未卖出），绝不清理，继续保留在监听队列中。
    2. 延迟清理原则：
       当日触发卖出的股票当日全天留存；只有在进入下一个交易日（即昨天已完成卖出平仓），
       且该股票不在新目标池中时，在次日 9:00 正式执行销毁清理。
    3. 未成交且不在新目标池的过期纯虚信号，在次日 9:00 执行清理。
    """
    allowed = {code_key(c) for c in active_strategy_codes}
    unclosed = unclosed_lifecycle_codes(holdings, session)
    changed = False

    # 1. 清洗 condition_buy_orders
    book = holdings.get('condition_buy_orders')
    if isinstance(book, dict):
        book_session = str(book.get('session') or '')
        orders = book.get('orders')
        if isinstance(orders, dict):
            for code in list(orders.keys()):
                c = code_key(code)
                order = orders[code]
                if c not in allowed:
                    # 不在新目标池：
                    if c in unclosed:
                        # 闭环原则：尚未完成卖出动作，绝对不清理！
                        continue
                    else:
                        # 已经在前一交易日（或更早）完成了卖出闭环，或者从未买入成交：
                        # 次日 9:00 执行真正的销毁清除！
                        orders.pop(code, None)
                        changed = True
                else:
                    # 留在新目标池中的候选股票：
                    if c not in unclosed and (book_session != session or order.get('status') in ('TRIGGERED', 'FILLED')):
                        # 昨天未成交的触买标记在次日 9:00 重置，等待今天 9:25 开盘重新审计
                        orders.pop(code, None)
                        changed = True
        if book.get('session') != session:
            book['session'] = session
            changed = True

    # 2. 清洗 alert_sticky
    sticky = holdings.get('alert_sticky')
    if isinstance(sticky, dict):
        for code in list(sticky.keys()):
            c = code_key(code)
            if c not in allowed and c not in unclosed:
                sticky.pop(code, None)
                changed = True

    # 3. 同步清理 LIVE_ALERT_RETENTION
    try:
        from alert_retention import LIVE_ALERT_RETENTION
        LIVE_ALERT_RETENTION.purge_closed_at_next_session(allowed, unclosed)
    except Exception:
        pass

    # 4. 更新 portfolio_pool
    pool = sorted(allowed | retained_inventory_codes(holdings, session))
    if holdings.get('portfolio_pool') != pool:
        holdings['portfolio_pool'] = pool
        changed = True

    return changed


# 兼容别名
purge_stale_unheld_signals = purge_closed_signals_at_next_session
