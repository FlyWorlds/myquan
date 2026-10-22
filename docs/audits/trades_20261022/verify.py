"""Independent Decimal reconciliation of the saved Oct 22 paper deliveries."""
import json
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

root = Path(__file__).parent
state = json.loads((root/'paper_state.json').read_text(), parse_float=D, parse_int=D)
day = '2026-10-22'
entries = state['ledger']['entries']
today = sorted([e for e in entries if e.get('session') == day and e.get('side') in ('buy', 'sell')],
               key=lambda e: e['time'])
prior = sorted([e for e in entries if e.get('time', '')[:10] < day and e.get('account_cash_after') is not None],
               key=lambda e: e['time'])
cash = prior[-1]['account_cash_after']
print('Prior committed cash:', cash)
seen = set()
trades = {t.get('id'): t for t in state['trades'] if t.get('id')}
for entry in today:
    assert entry['id'] not in seen
    seen.add(entry['id'])
    amount = entry['price']*entry['qty']
    assert amount == entry['amount']
    cash += amount if entry['side'] == 'sell' else -amount
    assert cash == entry['account_cash_after']
    for key in ('code', 'side', 'price', 'qty', 'amount', 'account_cash_after'):
        assert entry[key] == trades[entry['id']][key]
    if entry['side'] == 'sell':
        assert (entry['price']-entry['cost'])*entry['qty'] == entry['pnl']
        assert entry['buy_time'][:10] < day
        assert entry['execution_quote_time'][:10] == day
    else:
        order = state['holdings']['condition_buy_orders']['orders'][entry['code']]
        price = (order['open']*(1+order['entry_pct'])/D('.01')).to_integral_value(rounding=ROUND_CEILING)*D('.01')
        assert price == order['price'] == entry['price'] == entry['observed_price']
        assert order['status'] == 'FILLED' and order['filled_qty'] == entry['qty']
        assert order['signal_time'] == entry['signal_time']
        assert entry['qty'] % 100 == 0
        assert entry['quote_age_ms'] <= 5000 and entry['queue_age_ms'] <= 5000
        assert order['armed_at'] < entry['signal_time'] < entry['decision_time']
    print(entry['time'], entry['code'], entry['side'], amount, 'cash', cash)
assert cash == state['holdings']['account_cash']
assert len({e['code'] for e in today if e['side']=='buy'}) == 2
print('Realized cycle PnL:', sum(e['pnl'] for e in today if e['side']=='sell'))
print('Realized daily PnL:', sum(e['day_pnl'] for e in today if e['side']=='sell'))
floor = lambda x: (x/D('.01')).to_integral_value(rounding=ROUND_FLOOR)*D('.01')
print('JinAn prepared trail:', floor(D('66.95')*D('.975')))
print('TianTong trail:', floor(D('23.68')*D('.975')))
print('TianTong display half-gain:', floor((D('23.68')+D('22.99'))/2))
print('PASS: accounting and stored order/quote metadata; historical raw quote paths not retained here.')
