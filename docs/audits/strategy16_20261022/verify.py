"""Read-only independent reconciliation of the saved API evidence. Python stdlib only."""
import json
from decimal import Decimal as D
from pathlib import Path

root = Path(__file__).parent
books = json.loads((root / 'books.json').read_text(), parse_float=D, parse_int=D)
events = json.loads((root / 'events.json').read_text(), parse_float=D, parse_int=D)
snapshot = json.loads((root / 'snapshot.json').read_text(), parse_float=D, parse_int=D)
issues = []


def check(code, field, actual, expected, tolerance=D('.01')):
    if actual is None or abs(D(actual) - expected) > tolerance:
        issues.append((code, field, str(actual), str(expected)))


for code, book in books.items():
    qty = book['virtual_shares']
    entry = book.get('entry_price') or D(0)
    mark = book['last_mark']
    floating = qty * (mark - entry)
    total = book['virtual_cash'] + qty * mark - book['initial_cash']
    cycle = book.get('single_realized_pnl', 0) + floating
    for field, expected in dict(total_pnl=total, unrealized_pnl=floating,
            realized_pnl=total-floating, cycle_pnl=cycle,
            since_checkpoint_pnl=total-book.get('checkpoint_total_pnl', 0)).items():
        check(code, field, book.get(field), expected)
    check(code, 'cumulative_return_pct', book['cumulative_return_pct'],
          total / book['initial_cash'] * 100, D('.000001'))
    basis = book.get('single_cost_base') or D(0)
    if basis:
        check(code, 'cycle_return_pct', book['cycle_return_pct'], cycle/basis*100, D('.000001'))
    if qty or basis:
        expected = (mark-entry)/entry*100 if qty else cycle/basis*100
        check(code, 'single_return_pct', book['single_return_pct'], expected, D('.000001'))

event_count = 0
for code, fills in events.items():
    previous = None
    for fill in fills:
        event_count += 1
        price, qty = fill['price'], fill['qty']
        sell = fill['side'] == 'SELL'
        expected = (price-fill['cost_price'])*qty if sell else D(0)
        check(code, 'event_realized_pnl', fill['realized_pnl'], expected)
        before = fill['after_qty'] + (qty if sell else -qty)
        if previous:
            check(code, 'event_quantity_chain', before, previous['after_qty'], D(0))
            check(code, 'event_cash_chain', fill['cash_after'],
                  previous['cash_after'] + price*qty*(1 if sell else -1))
        previous = fill
    if previous:
        check(code, 'final_cash', books[code]['virtual_cash'], previous['cash_after'])
        check(code, 'final_qty', books[code]['virtual_shares'], previous['after_qty'], D(0))

rows = snapshot['strategy16']
for row in rows:
    code = row['代码']
    for field, key in [('综合策略收益%', 'cumulative_return_pct'),
                       ('综合单笔收入%', 'cycle_return_pct'), ('单笔收入%', 'single_return_pct')]:
        if row.get(field) != books[code].get(key):
            issues.append((code, 'snapshot_'+field, str(row.get(field)), str(books[code].get(key))))

missing = [c for c, b in books.items() if b.get('trades') and not b['virtual_shares']
           and b.get('cycle_return_pct') is None]
visible_missing = [(r['代码'], r['名称']) for r in rows if r['代码'] in missing]
print(json.dumps(dict(books=len(books), fills=event_count, visible_rows=len(rows),
                     arithmetic_issues=issues, missing_closed_cycle=missing,
                     visible_missing_closed_cycle=visible_missing), ensure_ascii=False, indent=2))
assert not issues, issues
