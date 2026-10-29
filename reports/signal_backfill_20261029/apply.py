import copy,json,uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from database_holdings import request_state
from runtime_documents import read_document
from account_reconciliation import effective_deliveries
from trade_ledger import build_ledger_entry
from paper_costs import trade_costs,buy_cash_price
from watch_config import capital_buy_qty
root=Path(__file__).parent
s=request_state();h=s['holdings'];before=copy.deepcopy(s)
aid='signal-restate-20261029-601519';bid='signal-backfill-20261029-002104'
assert not any(t.get('id') in (aid,bid) for t in s['trades']), 'Already applied'
_,alerts=read_document('wechat_alert_state');a=alerts['first_alerts']
(root/'before.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
(root/'signal_evidence.json').write_text(json.dumps({k:v for k,v in a.items() if '2026-10-29' in k and v.get('signal')=='buy_hit'},ensure_ascii=False,indent=2))
now=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
old=next(t for t in s['trades'] if t.get('id')=='cd1ded131b1e4dbeaed97260f2ee487d')
assert old['price']==8.88 and old['qty']==6300
assert h['positions']['601519']['qty']==6300 and not h['positions'].get('002104',{}).get('qty')
assert not any(t.get('code')=='601519' and t.get('side')=='sell' and t.get('time','')>old['time'] for t in s['trades'])
sig=a['signal|2026-10-29|601519|buy_hit'];hsig=a['signal|2026-10-29|002104|buy_hit']
assert (sig['signal_at'],sig['price'])==('2026-10-29 09:52:57',8.93)
assert (hsig['signal_at'],hsig['price'])==('2026-10-29 09:59:57',9.55)
base=Decimal(str(h['account_cash']))+Decimal(str(old['net_amount']))
qty,reason=capital_buy_qty(price=buy_cash_price(sig['price']),equity=float(base),cash=float(base),weight=.2)
assert qty==old['qty'] and not reason
fee=trade_costs('601519','buy',sig['price'],qty)
new=dict(old,**fee);new.update(time=sig['signal_at'],signal_time=sig['signal_at'],signal_received_at=sig['first_at'],price=sig['price'],cost=sig['price'],avg_cost=sig['price'],amount=round(sig['price']*qty,2),account_cash_after=float(base-Decimal(str(fee['net_amount']))),reason='用户授权：按首次买入信号时间及现价重算',note='历史信号修正·因子26开盘突破',reason_detail='历史首次触买预警现价8.93；保留原成交并追加修正',decision_time=now,fill_model='user_authorized_historical_signal',quote_source='database_wechat_alert_state',execution_quote_time=sig['source_quote_at'],observed_price=sig['price'],signal_factor='factor26')
for k in ['quote_db_revision','quote_db_at','quote_age_ms','queue_age_ms','execution_received_at','order_id','order_armed_at','order_price']:
 new.pop(k,None)
replacement=build_ledger_entry(new,holdings=h)
delta=Decimal(str(old['net_amount']))-Decimal(str(fee['net_amount']))
adjust=dict(id=aid,side='adjust',adjustment_kind='buy_signal_restate',adjusts_entry_id=old['id'],code='601519',name='大智慧',qty=qty,time=now,session='2026-10-29',cash_delta=float(delta),replacement_delivery=replacement,reason='用户授权按首次触买信号时间及价格重算')
s['trades'].append(adjust);h['account_cash']=float(Decimal(str(h['account_cash']))+delta)
p=h['positions']['601519'];p.update(cost=8.93,today_cost=8.93,buy_time=sig['signal_at'],buy_fees_remaining=fee['total_fees'],note='首次触买信号修正·8.93元·09:52:57')
# No complete mark at 09:59:57 survives. Check the quantity is stable across the
# recorded same-session observed range rather than inventing an exact equity mark.
for mark in [8.76,8.93,9.03]:
 eq=h['account_cash']+6300*mark
 q,r=capital_buy_qty(price=buy_cash_price(9.55),equity=eq,cash=h['account_cash'],weight=.2)
 assert q==5900 and not r,(mark,q,r)
fee2=trade_costs('002104','buy',9.55,5900)
h['account_cash']=round(h['account_cash']-fee2['net_amount'],2)
buy=dict(id=bid,side='buy',code='002104',name='恒宝股份',market='深证',qty=5900,after_qty=5900,price=9.55,cost=9.55,avg_cost=9.55,amount=56345,time=hsig['signal_at'],session='2026-10-29',account_cash_after=h['account_cash'],reason='用户授权：按历史触买顺序递补',note='历史信号递补·因子33·首次触买现价9.55',reason_detail='排除金安及东材今日买入后，恒宝为第二只；首次预警目标9.54、观察现价9.55，按用户要求使用触发时现价',signal_time=hsig['signal_at'],signal_received_at=hsig['first_at'],decision_time=now,fill_model='user_authorized_historical_signal',quote_source='database_wechat_alert_state',execution_quote_time=hsig['source_quote_at'],observed_price=9.55,order_price=9.54,signal_factor='factor33',historical_backfill=True,**fee2)
s['trades'].append(buy);s['ledger']['entries'].append(build_ledger_entry(buy,holdings=h))
h['positions']['002104']=dict(name='恒宝股份',market='深证',qty=5900,available=0,cost=9.55,today_cost=9.55,buy_time=hsig['signal_at'],tp_stage=0,last_tp_ts=None,peak_high=9.55,peak_high_at=hsig['source_quote_at'],buy_fees_remaining=fee2['total_fees'],note='用户授权历史信号递补；持仓峰值从已知信号价开始观测')
orders=h.get('condition_buy_orders',{}).get('orders',{})
if '601208' in orders:orders['601208'].update(status='BLOCKED',reason='USER_EXCLUDED_TODAY_GAIN_TOO_LARGE')
if '002104' in orders:orders['002104'].update(status='FILLED',reason='USER_AUTHORIZED_HISTORICAL_SIGNAL',filled_qty=5900,signal_time=hsig['signal_at'],historical_backfill=True,backfilled_at=now)
h['updated_at']=now
entries,issues=effective_deliveries(s);assert not issues,issues
active=[e for e in entries if e.get('side')=='buy' and e.get('session')=='2026-10-29'];assert {e['code'] for e in active}=={'601519','002104'}
assert abs(h['account_cash']-173060.99)<.001
payload=dict(expectedRevision=s['revision'],requestId='signal-backfill-20261029-v1',holdings=h,trades=s['trades'],ledger=s['ledger'])
(root/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
r=request_state('PUT',payload);(root/'after.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
assert not effective_deliveries(r)[1]
assert before['ledger']['entries']==r['ledger']['entries'][:len(before['ledger']['entries'])]
assert before['trades']==r['trades'][:len(before['trades'])]
print(json.dumps(dict(revision=r['revision'],cash=r['holdings']['account_cash'],positions=[(c,p['qty'],p['cost'],p['buy_time']) for c,p in r['holdings']['positions'].items() if p.get('qty',0)>0]),ensure_ascii=False))
