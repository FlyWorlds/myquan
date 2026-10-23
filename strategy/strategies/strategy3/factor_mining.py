"""前低破位/抛压衰竭因子研究。逐根CZSC结构，不回填；事件去重后评估。"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from itertools import product
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
from .reversal import ROOT, POOL, normalize, load_daily, Policy
from .research import simulate

OUT = ROOT/'backtest/strategy3_abalone/factor_mining'


@dataclass(frozen=True)
class FactorRule:
    support: str = 'chan'       # 最近结构前低；另测阶段低点过滤
    trigger: str = 'recover'    # 原始破位/小阴/下影/不创新低/收复前低
    volume: float = 0.          # 破位后截至当时最大量比，分母此前20日
    acceleration: bool = False
    depth: float = 0.
    window: int = 10
    shrink_volume: bool = False
    room: float = 0.            # 距前低的潜在空间 / 到事件最低点的风险


def features(daily: pd.DataFrame, symbol: str) -> pd.DataFrame:
    from czsc import CZSC, RawBar, Freq, Direction
    d = normalize(daily)
    if d.empty:
        return d
    o,h,l,c,v = [d[k].to_numpy(float) for k in ('open','high','low','close','volume')]
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.r_[c[0],c[:-1]]), np.abs(l-np.r_[c[0],c[:-1]])))
    atr = pd.Series(tr).rolling(14,min_periods=10).mean().shift(1).to_numpy()
    vol20 = pd.Series(v).rolling(20,min_periods=15).mean().shift(1).to_numpy()
    dateidx = {pd.Timestamp(t):i for i,t in enumerate(d.date)}
    a, active, emitted = None, None, set()
    rows=[]
    for i,r in enumerate(d.itertuples()):
        bar=RawBar(symbol=symbol,id=i,dt=r.date.to_pydatetime(),freq=Freq.D,
                   open=r.open,close=r.close,high=r.high,low=r.low,vol=r.volume,amount=r.close*r.volume)
        if a is None:a=CZSC([bar],max_bi_num=30)
        else:a.update(bar)
        # 当前已知的最新向上一笔，其端点包含底分型和顶分型。
        bis=a.bi_list
        up = next((b for b in reversed(bis[-2:]) if b.direction == Direction.Up),None)
        if up is not None:
            j,k = dateidx.get(pd.Timestamp(up.sdt),-1),dateidx.get(pd.Timestamp(up.edt),-1)
            key=(str(up.sdt),str(up.edt))
            if j>=20 and k>j and key not in emitted:
                # 端点必须是当时最新结构，不将过期前低延续到许多轮波段之后。
                if active is None or k>active['top_i']:
                    emitted.add(key)
                    active=dict(bottom_i=j,top_i=k,anchor=float(up.fx_a.fx),peak=float(up.fx_b.fx),
                                known_i=i,break_i=-1,trough=np.inf,max_volume=0.,max_accel=0.,
                                stage20=float(up.fx_a.fx)<=min(l[max(0,j-20):j+1])+1e-8,
                                stage60=j>=60 and float(up.fx_a.fx)<=min(l[j-60:j+1])+1e-8,
                                stage120=j>=120 and float(up.fx_a.fx)<=min(l[j-120:j+1])+1e-8,
                                event=f'{symbol}:{d.date.iloc[j].date()}:{d.date.iloc[k].date()}')
        body=max(o[i]-c[i],0.)
        span=max(h[i]-l[i],1e-10)
        lower=min(o[i],c[i])-l[i]
        vr=v[i]/vol20[i] if np.isfinite(vol20[i]) and vol20[i]>0 else 0.
        mom3=c[i]/c[i-3]-1 if i>=3 else 0.
        prev3=c[i-3]/c[i-6]-1 if i>=6 else 0.
        accel=max(0.,prev3-mom3) if mom3<-.02 else 0.
        # 小阴：当前阴线实体至少比本轮近3日最大阴线缩短一半；前阴线需>=0.8ATR。
        previous_bodies=np.maximum(o[max(0,i-3):i]-c[max(0,i-3):i],0.)
        maxbody=float(max(previous_bodies,default=0.))
        small_bear=bool(body>0 and body<=maxbody*.5 and maxbody>=.8*atr[i] and c[i]<=c[i-1]) if i else False
        shadow=bool(lower/span>=.45 and (c[i]-l[i])/span>=.6 and lower>=.5*atr[i])
        higher_low=bool(i>0 and l[i]>=l[i-1] and c[i]>c[i-1])
        bullish=bool(higher_low and c[i]>o[i])
        # 底分型只在右侧K线出现后确认（原始三K线版本，用作止跌因子而非CZSC笔端点）。
        bottom3=bool(i>=2 and l[i-1]<l[i-2] and l[i-1]<l[i] and h[i-1]<h[i-2] and h[i-1]<h[i])
        row=dict(event_id='',anchor_date='',anchor=np.nan,peak=np.nan,top_date='',known_date='',
                 broken=False,depth=0.,break_age=-1,trough=np.nan,break_volume=0.,
                 accelerated=False,stage20=False,stage60=False,stage120=False,down_leg=False,
                 recovered=False,room_ratio=0.,event_atr_risk=np.nan)
        if active is not None:
            x=active
            # 相邻下笔正在发展，或刚被确认；不要求下笔完成以免使用未来底分型。
            latest=bis[-1] if bis else None
            same_up=latest is not None and latest.direction==Direction.Up and pd.Timestamp(latest.edt)==d.date.iloc[x['top_i']]
            next_down=latest is not None and latest.direction==Direction.Down and pd.Timestamp(latest.sdt)==d.date.iloc[x['top_i']]
            developing_down=same_up and a.ubi is not None and a.ubi.get('direction')==Direction.Down
            down=bool(developing_down or next_down)
            if i>x['known_i'] and down and l[i]<x['anchor'] and x['break_i']<0:
                x['break_i']=i
            if x['break_i']>=0:
                x['trough']=min(x['trough'],l[i])
                x['max_volume']=max(x['max_volume'],vr)
                x['max_accel']=max(x['max_accel'],accel)
            age=i-x['break_i'] if x['break_i']>=0 else -1
            valid=bool(down and i-x['known_i']<=60 and 0<=age<=20)
            risk=max(c[i]-x['trough']+.3*atr[i],.3*atr[i]) if np.isfinite(x['trough']) else np.nan
            room=max(0.,x['anchor']-c[i])/risk if risk>0 else 0.
            row=dict(event_id=x['event'],anchor_date=str(d.date.iloc[x['bottom_i']].date()),anchor=x['anchor'],
                     peak=x['peak'],top_date=str(d.date.iloc[x['top_i']].date()),known_date=str(d.date.iloc[x['known_i']].date()),
                     broken=valid,depth=max(0.,1-x['trough']/x['anchor']) if age>=0 else 0.,break_age=age,
                     trough=x['trough'] if age>=0 else np.nan,break_volume=x['max_volume'],
                     accelerated=x['max_accel']>0,stage20=x['stage20'],stage60=x['stage60'],stage120=x['stage120'],
                     down_leg=down,recovered=bool(age>=0 and c[i]>=x['anchor'] and l[i-1]<x['anchor']) if i else False,
                     room_ratio=room,event_atr_risk=risk/c[i] if risk>0 else np.nan)
        rows.append(dict(**row,vol_ratio=vr,atr=atr[i],body_atr=body/atr[i] if atr[i]>0 else 0.,
                         lower_shadow=lower/span,mom3=mom3,small_bear=small_bear,shadow=shadow,
                         higher_low=higher_low,bullish=bullish,bottom3=bottom3,
                         dry=bool(v[i]>0 and v[i]<=vol20[i]*.8),stabilize=bullish))
    return pd.concat([d,pd.DataFrame(rows)],axis=1)


def signal(f:pd.DataFrame,rule:FactorRule)->pd.Series:
    ok=f.broken & (f.break_age<=rule.window) & (f.depth>=rule.depth)
    if rule.support!='chan':ok &= f[rule.support]
    if rule.volume:ok &= f.break_volume>=rule.volume
    if rule.acceleration:ok &= f.accelerated
    if rule.shrink_volume:ok &= f.dry
    if rule.room:ok &= f.room_ratio>=rule.room
    triggers={'break':pd.Series(True,index=f.index),'small_bear':f.small_bear,'shadow':f.shadow,
              'higher_low':f.higher_low,'bullish':f.bullish,'bottom3':f.bottom3,'recover':f.recovered,
              'exhaust':f.small_bear|f.shadow,'confirm':(f.small_bear|f.shadow)&f.higher_low}
    return (ok & triggers[rule.trigger]).fillna(False)


def event_observations(f:pd.DataFrame,rule:FactorRule,symbol:str)->pd.DataFrame:
    idx=f.index[signal(f,rule)]
    rows=[]
    seen_events=set()
    for i in idx:
        if f.event_id.iloc[i] in seen_events:continue
        if i+1>=len(f):continue
        entry=f.iloc[i+1]
        prior=f.iloc[i]
        # 与组合相同，开盘近涨/跌停保守跳过；不利用当日高低点决定开盘成交。
        if not .902<entry.open/prior.close<1.098:continue
        seen_events.add(prior.event_id)
        r=dict(symbol=symbol,event_id=prior.event_id,signal_date=str(prior.date.date()),entry_date=str(entry.date.date()),
               anchor=prior.anchor,depth=prior.depth,break_volume=prior.break_volume,
               shadow=prior.lower_shadow,body_atr=prior.body_atr,room_ratio=prior.room_ratio)
        for horizon in (3,5,10,20):
            # 买入日记第1天，至第h天收盘。所有标签与信号列分离。
            j=i+horizon
            if j>=len(f):
                r[f'return_{horizon}']=np.nan; r[f'label_end_{horizon}']='';continue
            future=f.iloc[i+1:j+1]
            r[f'return_{horizon}']=float(f.close.iloc[j]*(1-.001)*(1-.000596)/(entry.open*(1+.001)*(1+.000096))-1)
            r[f'mfe_{horizon}']=float(future.high.max()/entry.open-1)
            r[f'mae_{horizon}']=float(future.low.min()/entry.open-1)
            r[f'label_end_{horizon}']=str(f.date.iloc[j].date())
        rows.append(r)
    return pd.DataFrame(rows)


def stats(obs:pd.DataFrame,start:str,end:str,horizon:int=10)->dict:
    if obs.empty:return dict(n=0,mean_pct=0.,median_pct=0.,win_rate=0.,payoff=0.,mae_pct=0.,tail_pct=0.)
    col=f'return_{horizon}'
    d=obs[(obs.entry_date>=start)&(obs[f'label_end_{horizon}']<=end)&obs[col].notna()]
    r=d[col]
    wins=r[r>0];loss=r[r<=0]
    return dict(n=len(r),mean_pct=float(r.mean()*100) if len(r) else 0.,
                median_pct=float(r.median()*100) if len(r) else 0.,win_rate=float((r>0).mean()) if len(r) else 0.,
                payoff=float(wins.mean()/abs(loss.mean())) if len(wins) and len(loss) and loss.mean()<0 else 0.,
                mae_pct=float(d[f'mae_{horizon}'].mean()*100) if len(d) else 0.,
                tail_pct=float(r.quantile(.1)*100) if len(r) else 0.)


def as_portfolio(frames,rule):
    out={}
    for s,f in frames.items():
        g=f.copy();g['stabilize']=signal(f,rule)
        # 同一底+顶组合才是一轮事件，不能把旧前底无限期延续。
        g['anchor_date']=g.event_id
        out[s]=g
    return out


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    pool=json.loads(POOL.read_text());frames={};coverage=[]
    for p in pool['picks']:
        code=p['code'];s=('sh' if code.startswith('6') else 'sz')+code
        d,meta=load_daily(s);d=d[d.date<=pd.Timestamp('2026-10-21')]
        meta['zero_volume']=int((d.volume<=0).sum());meta['duplicate_dates']=int(d.date.duplicated().sum())
        meta['gap_over20days']=int((d.date.diff().dt.days>20).sum())
        meta['input_hash']=hashlib.sha256(pd.util.hash_pandas_object(d,index=False).values.tobytes()).hexdigest()
        coverage.append(meta)
        frames[s]=features(d,s);frames[s].to_parquet(OUT/f'{s}_features.parquet',index=False)
    (OUT/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))
    print('features ready',len(frames),flush=True)
    rules=[]
    # 单因子/对照固定阈值，不在留出集调阈值。
    for support,trigger in product(('chan','stage20','stage60'),('break','small_bear','shadow','higher_low','bullish','bottom3','recover','exhaust','confirm')):
        rules.append(FactorRule(support=support,trigger=trigger))
    for trigger,volume,accel,depth in product(('small_bear','shadow','higher_low','recover','exhaust'),(1.2,1.5,2.),(False,True),(0.,.02)):
        rules.append(FactorRule(trigger=trigger,volume=volume,acceleration=accel,depth=depth))
    for trigger,shrink,room in product(('small_bear','shadow','exhaust'),(False,True),(1.,2.)):
        rules.append(FactorRule(trigger=trigger,volume=1.5,shrink_volume=shrink,room=room))
    observations={}; summaries=[]
    for n,rule in enumerate(rules):
        obs=pd.concat([event_observations(f,rule,s) for s,f in frames.items()],ignore_index=True)
        observations[n]=obs
        for label,start,end in [('train','2020-01-01','2023-12-31'),('validation','2024-01-01','2024-12-31')]:
            summaries.append(dict(rule=n,period=label,**asdict(rule),**stats(obs,start,end)))
    table=pd.DataFrame(summaries);table.to_csv(OUT/'factor_train_validation.csv',index=False)
    train=table[(table.period=='train')&(table.n>=40)].copy()
    # 不允许原始直接破位当主策略；保留为对照。
    train=train[train.trigger!='break']
    train['score']=train.mean_pct+train.tail_pct*.15
    shortlist=train.sort_values('score',ascending=False).head(12)
    validation=table[(table.period=='validation')&table.rule.isin(shortlist.rule)&(table.n>=12)].copy()
    if validation.empty:raise ValueError('验证事件不足，不能选因子')
    validation['score']=validation.mean_pct+validation.tail_pct*.15
    chosen=int(validation.sort_values('score',ascending=False).iloc[0].rule)
    rule=rules[chosen]
    (OUT/'selected_factor.json').write_text(json.dumps(dict(rule_id=chosen,rule=asdict(rule),
        status='research_only',selection='2020-2023 train>=40 -> top12; 2024 validation>=12',
        warning='2025以后曾在上一轮研究中查看，非全新盲测；当前股票池存在选股偏差'),ensure_ascii=False,indent=2))
    # 先锁定因子，再做留出展示；全体检验列另存，避免用测试收益重新挑选。
    evaluation=[]
    for n,r in enumerate(rules):
        for label,start,end in [('train','2020-01-01','2023-12-31'),('validation','2024-01-01','2024-12-31'),('historical_check','2025-01-01','2026-10-21')]:
            for horizon in (3,5,10,20):
                evaluation.append(dict(rule=n,period=label,horizon=horizon,**asdict(r),**stats(observations[n],start,end,horizon)))
    pd.DataFrame(evaluation).to_csv(OUT/'factor_all_periods.csv',index=False)
    observations[chosen].to_csv(OUT/'selected_events.csv',index=False)
    print('selected factor',chosen,asdict(rule),flush=True)
    # 交易参数也仅在训练/验证选择，全部使用日线收盘触发、次开执行。
    pf=as_portfolio(frames,rule);trials=[]
    policies=[]
    for hold,stop,take,initial,reduce in product((5,10,15),(.04,.06,.08),(.04,.06,.1),(0.5,1.),(.5,1.)):
        p=Policy(hold=hold,stop=stop,take=take,initial=initial,reduce=reduce,depth=0.,acceleration=False)
        st,*_=simulate(pf,p,start='2020-01-01',end='2023-12-31')
        policies.append(p);trials.append(dict(trial=len(policies)-1,**p.dict(),**st))
    scan=pd.DataFrame(trials);scan['score']=scan.total_return_pct+scan.max_drawdown_pct
    scan.to_csv(OUT/'portfolio_train.csv',index=False)
    shortlist=scan[scan.n_trades>=30].sort_values('score',ascending=False).head(8)
    vals=[]
    for rr in shortlist.itertuples():
        p=policies[rr.trial];st,*_=simulate(pf,p,start='2024-01-01',end='2024-12-31')
        vals.append(dict(trial=rr.trial,**st))
    val=pd.DataFrame(vals);val=val[val.n_trades>=8]
    if val.empty:raise ValueError('验证组合交易不足')
    val['score']=val.total_return_pct+val.max_drawdown_pct
    selected=int(val.sort_values('score',ascending=False).iloc[0].trial);p=policies[selected]
    val.to_csv(OUT/'portfolio_validation.csv',index=False)
    (OUT/'selected_policy.json').write_text(json.dumps(dict(factor=asdict(rule),policy=p.dict(),research_only=True),indent=2))
    comparisons=[]
    controls=[('筛选候选',rule),('直接破位',FactorRule(trigger='break')),('放量破位',FactorRule(trigger='break',volume=1.5)),
              ('长阴变短',FactorRule(trigger='small_bear')),('下影线',FactorRule(trigger='shadow')),
              ('低点抬高',FactorRule(trigger='higher_low')),('收复前低',FactorRule(trigger='recover')),
              ('放量后长阴变短',FactorRule(trigger='small_bear',volume=1.5)),
              ('放量后下影线',FactorRule(trigger='shadow',volume=1.5)),
              ('放量后收复前低',FactorRule(trigger='recover',volume=1.5)),
              ('放量+加速+止跌',FactorRule(trigger='exhaust',volume=1.5,acceleration=True))]
    for name,r in controls:
        obs=pd.concat([event_observations(f,r,s) for s,f in frames.items()],ignore_index=True)
        for period,start,end in [('训练','2020-01-01','2023-12-31'),('验证','2024-01-01','2024-12-31'),('历史复核','2025-01-01','2026-10-21')]:
            comparisons.append(dict(name=name,period=period,**stats(obs,start,end)))
    pd.DataFrame(comparisons).to_csv(OUT/'factor_comparisons.csv',index=False)
    portfolios=[]
    for label,fr,pol,start,end in [
        ('训练',pf,p,'2020-01-01','2023-12-31'),('验证',pf,p,'2024-01-01','2024-12-31'),
        ('历史复核',pf,p,'2025-01-01','2026-10-21'),
        ('分批对照',pf,Policy(**{**p.dict(),'initial':.5,'reduce':.5}),'2025-01-01','2026-10-21'),
        ('原始破位对照',as_portfolio(frames,FactorRule(trigger='break')),p,'2025-01-01','2026-10-21'),
        ('名单冻结后',pf,p,'2026-10-01','2026-10-21')]:
        st,eq,ev,tr=simulate(fr,pol,start=start,end=end)
        portfolios.append(dict(label=label,**pol.dict(),**st))
        if label=='历史复核':
            eq.to_csv(OUT/'equity.csv',index=False);ev.to_csv(OUT/'orders.csv',index=False);tr.to_csv(OUT/'trades.csv',index=False)
    (OUT/'portfolio_summary.json').write_text(json.dumps(portfolios,ensure_ascii=False,indent=2))
    # 按标的删一复核，暴露少数股票/事件支配的表现。
    leave=[]
    obs=observations[chosen]
    for s in frames:
        leave.append(dict(excluded=s,**stats(obs[obs.symbol!=s],'2025-01-01','2026-10-21')))
    pd.DataFrame(leave).to_csv(OUT/'leave_one_symbol_out.csv',index=False)
    # 所有预设对照使用同一套训练/验证锁定的交易参数，不在复核期逐个优化。
    control_portfolios=[]
    for name,r in controls[1:]:
        fr=as_portfolio(frames,r)
        for period,start,end in [('验证','2024-01-01','2024-12-31'),('历史复核','2025-01-01','2026-10-21')]:
            st,*_=simulate(fr,p,start=start,end=end)
            control_portfolios.append(dict(name=name,period=period,**st))
    pd.DataFrame(control_portfolios).to_csv(OUT/'control_portfolios.csv',index=False)
    intervals=[]
    for name,r in controls:
        obs=pd.concat([event_observations(f,r,s) for s,f in frames.items()],ignore_index=True)
        intervals.append(dict(name=name,**month_bootstrap(obs)))
    pd.DataFrame(intervals).to_csv(OUT/'monthly_bootstrap.csv',index=False)
    write_report(rule,p,comparisons,portfolios,coverage,evaluation,chosen)
    addendum=['','## 相同交易参数下的对照组合',
              '|条件|区间|收益%|日线最大回撤%|闭环笔数|', '|---|---|---:|---:|---:|']
    for r in control_portfolios:
        addendum.append(f'|{r["name"]}|{r["period"]}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["n_trades"]}|')
    addendum += ['','## 事件均值的不确定性',
                '按信号发生月份整组重抽样1000次，保留同月共振；区间仅反映本池内历史事件，不修复选股偏差或多重检验。',
                '|条件|复核成熟事件数|10日均值95%区间%|', '|---|---:|---:|']
    for r in intervals:
        addendum.append(f'|{r["name"]}|{r["n"]}|{r["low_pct"]:.2f} ～ {r["high_pct"]:.2f}|')
    if portfolios[2]['total_return_pct']<=0:
        addendum += ['', '**训练/验证选出的候选未通过后续历史复核，不提升为有效交易策略。**']
    report_path=OUT/'REPORT.md'
    report_path.write_text(report_path.read_text()+'\n'.join(addendum))
    from .factor_evidence import build_evidence
    build_evidence(frames,p)
    print(json.dumps(dict(factor=asdict(rule),policy=p.dict(),portfolio=portfolios,output=str(OUT)),ensure_ascii=False,indent=2),flush=True)


def month_bootstrap(obs):
    d=obs[(obs.entry_date>='2025-01-01')&(obs.label_end_10<='2026-10-21')&obs.return_10.notna()].copy()
    if d.empty:return dict(n=0,low_pct=0.,high_pct=0.)
    d['month']=d.entry_date.str[:7]
    groups=[g.return_10.to_numpy() for _,g in d.groupby('month')]
    rng=np.random.default_rng(20261022)
    samples=[np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))]).mean()*100 for _ in range(1000)]
    return dict(n=len(d),low_pct=float(np.quantile(samples,.025)),high_pct=float(np.quantile(samples,.975)))


def write_report(rule,policy,comparisons,portfolios,coverage,evaluation,chosen):
    lines=['# 鲍鱼捞饭：前低破位后的抛压衰竭因子研究','',
           '## 前低与信号时点',
           '前低=当时CZSC最新向上一笔的起点底分型低点A；同一笔终点是顶分型B。B之后的相邻下行笔（正在发展或刚确认）跌破A才算破位。',
           '向下一笔不要求走完：若等待其底分型最终确认，就不能将买点倒填到更早的破位日。向上笔端点可能随新行情改变，所有快照按当日状态冻结，不事后重算历史信号。',
           '结构前低与阶段新低分开：chan=最近结构前低；stage20/stage60=底分型同时处于此前20/60日新低。',
           '同一底+顶为一个事件。结构滚动到新的上笔后失效；破位后的入场窗口最多10根日线，避免120日旧前低一直有效。',
           '', '## 因子定义',
           '- 放量：本次破位后至信号时刻的最大日成交量 / 各日之前20日均量，测试1.2/1.5/2倍，分母不含当日。',
           '- 加速：当日近3日收益低于−2%，且比前3日更差；记录破位后是否发生过。',
           '- 长阴变短：当前收阴实体≤此前3日最大阴线实体50%，且前面的大阴线≥0.8个前日ATR14。单独检验，不直接视为止跌事实。',
           '- 下影：下影占全振幅≥45%，收盘位于振幅上方40%，下影长度≥0.5ATR14。',
           '- 低点抬高：日低点≥前日低点，收盘>前收；收阳确认另作更严格版本。',
           '- 底分型止跌：原始三K底分型在右侧K出现后才确认；与CZSC包含处理后的笔端点分开。',
           '- 收复前低：上一日低点在前低之下，本日收盘≥前低；可能是短暂回收，须看后续收益。',
           '- 缩量：当日量≤之前20日均量80%；性价比代理=距前低空间/(当前收盘−破位后低点+0.3ATR)。',
           '上述是量价代理，不能识别卖出者是否止损，更不能直接确认“主力承接”。',
           '', '## 数据与研究边界',
           f'策略16当前30只冻结池，行情截至2026-10-21。覆盖{len(coverage)}只。缓存来源、复权拼接、数据哈希见coverage.json。',
           '只在重叠日OHLC复权比例一致时连接缓存；成交量不做价格比例缩放。每日特征逐根CZSC计算。智光电气2025-09-26至10-17的长间隔在原缓存与新拉取新浪日线中一致；仍无法仅凭日线区分停牌与供应商缺失，相关数据边界保留在coverage.json。',
           '当前名单回看过去存在选股/幸存者偏差。2025以后已在上一轮研究中查看，因此这里只称历史复核，不称全新盲测。',
           '训练2020—2023按10日净期望与下尾损失筛前12（至少40事件）；2024验证选择（至少12事件）。所有阈值预设，仅训练/验证选参数。',
           '事件研究：每个规则对每轮底+顶仅取第一个信号；次日开盘介入，第3/5/10/20个持有日收盘退出；边界未成熟标签剔除，不跨区间。不同规则可覆盖不同事件，均值差不代表因果效应。',
           '事件收益是每笔等权统计，不是组合年化；MAE是期间最低价相对入场价的平均不利幅度，不是组合最大回撤。',
           '组合：项目统一佣金及杂费、卖出印花税，双边0.1%滑点；100股整手、最多5只、单票资金额度20%；日收盘信号次开执行；开盘近涨跌停不买、跌停卖单顺延。',
           '止损按收盘加权成本判断，下一开盘卖，跳空可能超过止损阈值；不计历史税率变动及分红送转独立现金流。日线复权整手股数近似。',
           '', '## 单因子历史复核：持有10日',
           '|条件|事件数|平均净收益%|中位数%|胜率%|盈亏比|平均MAE%|',
           '|---|---:|---:|---:|---:|---:|---:|']
    for r in comparisons:
        if r['period']=='历史复核':
            lines.append(f'|{r["name"]}|{r["n"]}|{r["mean_pct"]:.2f}|{r["median_pct"]:.2f}|{r["win_rate"]*100:.1f}|{r["payoff"]:.2f}|{r["mae_pct"]:.2f}|')
    lines+=['','## 锁定研究因子','```json',json.dumps(asdict(rule),ensure_ascii=False,indent=2),'```',
            '## 持有期比较（所选因子，未加止损止盈）',
            '|区间|持有日|事件数|平均净收益%|胜率%|平均MAE%|','|---|---:|---:|---:|---:|---:|']
    for r in evaluation:
        if r['rule']==chosen:
            lines.append(f'|{r["period"]}|{r["horizon"]}|{r["n"]}|{r["mean_pct"]:.2f}|{r["win_rate"]*100:.1f}|{r["mae_pct"]:.2f}|')
    lines+=['','## 组合回测（日线净值）','|区间|收益%|最大回撤%|夏普|闭环笔数|胜率%|', '|---|---:|---:|---:|---:|---:|']
    for r in portfolios:
        lines.append(f'|{r["label"]}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["sharpe_ratio"]:.2f}|{r["n_trades"]}|{r["win_rate"]*100:.1f}|')
    lines+=['','## 训练/验证锁定的仓位与退出参数','```json',json.dumps(policy.dict(),indent=2),'```',
            'initial为单票额度首仓比例；低于1时，再跌3%且所选止跌因子重新满足，最多补一次余款。reduce为止盈时卖出持股比例；余仓峰值回落3%或到期退出。',
            '', '## 解释限制',
            '单因子频次少、行情共振及多重检验会放大偶然性；不能以历史复核最优重新挑因子。结构性因子并不保证破位反弹，要区分假破位回收与真下跌延续。',
            '结果应与训练/验证的一致性、事件数、MAE、组合回撤一起看；当前冻结池尚无足够长的前瞻样本。',
            '', '复现：`.venv/bin/python -m strategy.strategies.strategy3.factor_mining`。',
            '检验台账：factor_train_validation.csv、factor_all_periods.csv、factor_comparisons.csv、portfolio_train.csv、portfolio_validation.csv、selected_events.csv、orders.csv、equity.csv、leave_one_symbol_out.csv。',
            '', '公开背景参考：[上交所投资者入市手册（股票篇）](https://investor.sse.org.cn/institute/bookshelf/manualseriesbook/P020190322685818724112.pdf)。因子定义和结论以本次本地计算为准。']
    (OUT/'REPORT.md').write_text('\n'.join(lines))


if __name__=='__main__':run()
