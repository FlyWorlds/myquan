"""Fixed-grid factor34 tuning with train-only selection and locked holdout."""
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]))
from strategy.costs import ENGINE_COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE_VALUE

PLAN=json.loads((ROOT/'PLAN.json').read_text())
POOLS=json.loads((ROOT/'pools.json').read_text())
BUY=(1+SLIPPAGE_VALUE)*(1+ENGINE_COMMISSION_RATE)
SELL=(1-SLIPPAGE_VALUE)*(1-ENGINE_COMMISSION_RATE-STAMP_TAX_RATE)

def read(code):
    raw=json.loads((ROOT/'raw'/f'{code}.json').read_text())
    d=pd.DataFrame([r[:6] for r in raw],columns=['date','open','close','high','low','volume'])
    for c in ['open','close','high','low','volume']:d[c]=d[c].astype(float)
    assert d.date.is_unique and d.date.is_monotonic_increasing
    assert np.isfinite(d.iloc[:,1:]).all().all() and (d.iloc[:,1:]>0).all().all()
    return d

INDEX=read('000300_index')
CAL=INDEX.date.to_numpy()
DATE_INDEX={date:i for i,date in enumerate(CAL)}
FRAMES={code:read(code) for code in {w['code'] for v in POOLS.values() for w in v}}
DATA={}
FEATURES={}
for code,d in FRAMES.items():
    aligned=d.set_index('date').reindex(CAL)
    close=aligned.close.to_numpy()
    prev=aligned.close.ffill().shift().to_numpy()
    op=aligned.open.to_numpy()
    marked=aligned.close.ffill().to_numpy()
    locked=(np.isclose(op,close,atol=.00001)&np.isclose(aligned.high.to_numpy(),close,atol=.00001)
            &np.isclose(aligned.low.to_numpy(),close,atol=.00001)&(close<prev*.96))
    DATA[code]=dict(open=op,close=close,mark=marked,locked=locked,
                    blocked=(op/prev-1>=.097),indices=np.array([DATE_INDEX[x] for x in d.date]))
    v=d.volume.to_numpy();body=d.close.to_numpy()/d.open.to_numpy()-1
    low=(d.volume<=d.volume.rolling(60).min()).to_numpy()
    FEATURES[code]=(v,body,low)

SIGNALS={}
def signals(age,multiple,body_min):
    key=(age,multiple,body_min)
    if key in SIGNALS:return SIGNALS[key]
    answer={}
    for code,(vol,body,lows) in FEATURES.items():
        anchor=-1;used=False;mask=np.zeros(len(CAL),dtype=bool)
        for i in range(len(vol)):
            if anchor>=0 and not used and 1<=i-anchor<=age and vol[i]/vol[anchor]>=multiple and body[i]>=body_min-1e-12:
                mask[DATA[code]['indices'][i]]=True;used=True
            if lows[i]:anchor=i;used=False
        answer[code]=mask
    SIGNALS[key]=answer
    return answer

BENCH_CACHE={}
def matching_bench(codes,entry,exit):
    key=(tuple(codes),entry,exit)
    if key not in BENCH_CACHE:
        ratios=[]
        for code in codes:
            op=DATA[code]['open'][entry];cl=DATA[code]['mark'][exit]
            if np.isfinite(op) and np.isfinite(cl):ratios.append(cl*SELL/(op*BUY)-1)
        bench=float(np.mean(ratios)) if ratios else 0.
        idx=INDEX.close.iloc[exit]*SELL/(INDEX.open.iloc[entry]*BUY)-1
        BENCH_CACHE[key]=(bench,float(idx))
    return BENCH_CACHE[key]

def simulate(codes,param,start,end,curves=False):
    idx=np.flatnonzero((CAL>=start)&(CAL<=end));a,b=int(idx[0]),int(idx[-1])
    mask=signals(param['max_age'],param['volume_multiple'],param['body_min'])
    holding=param['hold_sessions'];trades=[];open_positions=[];blocked=0;delays=0
    eq=np.zeros(b-a+1);exposure=np.zeros_like(eq)
    for code in codes:
        x=DATA[code];cash=1.;qty=0.;entry=-1;entry_price=0.;due=-1;signal_date=None
        for t in range(a,b+1):
            # Prior-session signal only; no current-day high/low used to decide entry.
            if qty==0 and t>a and mask[code][t-1] and np.isfinite(x['open'][t]):
                if x['blocked'][t]:blocked+=1
                else:
                    entry=t;entry_price=float(x['open'][t]);due=t+holding-1
                    signal_date=str(CAL[t-1]);spend=cash*.95
                    qty=spend/(entry_price*BUY);cash-=spend
            if qty>0 and t>=due:
                if np.isfinite(x['close'][t]) and not x['locked'][t]:
                    price=float(x['close'][t]);cash+=qty*price*SELL
                    ret=price*SELL/(entry_price*BUY)-1
                    bench,index_ret=matching_bench(codes,entry,t)
                    trades.append(dict(code=code,signal_date=signal_date,entry_date=str(CAL[entry]),
                                       exit_date=str(CAL[t]),entry_price=entry_price,exit_price=price,
                                       net=ret,pool_benchmark=bench,index_benchmark=index_ret,
                                       excess_pool=ret-bench,excess_index=ret-index_ret,
                                       delayed_sessions=t-due))
                    qty=0.
                else:delays+=1
            value=qty*x['mark'][t] if qty else 0.
            assert cash>=-1e-10 and math.isfinite(cash+value)
            eq[t-a]+=cash+value
            exposure[t-a]+=value/(cash+value) if cash+value else 0
        if qty:
            open_positions.append(dict(code=code,entry_date=str(CAL[entry]),planned_exit_index=due,
                                       unrealized_mark_return=float(x['mark'][b]/entry_price-1)))
    eq/=len(codes);exposure/=len(codes)
    out=dict(trades=trades,open_positions=open_positions,blocked_entries=blocked,delayed_quote_days=delays)
    if curves:out.update(dates=CAL[a:b+1].tolist(),equity=eq.tolist(),exposure=exposure.tolist())
    return out

def summarize(run):
    rows=run['trades']
    if not rows:return dict(n=0,signal_dates=0,mean=None,median=None,win=None,excess_pool=None,excess_index=None,cluster_score=None)
    d=pd.DataFrame(rows);cluster=d.groupby('signal_date').excess_pool.mean()
    sd=float(cluster.std(ddof=1))
    score=float(cluster.mean()/sd*math.sqrt(len(cluster))) if len(cluster)>1 and sd>0 else None
    return dict(n=len(d),signal_dates=len(cluster),mean=float(d.net.mean()),median=float(d.net.median()),
                win=float((d.net>0).mean()),excess_pool=float(d.excess_pool.mean()),excess_index=float(d.excess_index.mean()),
                cluster_score=score,open_count=len(run['open_positions']),blocked=run['blocked_entries'])

def drawdown(eq):
    v=np.r_[1.,eq];return float(np.min(v/np.maximum.accumulate(v)-1))

def capital_benchmark(codes,dates):
    a=DATE_INDEX[dates[0]];b=DATE_INDEX[dates[-1]];curves=[]
    for code in codes:
        x=DATA[code];op=x['open'][a]
        if not np.isfinite(op) or x['blocked'][a]:curves.append(np.ones(b-a+1));continue
        vals=.05+.95/(op*BUY)*x['mark'][a:b+1]
        # End-point liquidation friction; assumes close executable, disclosed separately.
        vals[-1]=.05+.95/(op*BUY)*x['mark'][b]*SELL
        curves.append(vals)
    pool=np.mean(curves,axis=0)
    index=.05+.95/(INDEX.open.iloc[a]*BUY)*INDEX.close.iloc[a:b+1].to_numpy()
    index[-1]=.05+.95/(INDEX.open.iloc[a]*BUY)*INDEX.close.iloc[b]*SELL
    return pool,index

def portfolio_summary(run,codes):
    pool,index=capital_benchmark(codes,run['dates'])
    eq=np.array(run['equity']);ret=float(eq[-1]-1)
    return dict(return_total=ret,max_drawdown=drawdown(eq),mean_exposure=float(np.mean(run['exposure'])),
                pool_return=float(pool[-1]-1),index_return=float(index[-1]-1),
                excess_pool=ret-float(pool[-1]-1),excess_index=ret-float(index[-1]-1),
                pool_drawdown=drawdown(pool),index_drawdown=drawdown(index),open_positions=run['open_positions'])

grid=[dict(max_age=a,volume_multiple=m,body_min=b,hold_sessions=h)
      for a,m,b,h in itertools.product([5,10,15],[1.5,2.,3.],[.03,.05,.07],[2,5,10,20])]
assert len(grid)==108
default=dict(max_age=10,volume_multiple=2.,body_min=.05,hold_sessions=5)
results={};grid_out={}
for pool_id,items in POOLS.items():
    codes=sorted(w['code'] for w in items)
    train=[]
    for i,param in enumerate(grid):
        summary=summarize(simulate(codes,param,*PLAN['train']))
        train.append(dict(params=param,train=summary))
        if (i+1)%27==0:print(pool_id,'train',i+1,flush=True)
    eligible=[r for r in train if r['train']['n']>=20 and r['train']['signal_dates']>=12 and r['train']['cluster_score'] is not None]
    eligible.sort(key=lambda r:(-r['train']['cluster_score'],json.dumps(r['params'],sort_keys=True)))
    chosen=eligible[0]['params'] if eligible else default
    grid_out[pool_id]=train
    result=dict(pool_count=len(codes),eligible_count=len(eligible),selected=chosen,
                top5_train=eligible[:5],selection_reason='train_only' if eligible else 'no_eligible_use_default',models={})
    for label,param in [('default',default),('selected',chosen)]:
        periods={}
        for period in ['train','validation','holdout']:
            run=simulate(codes,param,*PLAN[period],curves=True)
            periods[period]=dict(trade_stats=summarize(run),portfolio=portfolio_summary(run,codes))
            (ROOT/f'{pool_id}_{label}_{period}.json').write_text(json.dumps(run,ensure_ascii=False,indent=2,allow_nan=False))
        result['models'][label]=periods
    results[pool_id]=result
    print(pool_id,'chosen',chosen,'holdout',result['models']['selected']['holdout'],flush=True)

(ROOT/'grid_train.json').write_text(json.dumps(grid_out,ensure_ascii=False,indent=2,allow_nan=False))
(ROOT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False))
fmt=lambda v:'—' if v is None else f'{v*100:+.2f}%'
lines=['# 因子34：策略1/16当前池回测及调参','',
       '本轮回测因子34，不是重放策略1/16原有因子26完整买卖。冻结当前股票池（包括公共自选）存在历史选股偏差。',
       '区间：2025训练；2026-01至06验证；2026-07至11-02历史留出。此前已查看部分2026数据，留出并非全新盲测。',
       '预先固定108组：地量后5/10/15日，1.5/2/3倍量，实体3/5/7%，持有2/5/10/20日。60日地量定义保持不变。',
       '仅训练期选参：至少20笔及12个信号日期，以同日期归并后的同池匹配窗口超额t形式分数排序；该分数不代表显著性，持仓窗仍有相关性且进行了多重比较。',
       '次日开盘买，H包含买入日，H≥2；每股固定等额资金子账户，95%投入，不重复持仓，不跨段携仓。现金无利息，前复权研究份额，不做整手/最低佣金。',
       '费用来自strategy.costs：佣金杂费双边各0.0096%、卖出印花0.05%、双边各0.1%滑点。开盘涨幅≥9.7%禁买。',
       '停牌/无报价或全日同价下跌超过4%的疑似封死日延迟卖出；未验证历史ST状态或真实封单。普通收盘卖出仍是假定可成交。',
       '单笔超额：同入场日开盘至实际退出日收盘，对比同池可报价股票等权及沪深300价格指数，双方同费率。',
       '组合超额：含空仓现金，对比段初95%投入的同池等额买入持有/沪深300；池内期初缺报价或近涨停股票保留现金。期末持仓按收盘盯市，不强制虚构卖出。',
       '指数使用价格指数（非全收益）；个股前复权价格代理分红。资金曲线和逐笔记录保存在同目录JSON。', '']
for pool_id,r in results.items():
    lines += [f"## {pool_id}（{r['pool_count']}只）",'',f"训练选参：{r['selected']}；合格参数{r['eligible_count']}/108。默认参数10日/2倍/5%/持有5日。",'',
              '|版本|阶段|完成交易|均笔净收益|同窗池超额|同窗指数超额|盈利率|组合收益|池买入持有|沪深300|组合对池超额|最大回撤|平均收盘仓位|',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for label,periods in r['models'].items():
        for period,v in periods.items():
            s,p=v['trade_stats'],v['portfolio']
            lines.append(f"|{label}|{period}|{s['n']}|{fmt(s['mean'])}|{fmt(s['excess_pool'])}|{fmt(s['excess_index'])}|{fmt(s['win'])}|{fmt(p['return_total'])}|{fmt(p['pool_return'])}|{fmt(p['index_return'])}|{fmt(p['excess_pool'])}|{fmt(p['max_drawdown'])}|{fmt(p['mean_exposure'])}|")
lines+=['','不能因为训练期最优就部署。优先检查验证/留出同池超额是否同向、是否优于默认、组合收益是否克服空仓拖累。当前池回看偏差未消除，真正验证需历史逐日池或今后冻结前瞻跟踪。',
        '复现：项目Python执行本目录run.py，使用冻结raw输入及PLAN.json；不读写交易账户或策略生产配置。']
(ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n')
