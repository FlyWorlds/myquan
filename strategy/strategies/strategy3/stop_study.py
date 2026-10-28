"""前低A/前高B/破位低点C关系、买后新低止损与组合因子30/31/32绑定研究。"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from itertools import product
import hashlib
import json
import numpy as np
import pandas as pd
from .reversal import ROOT, Policy
from .factor_mining import OUT as FEATURES
from .research import simulate
from .combo_config import compose_entry

OUT=ROOT/'backtest/strategy3_abalone/stop_study'
PERIODS=[('训练','2020-01-01','2023-12-31'),('验证','2024-01-01','2024-12-31'),('历史复核','2025-01-01','2026-10-21')]
STOP_DEFS=[('成本4%',dict(stop_mode='cost',stop=.04)),('成本6%',dict(stop_mode='cost',stop=.06)),
           ('成本8%',dict(stop_mode='cost',stop=.08)),('再破C即退',dict(stop_mode='event_low',stop_buffer_atr=0.)),
           ('C下1%',dict(stop_mode='event_low',stop_buffer_atr=0.,stop_buffer_pct=.01)),
           ('C下2%',dict(stop_mode='event_low',stop_buffer_atr=0.,stop_buffer_pct=.02)),
           ('C下0.25ATR',dict(stop_mode='event_low',stop_buffer_atr=.25)),
           ('C下0.5ATR',dict(stop_mode='event_low',stop_buffer_atr=.5)),
           ('C下1ATR',dict(stop_mode='event_low',stop_buffer_atr=1.))]


def detail_stats(trades):
    if trades.empty:return dict(new_low_n=0,new_low_mean_pct=0.,stop_n=0,mean_stop_loss_pct=0.,worst_cycle_pct=0.)
    lows=trades[trades.new_low_after_entry]
    stops=trades[trades.exit_reason.str.contains('止损')]
    return dict(new_low_n=len(lows),new_low_mean_pct=float(lows.return_pct.mean()) if len(lows) else 0.,
                stop_n=len(stops),mean_stop_loss_pct=float(stops.return_pct.mean()) if len(stops) else 0.,
                worst_cycle_pct=float(trades.return_pct.min()))


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=sorted(FEATURES.glob('*_features.parquet'))
    frames={p.name.split('_features')[0]:pd.read_parquet(p) for p in paths}
    if len(frames)!=30:raise ValueError('需要上一轮30只股票的逐日结构特征')
    manifest=[dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
    (OUT/'inputs.json').write_text(json.dumps(manifest,indent=2))
    combos={trigger:compose_entry(frames,dict(support='chan',window=10,trigger=trigger,volume=1.5)) for trigger in ('shadow','recover','either')}
    candidates=[];train=[]
    for trigger,(stop_name,stop_params),stop_trigger,hold,target in product(
            combos,STOP_DEFS,('close','intraday'),(10,20),('cost','structure')):
        p=Policy(initial=1.,reduce=.5,slot=.2,acceleration=False,depth=0.,take=.1,hold=hold,
                 max_entry_risk=.08,risk_budget=.005,stop_trigger=stop_trigger,take_mode=target,**stop_params)
        n=len(candidates);candidates.append((trigger,stop_name,p))
        st,*_=simulate(combos[trigger],p,start='2020-01-01',end='2023-12-31')
        train.append(dict(trial=n,trigger=trigger,stop_name=stop_name,**p.dict(),**st))
    table=pd.DataFrame(train);table['score']=table.total_return_pct+1.5*table.max_drawdown_pct
    table.to_csv(OUT/'train_grid.csv',index=False)
    shortlist=table[(table.n_trades>=20)&(table.take_mode=='structure')].sort_values('score',ascending=False).head(12)
    validation=[]
    for r in shortlist.itertuples():
        trigger,name,p=candidates[r.trial]
        st,*_=simulate(combos[trigger],p,start='2024-01-01',end='2024-12-31')
        validation.append(dict(trial=r.trial,trigger=trigger,stop_name=name,**p.dict(),**st))
    val=pd.DataFrame(validation);val['score']=val.total_return_pct+1.5*val.max_drawdown_pct
    val.to_csv(OUT/'validation.csv',index=False)
    viable=val[val.n_trades>=8]
    if viable.empty:raise ValueError('验证交易少于8笔，不能选组合')
    selected=int(viable.sort_values('score',ascending=False).iloc[0].trial)
    trigger,name,p=candidates[selected]
    config=dict(rule=dict(support='chan',window=10,trigger=trigger,volume=1.5),policy=p.dict(),
                status='research_only',selected_trial=selected,stop_name=name,
                selection_note='固定216组情景；主策略限定A/B结构止盈；2020-2023训练>=20笔筛前12；2024验证>=8笔按收益+1.5回撤选择。2025后曾查看，只作历史复核。',
                auto_trade=False,factors=['factor30','factor31','factor32'])
    # 参数在查看本轮历史复核结果前写定。
    (OUT/'binding_config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
    print('locked binding',json.dumps(config,ensure_ascii=False),flush=True)
    summaries=[]
    for label,start,end in PERIODS+[('名单冻结后','2026-10-01','2026-10-21')]:
        st,eq,orders,tr=simulate(combos[trigger],p,start=start,end=end)
        summaries.append(dict(label=label,**p.dict(),**st,**detail_stats(tr)))
        tag={'训练':'train','验证':'validation','历史复核':'review','名单冻结后':'post_freeze'}[label]
        eq.to_csv(OUT/f'{tag}_equity.csv',index=False);orders.to_csv(OUT/f'{tag}_orders.csv',index=False);tr.to_csv(OUT/f'{tag}_trades.csv',index=False)
    (OUT/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2))
    diagnostics=[]
    for stop_name,stop_params in STOP_DEFS:
        for timing in ('close','intraday'):
            # 同信号、同目标、同期限、同名义风险预算，仅更换失效位与执行时点。
            overrides=dict(stop_mode='cost',stop=.08,stop_buffer_atr=.3,stop_buffer_pct=0.,stop_trigger=timing)
            overrides.update(stop_params);q=replace(p,**overrides)
            for period,start,end in PERIODS[1:]:
                st,_,_,tr=simulate(combos[trigger],q,start=start,end=end)
                diagnostics.append(dict(name=stop_name,period=period,timing=timing,**st,**detail_stats(tr)))
    pd.DataFrame(diagnostics).to_csv(OUT/'stop_diagnostics.csv',index=False)
    # 只作结构关系诊断，不用这些事后收益重选入场。
    from strategy.abalone_risk import entry_plan
    relations=[]
    for s,f in combos[trigger].items():
        idx=f.index[f.stabilize]
        seen=set()
        for i in idx:
            if i+1>=len(f):continue
            r=f.iloc[i];entry=f.iloc[i+1]
            if r.event_id in seen or not .902<entry.open/r.close<1.098:continue
            plan=entry_plan(r,entry.open*1.001,p.dict())
            if not plan['allowed']:continue
            seen.add(r.event_id)
            if i+10>=len(f):continue
            end=f.date.iloc[i+10]
            if not ('2025-01-01'<=str(entry.date.date()) and str(end.date())<='2026-10-21'):continue
            future=f.iloc[i+1:i+11]
            relations.append(dict(symbol=s,event_id=r.event_id,entry_date=str(entry.date.date()),
                location=plan['location'],anchor=plan['anchor'],prior_high=plan['prior_high'],event_low=plan['event_low'],
                stop_px=plan['stop_px'],target_px=plan['target_px'],risk_pct=plan['risk_pct'],reward_risk=plan['reward_risk'],
                breach_wave_ratio=plan['breach_wave_ratio'],rebound_to_a=plan['rebound_to_a'],
                hit_a=bool(future.high.max()>=plan['anchor']),hit_b=bool(future.high.max()>=plan['prior_high']),
                new_low=bool(future.low.min()<plan['event_low']),
                return_10=float(f.close.iloc[i+10]*.999*(1-.000596)/(entry.open*1.001*(1+.000096))-1)))
    pd.DataFrame(relations).to_csv(OUT/'abc_relations.csv',index=False)
    write_report(config,summaries,diagnostics,relations)
    print(json.dumps(dict(config=config,results=summaries,output=str(OUT)),ensure_ascii=False,indent=2),flush=True)
    return dict(config=config,results=summaries,output=str(OUT))


def write_report(config,summaries,diagnostics,relations):
    lines=['# 鲍鱼捞饭：A前低、B前高、C止跌低点与再破新低止损','',
           '## 研究依据与可检验假设',
           '[纽约联储原始订单研究](https://www.newyorkfed.org/research/staff_reports/sr125.html)发现外汇支撑/阻力附近的止损订单可强化突破后的趋势；不能据此认定A股破位必反弹。',
           '[Fidelity ATR说明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)将ATR用于波动与止损距离，不预测方向。本项目沿用此前14日真实波幅简单均值，信号日ATR仅用此前数据，非Wilder平滑。',
           '[SEC订单说明](https://www.investor.gov/introduction-investing/investing-basics/how-stock-markets-work/types-orders)提示触发价与成交价不是同一概念。本研究对A股另外执行T+1、开盘近跌停顺延及跳空成交。',
           '', '## 三个价位与时间',
           'A=最近向上一笔起点底分型低点；B=该笔终点顶分型高点；B后相邻下行笔破A。C=截至入场信号收盘，本轮破位后的最低点，不是事后最终最低价。',
           '买入时冻结A/B/C。C不会随买后新低下移。价格在A下：A为第一反弹目标，到A减半，再到B清仓；已收复A但低于B：第一目标为B，到B减半，其余按3%收盘峰值回落或期限退出。',
           '若开盘已高于B，不再做这一轮抢反弹。成本目标版本另作对照：成本盈利10%减半，余仓3%回落/到期。',
           '', '## 比较与选择',
           '信号为因子30结构过滤 AND 因子31放量止跌；比较下影线、收复前低、两者之一。全部要求破位后最大量比>=1.5、破位后10根日线内。',
           '止损9种：成交价下4/6/8%（成交价含买滑点，不含佣金；全部费税计入现金及收益）；再破C即退；C下1/2%；C下0.25/0.5/1ATR。比较收盘触发与过夜持仓预置触价两种时点；持有10/20日；固定成本目标与A/B结构目标。共216组。',
           '主策略固定用A/B结构目标（成本目标仅为对照）；2020-2023训练，至少20笔筛前12；2024验证至少8笔，按收益+1.5×带负号最大回撤选择。2025以后已在前轮研究中查看，只称历史复核。当前30只冻结池回看历史有选股偏差。',
           '单票资金上限20%，最多5只；风险预算=每笔净值0.5%，按止损距离缩放股数；入场止损距离>8%跳过；不在买后新低时补仓。所有阈值均为研究选择，不保证未来有效。',
           '', '## 成交规则',
           '入场：日收盘信号，次开复核空间及风险后100股整手买；双边0.1%滑点及项目统一费税，未分段历史税率。',
           '收盘止损：收盘≤冻结止损线，次开卖。触价止损：持仓过夜后，开盘跌穿按开盘，盘中触线按止损价加卖出滑点；当天买入不可卖，买日触线最早次开退出。',
           '若开盘接近跌停，卖单保守顺延，哪怕当日后来打开也不假定能在开盘成交；无法保证损失不超过名义风险预算。',
           '结构止盈仍是日收盘达到目标后次开执行，不假设碰到当日最高价就成交。先发生的开盘退出优先于当日稍后盘中止损。',
           '', '## 绑定配置','```json',json.dumps(config,ensure_ascii=False,indent=2),'```',
           '', '## 选定组合的逐日净值回测',
           '|区间|收益%|最大回撤%|闭环笔数|胜率%|买后新低笔数|新低组平均每笔%|',
           '|---|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        lines.append(f'|{r["label"]}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["n_trades"]}|{r["win_rate"]*100:.1f}|{r["new_low_n"]}|{r["new_low_mean_pct"]:.2f}|')
    lines+=['','## 同信号、同退出目标下的止损对照',
            '|止损|触发|区间|收益%|回撤%|笔数|止损笔数|止损组平均每笔%|最差单笔%|',
            '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for r in diagnostics:
        lines.append(f'|{r["name"]}|{r["timing"]}|{r["period"]}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["n_trades"]}|{r["stop_n"]}|{r["mean_stop_loss_pct"]:.2f}|{r["worst_cycle_pct"]:.2f}|')
    if relations:
        d=pd.DataFrame(relations)
        lines+=['','## A/B/C关系诊断（独立事件，不是组合收益）',
                '|入场位置|成熟事件数|未来10日触A%|触B%|再低于C%|平均10日净收益%|',
                '|---|---:|---:|---:|---:|---:|']
        for name,g in d.groupby('location'):
            lines.append(f'|{name}|{len(g)}|{g.hit_a.mean()*100:.1f}|{g.hit_b.mean()*100:.1f}|{g.new_low.mean()*100:.1f}|{g.return_10.mean()*100:.2f}|')
        lines+=['触A/触B只是后续最高价是否到达，不能当作策略止盈成交率。新低组按入场当日至平仓前实际可观察的低点标记；若开盘退出，不用当天稍后低点补标。']
    lines+=['','## 证据边界',
            '同一池重复挖掘，不能把复核结果称为新的独立样本。绑定表示规则已接入研究/观察，不表示自动交易或已证明有效。',
            '复现：`.venv/bin/python -m strategy.strategies.strategy3.stop_study`。输入哈希见inputs.json；逐笔、日线净值及全部训练/验证/止损对照保存在本目录。']
    (OUT/'REPORT.md').write_text('\n'.join(lines))


if __name__=='__main__':run()
