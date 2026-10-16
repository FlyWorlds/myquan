from pathlib import Path
import sys,json,hashlib,shutil
import pandas as pd
ROOT=Path('/Users/wangxiangyu/Documents/myquan')
sys.path.insert(0,str(ROOT))
from backtest.strategy1_pool_1m import run as engine
from backtest.strategy16_core_leader.run_month_review import add_intraday_daily,reconcile
from holdingStocks.watch_config import DEFAULT_ACCOUNT_TOTAL,MAX_PORTFOLIO_SLOTS,MAX_BUYS_PER_DAY,SLOT_WEIGHT,RESERVE_EMPTY_SLOTS
from strategy.pullback_wave_stop import DEFAULT_PULLBACK_PCT
OUT=ROOT/'backtest/strategy16_core_leader/review_2026-10-01_2026-10-16_intraday_150100'
DAYS=['2026-10-08','2026-10-09','2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16']
if (OUT/'frozen_pool.json').exists():
 pool=json.loads((OUT/'frozen_pool.json').read_text())
else:
 pool=engine._load_pool(engine.POOL_STRATEGY16)
 (OUT/'frozen_pool.json').write_text(json.dumps(pool,ensure_ascii=False,indent=2))
(OUT/'daily').mkdir(exist_ok=True)
special=pd.read_parquet(OUT/'source_checks/sz001282_sina.parquet')
special['ts']=pd.to_datetime(special.ts).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
special=special[(special.ts>=pd.Timestamp('2026-10-01'))&(special.ts<pd.Timestamp('2026-10-17'))]
special.to_parquet(OUT/'minutes/sz001282.parquet',index=False)
stocks=[]; coverage=[]; sources=[];frames={}; warmups=[]
for w in pool:
 minute_path=OUT/'minutes'/f"{w['sina']}.parquet"
 m=pd.read_parquet(minute_path).sort_values('ts')
 assert not m.ts.duplicated().any(),w['code']
 assert not m[['open','high','low','close']].isna().any().any(),w['code']
 assert (m[['open','high','low','close']]>0).all().all(),w['code']
 assert (m.high>=m[['open','close','low']].max(axis=1)-1e-8).all(),w['code']
 assert (m.low<=m[['open','close','high']].min(axis=1)+1e-8).all(),w['code']
 counts=m.groupby(m.ts.dt.strftime('%Y-%m-%d')).size().to_dict()
 assert sorted(counts)==DAYS,(w['code'],counts)
 for day,bars in m.groupby(m.ts.dt.strftime('%Y-%m-%d')):
  assert bars.ts.min().strftime('%H:%M')<='09:35',(w['code'],day)
  assert bars.ts.max().strftime('%H:%M')=='15:00',(w['code'],day)
 dp=OUT/'daily'/f"{w['sina']}.parquet"
 if not dp.exists():shutil.copyfile(ROOT/'data_cache'/f"{w['sina']}_daily_qfq.parquet",dp)
 d=pd.read_parquet(dp); dates=pd.to_datetime(d.date)
 if dates.dt.tz is not None:dates=dates.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
 d['date']=dates;d=d[d.date<pd.Timestamp('2026-10-17')].copy()
 warmups.append(len(d[d.date<pd.Timestamp(DAYS[0])]))
 for day,bars in m.groupby(m.ts.dt.strftime('%Y-%m-%d')):
  dr=d[d.date.dt.strftime('%Y-%m-%d')==day]
  if not dr.empty:
   assert abs(float(dr.iloc[-1].close)-float(bars.iloc[-1].close))<=max(.02,float(dr.iloc[-1].close)*.002),(w['code'],day,'price scale conflict')
 d=add_intraday_daily(d,m,DAYS[-1])
 stocks.append(dict(code=w['code'],name=w['name'],entry_pct=float(w['entry_pct']),pullback_pct=float(DEFAULT_PULLBACK_PCT),daily=d,minutes=m))
 frames[w['code']]=m
 for day,n in counts.items():coverage.append(dict(code=w['code'],name=w['name'],date=day,bars=int(n)))
 for file in [minute_path,dp]:sources.append(dict(path=str(file.relative_to(ROOT)),sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
# Compare actual sparse timestamps against the source's normal session labels;
# closing auction is aggregated, so 238 records do not mean two missing auction bars.
gaps=[]
for day in DAYS:
 ref=frames['600330'];labels=set(ref.loc[ref.ts.dt.strftime('%Y-%m-%d')==day,'ts'])
 for w in pool:
  m=frames[w['code']];actual=set(m.loc[m.ts.dt.strftime('%Y-%m-%d')==day,'ts'])
  for ts in sorted(labels-actual):gaps.append(dict(code=w['code'],name=w['name'],date=day,missing_source_label=str(ts)))
port=engine.simulate_portfolio_3slots(stocks,days=1000,max_slots=MAX_PORTFOLIO_SLOTS,initial_cash=DEFAULT_ACCOUNT_TOTAL,slot_weight=SLOT_WEIGHT,max_buys_per_day=MAX_BUYS_PER_DAY,reserve_empty=RESERVE_EMPTY_SLOTS,buy_mode=engine.BUY_MODE_DEFAULT)
cycles,accounting=reconcile(port)
assert port['summary']['calendar']==DAYS
prev=float(DEFAULT_ACCOUNT_TOTAL);daily=[]
for e in port['equity']:
 equity=float(e['equity']);daily.append(dict(date=e['date'],day_pnl=round(equity-prev,2),day_return_pct=(equity/prev-1)*100,equity=equity,cumulative_return_pct=(equity/DEFAULT_ACCOUNT_TOTAL-1)*100,cash=e['cash'],positions=e['n_pos'],codes=e['codes']))
 prev=equity
assert abs(sum(e['day_pnl'] for e in daily)-accounting['net_profit'])<.02
compound=1.
for e in daily:compound*=1+e['day_return_pct']/100
assert abs(compound-port['summary']['final_equity']/DEFAULT_ACCOUNT_TOTAL)<1e-9
caveats=['研究参考：原严格入口因三联锻造10月15日仅229根分钟记录而终止；本结果保留全部34只，未补造分钟。','7个交易日均有数据，但逐分钟覆盖不完整；稀疏记录原因未确认，不能声称完整精确回测。','使用当前冻结股票池、个股阈值；thr_2026拟合截至2026-10-13，与评价窗重叠，非样本外。','不包含因子29竞价买入；缺历史竞价tick与完整报价事件，不能精确复现当前实时策略。','30万元空仓开始，未继承9月持仓，不等于实际账户收益。','沿用现有分钟回测内核、T+1、费用和滑点模型，同分钟竞争按固定池顺序；未证明与报价交易逐笔一致。','10月尚未结束，本次只到10月16日15:00；未计算未来交易日。']
result=dict(requested_start='2026-10-01',requested_end='2026-10-16',sessions=DAYS,status='research_only_sparse_minutes_strict_acceptance_failed',pool_size=len(pool),minute_rows=sum(len(s['minutes']) for s in stocks),missing_source_labels=len(gaps),minimum_daily_warmup_rows=min(warmups),summary=port['summary'],accounting=accounting,daily_returns=daily,caveats=caveats,open_positions=port['open_positions'],sources=sources,configuration=dict(initial_cash=DEFAULT_ACCOUNT_TOTAL,max_slots=MAX_PORTFOLIO_SLOTS,max_buys_per_day=MAX_BUYS_PER_DAY,slot_weight=SLOT_WEIGHT,threshold_fit_end='2026-10-13'))
for name,rows in [('daily_returns',daily),('research_trades',port['trades']),('research_cycles',cycles),('research_coverage',coverage),('missing_minute_labels',gaps),('research_skipped_buys',port['skipped_buys'])]:pd.DataFrame(rows).to_csv(OUT/f'{name}.csv',index=False,encoding='utf-8-sig')
(OUT/'research_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
lines=['# 策略16：2026年10月至16日研究参考回测','', '**状态：严格数据完整性验收未通过，以下仅为稀疏分钟数据研究参考。**','',f"当前池34只；初始资金{DEFAULT_ACCOUNT_TOTAL:,.0f}元；最多{MAX_PORTFOLIO_SLOTS}只，每天最多新开{MAX_BUYS_PER_DAY}只，单只目标{SLOT_WEIGHT:.0%}。",'', '| 日期 | 当日盈亏（元） | 当日收益率 | 日末权益（元） | 累计收益率 |','|---|---:|---:|---:|---:|']
for e in daily:lines.append(f"| {e['date']} | {e['day_pnl']:+,.2f} | {e['day_return_pct']:+.4f}% | {e['equity']:,.2f} | {e['cumulative_return_pct']:+.4f}% |")
lines+=['',f"累计净盈亏 {accounting['net_profit']:+,.2f} 元；费用和滑点 {accounting['fees_and_slippage']:,.2f} 元。",f"日末最大回撤 {port['summary']['max_dd_pct']:.2f}%；买入{port['summary']['n_buys']}笔，卖出{port['summary']['n_sells']}笔，期末仍持有{port['summary']['n_open']}只。",'', '## 限制','']+['- '+s for s in caveats]+['',f"数据检查：{len(coverage)}个股票交易日；{result['minute_rows']}根；相对正常源标签缺{len(gaps)}条，详见missing_minute_labels.csv。",'资金、持仓、周期盈亏及每日收益复利已核对。输入文件SHA256见research_result.json。','']
(OUT/'RESEARCH_REPORT.md').write_text('\n'.join(lines))
print(json.dumps({k:result[k] for k in ['status','pool_size','minute_rows','missing_source_labels','minimum_daily_warmup_rows','summary','accounting','daily_returns']},ensure_ascii=False,indent=2))
