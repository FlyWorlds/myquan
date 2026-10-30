"""Replay today's existing bought symbols only; retain immutable originals and append audited replacements."""
import copy,json,sys,uuid
from pathlib import Path
from datetime import datetime
import pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'holdingStocks'));sys.path.insert(0,str(ROOT))
from paper_costs import trade_costs,buy_cash_price,money
from watch_config import capital_buy_qty
from strategy.open_break import entry_trigger_price
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from account_reconciliation import effective_deliveries,account_summary
OUT=Path(__file__).parent;DAY='2026-10-30'
base=json.loads((OUT/'before_state.json').read_text());opening=json.loads((OUT/'opening_state.json').read_text())
snap=json.loads(Path('/tmp/myquan-buy-check.json').read_text());rows={r['代码']:r for r in snap['holdings']}
today=[t for t in base['trades'] if not t.get('reset_archived') and str(t.get('session')or t.get('time')or '')[:10]==DAY]
assert len(today)==6 and sum(t['side']=='buy' for t in today)==3
codes={t['code'] for t in today};targets={t['code'] for t in today if t['side']=='buy'}
frames={c:pd.read_parquet(OUT/'minutes'/f"{'sh' if c.startswith('6') else 'sz'}{c}.parquet").set_index('ts',drop=False) for c in codes}
common=min(f.ts.max() for f in frames.values())
for c,f in frames.items():
 assert str(f.ts.min())==DAY+' 09:31:00'
 expected=pd.date_range(DAY+' 09:31:00',common,freq='min');assert set(expected)<=set(f.index)
book=copy.deepcopy(base['holdings']);cash=float(opening['holdings']['account_cash']);positions=copy.deepcopy(opening['holdings']['positions'])
new=[];realized={};evidence=[]
def add(record):
 record.update(id='replay-'+uuid.uuid4().hex,session=DAY,fill_model='historical_minute_replay',replay_source='sina_1m',replay_precision='minute',replay_from=DAY+' 09:30:00')
 record.update(trade_costs(record['code'],record['side'],record['price'],record['qty']))
 new.append(record);return record
# All three overnight holdings satisfy the shared production open-protection rule.
for c,p in sorted(positions.items()):
 qty=int(p.get('qty')or 0)
 if qty<=0:continue
 r=rows[c];px=float(frames[c].iloc[0]['open']);assert px==float(r['开盘'])
 decision=evaluate_overnight_open_protect(dict(cost=p['cost'],qty=qty,buy_time=p['buy_time'],session=DAY,open_px=px,prev_close=r['昨收'],peak_high=p.get('overnight_peak')or p.get('peak_high'),overnight_high_ok=True))
 assert decision.triggered
 fees=trade_costs(c,'sell',px,qty);buyfee=float(p.get('buy_fees_remaining')or 0)
 rec=add(dict(time=DAY+' 09:30:00',side='sell',code=c,name=p['name'],market=p['market'],price=px,qty=qty,after_qty=0,cost=p['cost'],buy_time=p['buy_time'],action_kind='full',reason='止损成交',note='09:30起回放·隔夜开盘保护',exit_kind='open_protect',signal_factor='factor26',signal_time=DAY+' 09:30:00',decision_time=DAY+' 09:30:00',gross_pnl=money((px-p['cost'])*qty),allocated_buy_fees=buyfee,pnl=money((px-p['cost'])*qty-fees['total_fees']-buyfee),day_pnl=money((px-r['昨收'])*qty-fees['total_fees'])))
 rec['pnl_pct']=round(rec['pnl']/(p['cost']*qty+buyfee)*100,2);rec['day_pnl_pct']=round(rec['day_pnl']/(r['昨收']*qty)*100,2)
 cash=money(cash+rec['cash_delta']);rec['account_cash_after']=cash
 old=copy.deepcopy((book.get('realized_today')or {}).get(c,{}));old.update(rec,full_exit=True,allow_stop_rebuy=True,day_base=money(r['昨收']*qty),stop_exit_px=px,first_hit_ts=rec['time'],triggered_at=rec['time'],filled_at=rec['time'],decision_at=rec['time'])
 realized[c]=old;p.update(qty=0,available=0,buy_fees_remaining=0)
 evidence.append(dict(code=c,action='sell',price=px,time=rec['time'],rule='shared overnight open protection'))
anchor=money(float(opening['holdings']['account_cash'])+sum(int(p.get('qty')or 0)*rows[c]['昨收'] for c,p in opening['holdings']['positions'].items() if int(p.get('qty')or 0)>0))
# Re-evaluate the requested three symbols. One breakout entry before 10:00;
# rebound entries at observed completed-minute closes from 10:00, no backfilled threshold.
low={c:float(frames[c].iloc[0]['open']) for c in targets};breakout_used=False;new_count=rebuy_count=0
for ts in pd.date_range(DAY+' 09:31:00',common,freq='min'):
 for c in sorted(targets):
  b=frames[c].loc[ts];low[c]=min(low[c],float(b.low))
  if int(positions.get(c,{}).get('qty')or 0)>0:continue
  assert rows[c]['过门OK'] is True
  entry=.03 if c=='600330' else .025
  is_rebuy=c in realized
  if is_rebuy and rebuy_count>=1 or not is_rebuy and new_count>=2:continue
  if ts.strftime('%H:%M:%S')<'10:00:00':
   if breakout_used:continue
   level=entry_trigger_price(float(b['open']) if ts==frames[c].ts.min() else float(frames[c].iloc[0]['open']),entry_pct=entry,tick=.01)
   if float(b.high)+1e-9<level:continue
   px=max(float(level),float(b['open']));kind='breakout';factor='factor26'
  else:
   level=entry_trigger_price(low[c],entry_pct=entry,tick=.01)
   if float(b.close)+1e-9<level:continue
   px=float(b.close);kind='day_low_rebound';factor='factor33'
  equity=cash
  for held,p in positions.items():
   if int(p.get('qty')or 0)>0:equity+=int(p['qty'])*float(frames[held].loc[ts]['close'])
  qty,reason=capital_buy_qty(price=buy_cash_price(px),equity=equity,cash=cash,weight=.2,allow_negative_cash=False,lot=100)
  assert not reason and qty>=100
  rec=add(dict(time=str(ts),side='buy',code=c,name=rows[c]['名称'],market=rows[c]['市场'],price=px,qty=qty,after_qty=qty,avg_cost=px,cost=px,amount=money(px*qty),reason='买入入槽',note='09:30起回放·'+('开盘突破' if kind=='breakout' else '日内低点反弹·分钟收盘报价'),signal_factor=factor,is_rebuy=is_rebuy,signal_time=str(ts),decision_time=str(ts),order_price=float(level),observed_price=px))
  cash=money(cash+rec['cash_delta']);rec['account_cash_after']=cash
  pos=copy.deepcopy(book['positions'].get(c,{}));pos.update(qty=qty,available=0,cost=px,today_cost=px,buy_time=str(ts),name=rec['name'],market=rec['market'],buy_fees_remaining=rec['total_fees'],peak_high=px,peak_high_at=str(ts),tp_stage=0,last_tp_ts=None,stop_noted=False,stop_noted_px=None,stop_noted_session=None,note=rec['note'])
  for k in ['quote_exit_watermark','quote_cycle_low','quote_exit_session','quote_session_peak','overnight_peak','overnight_peak_session','actual_weight_pct','actual_weight_confirmed_at'] :pos.pop(k,None)
  # Only post-entry completed bars contribute to the holding high.
  later=frames[c][frames[c].ts>ts]
  if len(later):
   highest=float(later.high.max())
   if highest>px:pos.update(peak_high=highest,peak_high_at=str(later[later.high==highest].iloc[0].ts))
  positions[c]=pos
  if kind=='breakout':breakout_used=True
  if is_rebuy:rebuy_count+=1
  else:new_count+=1
  evidence.append(dict(code=c,action='buy',price=px,order_price=float(level),qty=qty,time=str(ts),factor=factor,minute_timestamp='bar end; subminute ordering unavailable'))
assert {r['code'] for r in new if r['side']=='buy'}==targets
assert cash>=0
for t in new:
 if t['side']=='sell':t['amount']=money(t['price']*t['qty'])
# Immutable originals remain in the source ledger; the read model substitutes the replay entries.
state=copy.deepcopy(base)
ids={t['id'] for t in today}
for t in state['trades']:
 if t.get('id') in ids:t['reset_archived']=True
state['trades'].extend(copy.deepcopy(new));state['ledger']['entries'].extend(copy.deepcopy(new))
correction=dict(id='session-replay-20261030-'+uuid.uuid4().hex[:12],side='adjust',adjustment_kind='session_replay',session=DAY,time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),voided_delivery_ids=sorted(ids),replacement_delivery_ids=[t['id'] for t in new],cash_delta=money(cash-float(base['holdings']['account_cash'])),reason='用户授权：今天买入持仓从09:30按策略1回放，并同步今日盈亏',replay_scope='today existing bought symbols and prerequisite overnight exits',evidence_path=str(OUT.resolve()))
state['trades'].append(correction)
book.update(positions=positions,realized_today=realized,closed_today={},account_cash=cash,account_total_open=anchor,account_total_open_session=DAY,last_session=DAY,slot_queue={'session':DAY,'freed_at':[]})
for c in targets:
 rec=next(t for t in new if t['side']=='buy' and t['code']==c)
 order=(book.get('condition_buy_orders',{}).get('orders',{})).get(c)
 if order:order.update(status='FILLED',reason=None,filled_qty=rec['qty'],decision_time=rec['time'],signal_time=rec['time'],price=rec['order_price'],kind='breakout' if rec['signal_factor']=='factor26' else 'day_low_rebound',signal_factor=rec['signal_factor'])
 for key in ['alert_sticky','factor_memory']:
  if isinstance(book.get(key),dict):book[key].pop(c,None)
book['session_replay']={k:correction[k] for k in ['id','session','time','evidence_path','replay_scope']}
state['holdings']=book
actual,issues=effective_deliveries(state)
assert len([e for e in actual if str(e.get('session')or e.get('time',''))[:10]==DAY])==6
assert not any(i['kind']=='invalid_session_replay' for i in issues)
quote_rows=[]
for c,p in positions.items():
 if int(p.get('qty')or 0)>0:quote_rows.append({'代码':c,'持仓':p['qty'],'成本':p['cost'],'现价':float(frames[c].loc[common]['close']),'昨收':rows[c]['昨收']})
summary=account_summary(state,quote_rows,DAY);assert summary['dayPnl'] is not None
state['holdings']['account_total']=summary['accountTotal']
(OUT/'proposed_state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
report=dict(day=DAY,from_time=DAY+' 09:30:00',cutoff=str(common),scope=correction['replay_scope'],source='Sina 1m; timestamps are minute bar endpoints',events=evidence,account=summary,cash_delta=correction['cash_delta'],source_revision=base['revision'],original_trade_ids=sorted(ids),verified=True)
(OUT/'replay_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(dict(events=evidence,account={k:summary[k] for k in ['availableCash','accountOpen','dayPnl','dayPnlPct','settledDayPnl']},cash_delta=correction['cash_delta']),ensure_ascii=False,indent=2))
