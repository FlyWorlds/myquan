from pathlib import Path
import copy,json,sys,uuid
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'holdingStocks'))
from database_holdings import request_state
from quote_feed import fetch_sina_batch
from trade_ledger import build_ledger_entry
from paper_costs import settle_trade,trade_costs
OUT=Path(__file__).resolve().parent
pairs=[('002636','601208','金安国纪','东材科技'),('600552','002454','凯盛科技','松芝股份')]
def symbol(c):return ('sh' if c.startswith('6') else 'sz')+c
quotes=fetch_sina_batch([symbol(c) for p in pairs for c in p[:2]])
now=datetime.now(ZoneInfo('Asia/Shanghai'));ts=now.strftime('%Y-%m-%d %H:%M:%S');day=ts[:10]
for p in pairs:
 for c in p[:2]:
  q=quotes[symbol(c)]
  assert q['session']==day and q['last']>0 and q.get('source_time_verified'),(c,q)
  age=(now.replace(tzinfo=None)-datetime.fromisoformat(q['last_ts'])).total_seconds()
  assert 0<=age<90,(c,age)
state=request_state(); before=copy.deepcopy(state);h=state['holdings'];records=[];summary=[]
assert h.get('account_execution_mode')=='manual_actual'
for old,new,oname,nname in pairs:
 op=h['positions'][old];assert op['qty']>0 and op['name']==oname
 assert not h['positions'].get(new,{}).get('qty',0)
 oq=quotes[symbol(old)];nq=quotes[symbol(new)];sell_qty=op['qty'];sell_px=oq['last'];buy_px=nq['last'];cost=op['cost'];buy_time=op['buy_time']
 proceeds=trade_costs(old,'sell',sell_px,sell_qty)['net_amount']
 buy_qty=int(proceeds/buy_px/100)*100
 while buy_qty and trade_costs(new,'buy',buy_px,buy_qty)['net_amount']>proceeds:buy_qty-=100
 assert buy_qty>0
 for code,name,side,px,qty,q in [(old,oname,'sell',sell_px,sell_qty,oq),(new,nname,'buy',buy_px,buy_qty,nq)]:
  pos=h['positions'].setdefault(code,{})
  market='上证' if code.startswith('6') else '深证'
  rec=dict(id='manual-swap-'+uuid.uuid4().hex,time=ts,session=day,side=side,code=code,name=name,market=market,price=px,qty=qty,after_qty=0 if side=='sell' else qty,cost=cost if side=='sell' else px,amount=round(px*qty,2),reason='用户确认手工换仓',note='用户指定按现价清仓并分别换入，100股向下取整；本地持仓记账',fill_model='user_directed_manual_record',quote_source='sina',execution_quote_time=q['last_ts'],execution_received_at=ts,observed_price=px,decision_time=ts)
  if side=='sell':
   base=cost if str(buy_time)[:10]==day else q['prev_close']
   rec.update(buy_time=buy_time,pnl=round((px-cost)*qty,2),pnl_pct=round((px/cost-1)*100,2),day_pnl=round((px-base)*qty,2),day_pnl_pct=round((px/base-1)*100,2))
   h['account_cash']=round(h['account_cash']+px*qty,2)
   pos.update(qty=0,available=0,cost=None,today_cost=None,buy_time=None,tp_stage=0,last_tp_ts=None,stop_noted=False,stop_noted_px=None,stop_noted_session=None,note=f'用户手工换仓清仓@{px} ({day})')
   h.setdefault('realized_today',{})[code]={**rec,'full_exit':True,'day_base':round(base*qty,2),'filled_at':ts,'triggered_at':ts,'decision_at':ts,'exit_kind':'manual'}
  else:
   # Start a new holding cycle; historical peaks/stop state must not carry over.
   pos.clear();pos.update(name=name,market=market,qty=qty,available=0,cost=px,today_cost=px,buy_time=ts,peak_high=px,peak_high_at=ts,tp_stage=0,last_tp_ts=None,stop_noted=False,stop_noted_px=None,stop_noted_session=None,buy_fees_remaining=0,note='用户手工换仓，成本按现价记录')
   h['account_cash']=round(h['account_cash']-px*qty,2)
   h.setdefault('realized_today',{}).pop(code,None)
   h.setdefault('closed_today',{}).pop(code,None)
   pool=h.setdefault('portfolio_pool',[])
   if code not in pool:pool.append(code)
  settle_trade(rec,h);rec['account_cash_after']=h['account_cash'];records.append(rec)
  state['trades'].append(rec);state['ledger']['entries'].append(build_ledger_entry(rec,holdings=h))
 confirmation=h.setdefault('actual_holdings_confirmation',{})
 confirmation.setdefault('positions',{}).pop(old,None)
 confirmation['positions'][new]=dict(qty=buy_qty,cost=buy_px,cost_confirmed_at=ts,source='user_manual_swap')
 confirmation.update(confirmed_at=ts,source='user_confirmation')
 summary.append(dict(sold=dict(code=old,name=oname,qty=sell_qty,price=sell_px),bought=dict(code=new,name=nname,qty=buy_qty,price=buy_px)))
h['updated_at']=ts;state['ledger']['updated_at']=ts
h.setdefault('manual_swaps',[]).append(dict(time=ts,pairs=summary,trade_ids=[r['id'] for r in records]))
assert len(state['trades'])==len(before['trades'])+4
assert len(state['ledger']['entries'])==len(before['ledger']['entries'])+4
assert h['account_cash']>=0
assert round(before['holdings']['account_cash']+sum(r['cash_delta'] for r in records),2)==h['account_cash']
for name,data in [('before.json',before),('quotes.json',quotes),('planned.json',state)]:
 (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2))
result=request_state('PUT',dict(expectedRevision=before['revision'],requestId='manual-swap-'+uuid.uuid4().hex,holdings=h,trades=state['trades'],ledger=state['ledger']))
(OUT/'committed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
assert result['revision']==before['revision']+1
print(json.dumps(dict(revision=result['revision'],pairs=summary,cash_before=before['holdings']['account_cash'],cash_after=result['holdings']['account_cash'],fees=sum(r['total_fees'] for r in records)),ensure_ascii=False))
