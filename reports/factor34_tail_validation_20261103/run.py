"""Fixed-parameter tail validation using only pre-14:55 cumulative observations."""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]))
from strategy.costs import ENGINE_COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE_VALUE

SOURCE=ROOT.parent/'factor34_pool_tuning_20261103'
PLAN=json.loads((ROOT/'PLAN.json').read_text())
POOLS=json.loads((ROOT/'pools.json').read_text())
START,END=PLAN['date_range']
BUY=(1+SLIPPAGE_VALUE)*(1+ENGINE_COMMISSION_RATE)
SELL=(1-SLIPPAGE_VALUE)*(1-ENGINE_COMMISSION_RATE-STAMP_TAX_RATE)
codes={w['code'] for v in POOLS.values() for w in v}|{'000300_index'}
DAILY={};OBS={};QA=[]
for code in sorted(codes):
    q=json.loads((SOURCE/'raw'/f'{code}.json').read_text())
    d=pd.DataFrame([r[:6] for r in q],columns=['date','open','close','high','low','volume'])
    for c in ['open','close','high','low','volume']:d[c]=d[c].astype(float)
    assert d.date.is_monotonic_increasing and d.date.is_unique
    d['low60']=d.volume<=d.volume.rolling(60).min()
    DAILY[code]=d
    raw=json.loads((ROOT/'raw'/f'{code}.json').read_text())
    m=pd.DataFrame(raw['bars']);m['date']=m.day.str[:10];m['clock']=m.day.str[11:19]
    assert not m.day.duplicated().any()
    for c in ['open','high','low','close','volume']:m[c]=m[c].astype(float)
    rd={r[0]:r for r in raw['daily']}
    out={}
    for date,group in m.groupby('date',sort=True):
        if date>END:continue
        g=group[(group.clock>='09:35:00')&(group.clock<='15:00:00')].sort_values('day')
        if len(g)!=48 or '14:55:00' not in g.clock.values or g.iloc[0].clock!='09:35:00' or g.iloc[-1].clock!='15:00:00':
            QA.append(dict(code=code,date=date,reason='incomplete_5m'));continue
        hist=d[d.date==date]
        if hist.empty or date not in rd:
            QA.append(dict(code=code,date=date,reason='missing_daily_crosscheck'));continue
        r=hist.iloc[0];ro,rc=map(float,rd[date][1:3])
        if abs(g.iloc[0].open-ro)>.010001 or abs(g.iloc[-1].close-rc)>.010001:
            QA.append(dict(code=code,date=date,reason='daily_price_mismatch'));continue
        volume_error=abs(g.volume.sum()/100/r.volume-1)
        if code!='000300_index' and volume_error>.02:
            QA.append(dict(code=code,date=date,reason='volume_unit_or_coverage',error=volume_error));continue
        scale=r.open/ro
        signal=g[g.clock=='14:55:00'].iloc[0]
        out[date]=dict(price_raw=float(signal.close),price=float(signal.close*scale),
                       open_raw=ro,entry_raw=float(g.iloc[-1].open),entry=float(g.iloc[-1].open*scale),
                       cumulative_volume=float(g[g.clock<='14:55:00'].volume.sum()/100),
                       body=float(signal.close/ro-1),volume_error=volume_error,
                       day_position=int(hist.index[0]))
    OBS[code]=out

CAL=DAILY['000300_index'].date.tolist();CAL_INDEX={date:i for i,date in enumerate(CAL)}
BYDATE={c:d.set_index('date') for c,d in DAILY.items()}

def exit_after(code,date,horizon):
    due=CAL_INDEX[date]+horizon
    for t in range(due,len(CAL)):
        day=CAL[t]
        if day>END:break
        if day not in BYDATE[code].index:continue
        d=BYDATE[code];r=d.loc[day];i=d.index.get_loc(day)
        prev=float(d.iloc[i-1].close) if i else float(r.close)
        locked=(max(r.open,r.high,r.low,r.close)-min(r.open,r.high,r.low,r.close)<.00001 and r.close/prev-1<-.04)
        if locked:continue
        return day,float(r.close),t-due
    return None

def benchmark(pool,date,exitdate):
    vals=[]
    for c in pool:
        if date not in OBS[c] or exitdate not in BYDATE[c].index:continue
        vals.append(float(BYDATE[c].loc[exitdate,'close'])*SELL/(OBS[c][date]['entry']*BUY)-1)
    index=None
    if date in OBS['000300_index'] and exitdate in BYDATE['000300_index'].index:
        index=float(BYDATE['000300_index'].loc[exitdate,'close'])*SELL/(OBS['000300_index'][date]['entry']*BUY)-1
    return (float(np.mean(vals)) if vals else None),index,len(vals)

def stat(rows,column):
    vals=[r[column] for r in rows if r.get(column) is not None]
    return dict(n=len(vals),mean=float(np.mean(vals)) if vals else None,
                median=float(np.median(vals)) if vals else None,
                win=float(np.mean(np.array(vals)>0)) if vals else None,
                worst=float(min(vals)) if vals else None)

results={}
for pool_id,items in POOLS.items():
    params=PLAN['parameters'][pool_id];max_age=params['max_age'];pool=[w['code'] for w in items]
    names={w['code']:w['name'] for w in items}
    candidates=[];excluded=[];valid=0;expected=0
    for code in pool:
        d=DAILY[code];consumed=set();obs=OBS[code]
        for i,row in d.iterrows():
            date=row.date
            if date>END:break
            in_range=START<=date<=END
            if in_range:expected+=1
            if date not in obs:continue
            if in_range:valid+=1
            history=d.iloc[max(0,i-max_age):i]
            anchors=history[history.low60]
            if anchors.empty:continue
            anchor=anchors.iloc[-1];anchor_date=anchor.date
            if anchor_date in consumed:continue
            o=obs[date]
            if o['cumulative_volume']<anchor.volume*3 or o['body']<.03-1e-12:continue
            # Earlier eligible tails must be observed to establish FIRST trigger.
            intervening=d.iloc[int(anchor.name)+1:i]
            if any(day not in obs for day in intervening.date):
                if in_range:excluded.append(dict(code=code,date=date,reason='anchor_history_unknown'))
                continue
            consumed.add(anchor_date)
            if not in_range:continue
            prev=float(d.iloc[i-1].close)
            if o['price']/prev-1>=.097 or o['entry']/prev-1>=.097:
                excluded.append(dict(code=code,date=date,reason='near_limit_up',body=o['body'],ratio=o['cumulative_volume']/anchor.volume));continue
            event=dict(code=code,name=names[code],date=date,anchor=anchor_date,age=i-int(anchor.name),
                       body=o['body'],volume_multiple=o['cumulative_volume']/float(anchor.volume),
                       entry_raw=o['entry_raw'],entry=o['entry'],signal_price_raw=o['price_raw'],
                       daily_close_confirms=bool(row.volume>=anchor.volume*3 and row.close/row.open-1>=.03-1e-12))
            for h in [1,2,3]:
                exit_info=exit_after(code,date,h)
                event[f'd{h}']=None
                if exit_info:
                    exdate,price,delay=exit_info
                    net=price*SELL/(o['entry']*BUY)-1
                    pb,ib,bn=benchmark(pool,date,exdate)
                    event[f'd{h}']=dict(exit_date=exdate,price=price,net=net,delayed_sessions=delay,
                                       pool_benchmark=pb,index_benchmark=ib,benchmark_members=bn,
                                       excess_pool=net-pb if pb is not None else None,
                                       excess_index=net-ib if ib is not None else None)
            event['next_open_d2']=None
            ni=CAL_INDEX[date]+1
            if ni<len(CAL) and CAL[ni] in BYDATE[code].index and event['d2']:
                n=BYDATE[code].loc[CAL[ni]]
                if n.open/row.close-1<.097:
                    event['next_open_d2']=event['d2']['price']*SELL/(float(n.open)*BUY)-1
            candidates.append(event)
    candidates.sort(key=lambda x:(x['date'],x['code']))
    summaries={};trades_by_h={}
    for h in [1,2,3]:
        free={};trades=[];incomplete=[];overlap=[]
        for e in candidates:
            if e['date']<=free.get(e['code'],''):
                overlap.append(dict(code=e['code'],date=e['date']));continue
            if e[f'd{h}'] is None:
                incomplete.append(dict(code=e['code'],date=e['date']));free[e['code']]=END;continue
            t={**e,**e[f'd{h}']};free[e['code']]=t['exit_date'];trades.append(t)
        paired=[dict(tail=r['net'],next_open=r['next_open_d2'],delta=r['net']-r['next_open_d2'])
                for r in trades if h==2 and r['next_open_d2'] is not None]
        summaries[str(h)]=dict(net=stat(trades,'net'),excess_pool=stat(trades,'excess_pool'),
                               excess_index=stat(trades,'excess_index'),
                               distinct_signal_dates=len({r['date'] for r in trades}),
                               incomplete=incomplete,overlap_skips=overlap,
                               paired_tail=stat(paired,'tail'),paired_next_open=stat(paired,'next_open'),paired_advantage=stat(paired,'delta'))
        trades_by_h[str(h)]=trades
    results[pool_id]=dict(pool_count=len(pool),expected_stock_days=expected,valid_stock_days=valid,
                         excluded_candidates=excluded,candidates=candidates,summaries=summaries,trades=trades_by_h)
output=dict(start=START,end=END,qa_exclusions=QA,pools=results)
(ROOT/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False))
fmt=lambda x:'—' if x is None else f'{x*100:+.2f}%'
lines=['# 因子34尾盘验证：3倍量、3%实体、短持有','',
       f'固定参数，不再次调参。{START}至{END}，利用可取得的5分钟历史扩展到约两个月；当前名单回看，不是前瞻盲测。',
       '策略1地量后5个交易日内，策略16为10日内；60日地量、≥3倍量、≥3%实体。',
       '14:55只用此前累计量与该时点价格。下根5分钟K线（15:00标签）的open为成交代理，不能保证下单延迟后以此成交。',
       '历史价格使用前复权统一收益口径，分钟原始价格按当日开盘比例转换；先用不复权日线交叉检查分钟开收盘。',
       '每个锚点首次观察到满足量价即消耗；近涨停过滤导致未成交也不重复追买。缺少锚点之后的历史尾盘证据，首发状态记未知并排除。',
       'D1/D2/D3表示买入后的第1/2/3个市场交易日收盘，遵守T+1；同股票持仓重叠信号跳过，退出日尾盘新信号不买。',
       '成本沿用strategy.costs。禁止近涨停≥9.7%买入；疑似一字下跌封单或停牌退出顺延。未含最低佣金、盘口容量、历史ST状态及完整资金组合。',
       '同窗基准：信号日尾盘至相同退出日收盘，当前池等权与沪深300；相同费用。只统计有完整退出窗口的样本，缺失不计作零收益。','']
for pool_id,r in results.items():
    lines += [f"## {pool_id}（{r['pool_count']}只）",'',
              f"覆盖{r['valid_stock_days']}/{r['expected_stock_days']}股票日；通过过滤候选{len(r['candidates'])}次；过滤{len(r['excluded_candidates'])}次，原因见JSON。",'',
              '|退出日|完整交易|信号日期数|平均净收益|中位数|盈利率|最差|同窗池超额|同窗指数超额|',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for h,s in r['summaries'].items():
        n=s['net'];lines.append(f"|D{h}|{n['n']}|{s['distinct_signal_dates']}|{fmt(n['mean'])}|{fmt(n['median'])}|{fmt(n['win'])}|{fmt(n['worst'])}|{fmt(s['excess_pool']['mean'])}|{fmt(s['excess_index']['mean'])}|")
    s=r['summaries']['2']
    lines += ['', f"同一事件D2退出配对：{s['paired_advantage']['n']}笔；尾盘买均值{fmt(s['paired_tail']['mean'])}，次日开盘买{fmt(s['paired_next_open']['mean'])}，平均差{fmt(s['paired_advantage']['mean'])}。",'',
              '|信号日|股票|量倍数|14:55实体|D1净收益|D2净收益|D3净收益|', '|---|---|---:|---:|---:|---:|---:|']
    for e in r['candidates']:
        ret=[fmt(e[f'd{h}']['net']) if e[f'd{h}'] else '未完成' for h in [1,2,3]]
        lines.append(f"|{e['date']}|{e['name']} {e['code']}|{e['volume_multiple']:.2f}|{fmt(e['body'])}|{'|'.join(ret)}|")
lines+=['','候选逐笔表可能包含被持仓重叠排除的事件，以各期限trades和汇总为执行样本。不得将样本均值当作组合收益，亦不可仅据本窗口选出最佳持有期。',
        'raw保存输入，PLAN.json保存事前方案，run.py复现分析；不修改生产因子参数或策略绑定。']
(ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:{field:v[field] for field in ['expected_stock_days','valid_stock_days','excluded_candidates','summaries']} for k,v in results.items()},ensure_ascii=False,indent=2))
