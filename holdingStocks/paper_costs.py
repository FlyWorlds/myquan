"""Paper cash settlement using the exact strategy.costs backtest convention.

Trigger prices stay unmodified. Slippage is a separate cash cost, with fees
charged on the slipped notional, just like strategy1_pool_1m/run.py.
"""
from decimal import Decimal, ROUND_HALF_UP
from strategy import costs

MODEL = "strategy.costs.v1"
FIELDS = ("fee_model", "commission", "misc_fee", "stamp_tax", "slippage_cost",
          "total_fees", "net_amount", "cash_delta", "gross_pnl", "allocated_buy_fees", "fee_rates")


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def buy_cash_price(price):
    return float(price)*(1+costs.SLIPPAGE_VALUE)*(1+costs.ENGINE_COMMISSION_RATE)


def trade_costs(code, side, price, qty):
    if side not in ('buy', 'sell') or int(qty) <= 0 or float(price) <= 0:
        raise ValueError('Invalid fee settlement')
    gross = Decimal(str(price))*int(qty)
    slip = gross*Decimal(str(costs.SLIPPAGE_VALUE))
    slipped = gross+slip if side == 'buy' else gross-slip
    commission = slipped*Decimal(str(costs.COMMISSION_RATE))
    misc = slipped*Decimal(str(costs.MISC_FEE_RATE))
    stamp = slipped*Decimal(str(costs.stamp_tax_for_code(code))) if side == 'sell' else Decimal(0)
    # Match the backtest formula, rounding the final cash amount only once.
    net = money(slipped+commission+misc if side == 'buy' else slipped-commission-misc-stamp)
    total = money(abs(Decimal(str(net))-gross))
    return dict(fee_model=MODEL, commission=money(commission), misc_fee=money(misc),
        stamp_tax=money(stamp), slippage_cost=money(slip), total_fees=total,
        net_amount=net, cash_delta=-net if side == 'buy' else net,
        fee_rates=dict(commission=costs.COMMISSION_RATE, misc=costs.MISC_FEE_RATE,
            stamp_tax=costs.stamp_tax_for_code(code) if side == 'sell' else 0,
            slippage=costs.SLIPPAGE_VALUE))


def settle_trade(record, holdings):
    """Apply to a newly created gross fill inside its existing DB transaction.

    Historical entries are never passed through this function. Existing positions
    without fee fields have zero historical entry fees; never invent a backfill.
    """
    side = record.get('side')
    if side not in ('buy', 'sell') or record.get('fee_model'):
        return
    fee = trade_costs(record['code'], side, record['price'], record['qty'])
    pos = holdings['positions'][record['code']]
    qty = int(record['qty'])
    after = int(record.get('after_qty') or 0)
    remaining = money(pos.get('buy_fees_remaining') or 0)
    if side == 'buy':
        pos['buy_fees_remaining'] = money(remaining+fee['total_fees'])
    else:
        allocated = remaining if after == 0 else money(remaining*qty/(after+qty))
        pos['buy_fees_remaining'] = money(remaining-allocated)
        fee['allocated_buy_fees'] = allocated
        gross_pnl = record.get('pnl')
        if gross_pnl is not None:
            fee['gross_pnl'] = gross_pnl
            record['pnl'] = money(float(gross_pnl)-fee['total_fees']-allocated)
            basis = float(record.get('cost') or 0)*qty+allocated
            record['pnl_pct'] = round(record['pnl']/basis*100, 2) if basis else None
        if record.get('day_pnl') is not None:
            same_day = str(record.get('buy_time') or '')[:10] == str(record.get('session') or '')[:10]
            record['day_pnl'] = money(float(record['day_pnl'])-fee['total_fees']-(allocated if same_day else 0))
    cash = holdings.get('account_cash')
    if cash is not None:
        # Existing fill paths already applied gross amount to cash.
        holdings['account_cash'] = money(float(cash)-fee['total_fees'])
        if side == 'buy' and holdings['account_cash'] < 0:
            raise ValueError('INSUFFICIENT_CASH_WITH_FEES')
        record['account_cash_after'] = holdings['account_cash']
    record.update(fee)
    rec = (holdings.get('realized_today') or {}).get(record['code'])
    if side == 'sell' and rec:
        rec.update({k: record[k] for k in (*FIELDS, 'pnl', 'pnl_pct', 'day_pnl') if k in record})
        base = rec.get('day_base')
        rec['day_pnl_pct'] = round(rec['day_pnl']/base*100, 2) if base and rec.get('day_pnl') is not None else None
        record['day_pnl_pct'] = rec['day_pnl_pct']
