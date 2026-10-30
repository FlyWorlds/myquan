import sys,json
from pathlib import Path
import pandas as pd
root=Path('/Users/wangxiangyu/Documents/myquan');sys.path[:0]=[str(root),str(root/'holdingStocks')]
from backtest.strategy1_pool_1m import run as fees
from holdingStocks.quote_feed import fetch_sina_batch
out=root/'backtest/strategy1_week_20261030';r=json.loads((out/'strategy1_result.json').read_text());start='2026-10-26';end='2026-10-30';base='2026-10-23'
eq=pd.DataFrame(r['equity']); baseline=float(eq[eq.date==base].iloc[0].equity)
tr=r['trades'];active={};rows=[];carry=[]
for t in tr:
 if t['date']>=start: break
 c=t['code']
 if t['side']=='buy':active[c]=dict(t,remaining=t['shares'])
 else:
  active[c]['remaining']-=t['shares']
  if not active[c]['remaining']:del active[c]
for c,t in active.items():
 m=pd.read_parquet(out/'minutes'/('sh' if c.startswith('6') else 'sz' ) .__str__()) if False else pd.read_parquet(out/'minutes'/f'{"sh" if c.startswith("6") else "sz"}{c}.parquet')
 px=float(m[m.ts.dt.strftime('%Y-%m-%d')==base].iloc[-1].close)
 t.update(px=px,shares=t['remaining'],fee=0,original_time=t['ts'],ts=base+' 15:00:00',kind='期初持仓按前收盘重置');carry.append(dict(t))
active={c:dict(t) for c,t in active.items()}
reasons={'open_break':'开盘突破','day_low_rebound':'日内低点反弹','open':'开盘突破','breakout':'开盘突破'}
for t in tr:
 if not start<=t['date']<=end:continue
 c=t['code'];qty=t['shares'];px=t['px'];reason=reasons.get(t.get('kind'),t.get('kind',''))
 if t['side']=='buy':
  active[c]=dict(t,remaining=qty,fee=fees._buy_outlay(px,qty)-px*qty)
  rows.append([t['ts'],c,t['name'],'买入',qty,px,reason,'—'])
 else:
  a=active[c];pnl=fees._sell_credit(px,qty,c)-a['px']*qty-a.get('fee',0)*qty/a['shares'];a['remaining']-=qty
  rows.append([t['ts'],c,t['name'],'卖出',qty,px,{'open_protect':'隔夜开盘保护','vol_giveback':'波动回吐止盈','ladder_half_10':'盈利10%阶梯半仓止盈','peak_pullback_clear':'峰值回撤清仓','t1_peak_trail':'T+1峰值回撤止损'}.get(t.get('exit_reason',''),t.get('exit_reason','')),round(pnl,2)])
  if not a['remaining']:del active[c]
for c,a in active.items():
 mark=next(p['last_px'] for p in r['open_positions'] if p['code']==c);qty=a['remaining'];pnl=(mark-a['px'])*qty-a.get('fee',0)*qty/a['shares']
 rows.append([end+' 15:00:00',c,a['name'],'期末持仓盯市',qty,mark,'尚未卖出',round(pnl,2)])
rows.sort(key=lambda r:r[0]);df=pd.DataFrame(rows,columns=['时间','代码','名称','方向','股数','价格','理由','本期净盈亏']);df.to_csv(out/'本周交割单.csv',index=False,encoding='utf-8-sig')
sh=pd.read_csv(out/'sh000001_daily.csv');q=fetch_sina_batch(['sh000001'])['sh000001'];assert q['session']==end
sh=pd.concat([sh,pd.DataFrame([dict(date=end,close=q['last'])])]).drop_duplicates('date',keep='last');sh=sh.sort_values('date');sh['上证日涨跌幅%']=sh.close.pct_change()*100
sub=eq[(eq.date>=start)&(eq.date<=end)].copy();sub['日盈亏']=sub.equity.diff();sub.loc[sub.index[0],'日盈亏']=sub.iloc[0].equity-baseline;sub['累计盈亏']=sub.equity-baseline;sub=sub.merge(sh[['date','close','上证日涨跌幅%']],on='date');sub['ret_pct']=(sub.equity/baseline-1)*100;sub=sub.rename(columns={'date':'日期','equity':'收盘权益','cash':'现金','n_pos':'持仓数','ret_pct':'本周累计收益%','close':'上证收盘'});sub.to_csv(out/'每日盈亏与上证.csv',index=False,encoding='utf-8-sig')
net=float(sub.iloc[-1]['收盘权益'])-baseline;total=sum(v[-1] for v in rows if isinstance(v[-1],(int,float)));assert abs(net-total)<.1,(net,total)
shbase=float(sh[sh.date==base].iloc[0].close);shret=(q['last']/shbase-1)*100
lines=['# 策略一最近五个交易日回测','',f'区间：{start}—{end}；期初权益 {baseline:,.2f} 元；期末权益 {sub.iloc[-1]['收盘权益']:,.2f} 元。',f'总净盈亏 {net:+,.2f} 元，收益率 {net/baseline*100:+.2f}%；上证同期 {shret:+.2f}%。','', '期初持仓按10月23日收盘价重置成本，不重复扣历史买入费用；本周成交含费用及滑点，未卖出持仓按10月30日收盘价盯市。','', '从10月20日空仓30万元启动预热，10月23日收盘形成期初持仓。当前策略一股票池及阈值向历史回放，分钟收盘观察价成交；最多5槽，每槽20%，每日新增最多2笔、接回最多1笔；T+1。缺少历史竞价路径，不含因子29；含选股与阈值前视偏差，分钟缺口未插值。','', '## 期初持仓','']
for t in carry:lines.append(f'- {t["name"]}（{t["code"]}）：{t["shares"]}股，重置成本{t["px"]:.2f}元；原买入时间{t["original_time"]}。')
lines+=['','## 每日统计','',sub.to_markdown(index=False,floatfmt='.2f'),'','## 交割单','',df.to_markdown(index=False),'','理由代码：open_protect=隔夜开盘保护；t1_peak_trail=持仓峰值回撤；hard_from_cost=成本硬止损；vol_giveback=波动回吐。','',f'现金与持仓净值核对：交割单净盈亏合计{total:,.2f}元，与权益差一致。']
(out/'本周回测报告.md').write_text('\n'.join(lines));print('\n'.join(lines[:5]));print(df.to_string(index=False))
