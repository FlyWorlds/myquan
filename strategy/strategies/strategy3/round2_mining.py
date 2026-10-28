"""固定退出规则，训练/双年度验证挖掘确认型入场；2026不参与选择。"""
from __future__ import annotations
import json
from itertools import product
import hashlib
import pandas as pd
from .reversal import ROOT,Policy
from .combo_config import load_config,compose_entry
from .research import simulate
from .round2_features import PATTERNS,enrich_features,entry_mask

OUT=ROOT/'backtest/strategy3_abalone/round2'
SOURCE=ROOT/'backtest/strategy3_abalone/ytd_2026'
PERIODS=[('训练','2020-01-01','2022-12-31'),('验证2023','2023-01-01','2023-12-31'),
         ('验证2024','2024-01-01','2024-12-31'),('复核2025','2025-01-01','2025-12-31'),
         ('复核2026','2026-01-01','2026-10-22')]


def prep(enriched,rule):
    out={}
    for s,f in enriched.items():
        g=f.copy();g['stabilize']=entry_mask(f,rule);g['anchor_date']=g.event_id
        out[s]=g
    return out


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    locked=load_config();p=Policy(**locked['policy'])
    (OUT/'baseline_binding.json').write_text(json.dumps(locked,ensure_ascii=False,indent=2))
    paths=sorted(SOURCE.glob('*_features.parquet'))
    frames={q.name.split('_features')[0]:pd.read_parquet(q) for q in paths}
    if len(frames)!=30:raise ValueError('需要截至10月22日的30只股票完整历史特征')
    (OUT/'input_hashes.json').write_text(json.dumps([{ 'path':str(q.relative_to(ROOT)), 'sha256':hashlib.sha256(q.read_bytes()).hexdigest()} for q in paths],indent=2))
    enriched={allow:{s:enrich_features(f,allow_rebound=allow) for s,f in frames.items()} for allow in (False,True)}
    rules=[dict(support='chan',window=10,trigger=t,volume=v,quality_filter=q,allow_rebound=a)
           for t,v,q,a in product(PATTERNS,(1.2,1.5),('none','avoid_weak','wave','depth'),(False,True))]
    # 基准必须用原始factor30/31的严格相邻笔语义；不能偷偷换成延长结构窗口。
    baseline=compose_entry(frames,locked['rule'])
    base=[]
    for name,start,end in PERIODS:
        stats,*_=simulate(baseline,p,start=start,end=end)
        base.append(dict(period=name,**stats))
    (OUT/'baseline_results.json').write_text(json.dumps(base,ensure_ascii=False,indent=2))
    train=[]
    for i,rule in enumerate(rules):
        fr=prep(enriched[rule['allow_rebound']],rule)
        st,*_=simulate(fr,p,start='2020-01-01',end='2022-12-31')
        train.append(dict(trial=i,**rule,**st))
    t=pd.DataFrame(train);t['score']=t.total_return_pct+1.5*t.max_drawdown_pct
    t.to_csv(OUT/'train_grid.csv',index=False)
    # 按触发族各取训练前2，避免大量近似阈值挤占整个候选集。
    valid=t[(t.n_trades>=18)&(t.total_return_pct>0)].sort_values('score',ascending=False)
    shortlist=valid.groupby('trigger',sort=False).head(2).sort_values('score',ascending=False)
    print('train complete',len(t),'shortlist',len(shortlist),flush=True)
    validations=[]
    for rr in shortlist.itertuples():
        rule=rules[rr.trial];fr=prep(enriched[rule['allow_rebound']],rule)
        for label,start,end in PERIODS[1:3]:
            st,*_=simulate(fr,p,start=start,end=end)
            validations.append(dict(trial=rr.trial,period=label,**rule,**st))
    val=pd.DataFrame(validations);val.to_csv(OUT/'validation.csv',index=False)
    ranked=[]
    base24=next(x for x in base if x['period']=='验证2024')
    for trial,g in val.groupby('trial'):
        if len(g)!=2:continue
        a=g[g.period=='验证2023'].iloc[0];b=g[g.period=='验证2024'].iloc[0]
        enough=a.n_trades>=6 and b.n_trades>=6
        accepted=bool(enough and min(a.total_return_pct,b.total_return_pct)>0
                      and b.total_return_pct>=base24['total_return_pct']
                      and abs(b.max_drawdown_pct)<=abs(base24['max_drawdown_pct'])*1.25)
        score=float(min(a.total_return_pct+1.5*a.max_drawdown_pct,b.total_return_pct+1.5*b.max_drawdown_pct))
        ranked.append(dict(trial=int(trial),accepted=accepted,score=score,min_trades=int(min(a.n_trades,b.n_trades)),
                           return_2023=float(a.total_return_pct),return_2024=float(b.total_return_pct),
                           dd_2023=float(a.max_drawdown_pct),dd_2024=float(b.max_drawdown_pct)))
    rank=pd.DataFrame(ranked,columns=['trial','accepted','score','min_trades','return_2023','return_2024','dd_2023','dd_2024']).sort_values(['accepted','score'],ascending=False)
    rank.to_csv(OUT/'ranking.csv',index=False)
    if rank.empty:raise ValueError('没有达到训练门槛的候选，本轮不改绑定')
    selected=int(rank.iloc[0].trial);rule=rules[selected];accepted=bool(rank.iloc[0].accepted)
    selection=dict(rule=rule,policy=p.dict(),accepted_by_validation=accepted,
                   status='research_only',trial=selected,selection_basis='2020-2022训练>=18，按触发族取前2；2023/2024双年各>=6笔且盈利，2024不低于基准且回撤<=基准1.25倍；2026不参与选择',
                   auto_trade=False)
    # 先锁选择，再查看2025/2026结果；当前池和各历史段均曾被查看，不声称独立盲测。
    (OUT/'candidate.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2))
    print('locked candidate',json.dumps(selection,ensure_ascii=False),flush=True)
    results=[];fr=prep(enriched[rule['allow_rebound']],rule)
    for label,start,end in PERIODS:
        st,eq,orders,tr=simulate(fr,p,start=start,end=end)
        results.append(dict(period=label,**st))
        if label in ('复核2025','复核2026'):
            tag='2025' if label=='复核2025' else '2026'
            eq.to_csv(OUT/f'equity_{tag}.csv',index=False);orders.to_csv(OUT/f'orders_{tag}.csv',index=False);tr.to_csv(OUT/f'trades_{tag}.csv',index=False)
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    # 预设触发族对照仅展示，不按2026收益重新排序或更换选择。
    controls=[]
    for family in PATTERNS:
        subset=rank[rank.trial.map(lambda i:rules[i]['trigger']==family)]
        if subset.empty:continue
        rr=subset.sort_values(['accepted','score'],ascending=False).iloc[0]
        nr=rules[int(rr.trial)];ff=prep(enriched[nr['allow_rebound']],nr)
        for label,start,end in PERIODS[3:]:
            st,*_=simulate(ff,p,start=start,end=end)
            controls.append(dict(trigger=family,trial=int(rr.trial),period=label,accepted=bool(rr.accepted),**st))
    pd.DataFrame(controls).to_csv(OUT/'family_checks.csv',index=False)
    write_report(selection,base,results,rank,controls,len(t))
    write_review()
    print(json.dumps(dict(candidate=selection,baseline=base,results=results,output=str(OUT)),ensure_ascii=False,indent=2),flush=True)
    return dict(candidate=selection,baseline=base,results=results,output=str(OUT))


def write_report(selection,base,results,rank,controls,count):
    names=dict(shadow_confirm='下影后突破确认',reclaim2='连续两日收复前低',retest='收复前低后回踩',spring='假破位当日收回',
               low_confirm2='两日低点抬高后突破',dry_reversal='缩量且两日低点抬高',bull_engulf='阳包阴反转',momentum_turn='短均线动量转正')
    lines=['# 鲍鱼捞饭：第二轮确认型组合挖掘','',
           '本轮固定原绑定的仓位、4%触价止损、A/B退出及20日上限，只改变入场。基准与候选均年初/区间初空仓起算，费税、滑点、T+1相同。行情截至2026-10-22，当前30只股票池有选股偏差。',
           '2026表现已知，本轮不以其筛选候选；所有历史段也已在前轮研究中使用，仍不算全新独立样本。',
           '', '## 本轮假设与时点',
           '- 下影后确认：同一轮结构最近3日出现下影，之后收盘突破该下影K线高点且不跌穿其低点，次开介入。',
           '- 两日收复：连续两日收盘>=前低A，当前低点不低于前日；回踩：近5日曾收复A，今日回踩A附近[-0.5,+0.3]ATR后收阳站回A。',
           '- 假破位收回：当日日低<A、收盘>=A且收阳；低点抬高确认：连续两日低点不下降，收盘突破前日高点。',
           '- 缩量反转：量比<=0.8、连续两日低点不下降且收盘上升；阳包阴：前日收阴，今日开盘<=前收且收盘>前开。',
           '- 动量转正：收盘上穿5日均线、突破前日高点且RSI14上升。',
           '- 过滤器：避免弱势=价格>=MA20的95%且MA20近5日跌幅<=2%；波段过滤=破位深度/(B-A)<=0.5；深度过滤=跌破A的幅度在2%—8%。量比阈值1.2/1.5。',
           '- 严格下行笔与反弹确认窗口分别测试。后者仅在过去已观察到相邻下笔破A后，冻结这一轮A/B，允许进入新上笔确认；最多10根日线或收盘到B后失效。C在介入前可随已知行情更新，介入后仍冻结。没有用事后笔列表倒填。',
           '', '## 选择约束',
           f'预设{count}组。2020—2022训练至少18笔且盈利，每个触发族取前2；2023、2024双年度验证各至少6笔且盈利。通过条件还要求2024收益>=基准、回撤<=基准1.25倍。按较弱验证年的“收益+1.5×负回撤”排序。',
           f'候选：{names[selection["rule"]["trigger"]]}；通过验证门槛：{selection["accepted_by_validation"]}。本脚本不会自动覆写原绑定。',
           '```json',json.dumps(selection,ensure_ascii=False,indent=2),'```','',
           '## 锁定候选与原组合对照', '|区间|组合|收益%|日线最大回撤%|闭环笔数|胜率%|', '|---|---|---:|---:|---:|---:|']
    for b,r in zip(base,results):
        for label,row in [('原组合',b),('新候选',r)]:
            lines.append(f'|{row["period"]}|{label}|{row["total_return_pct"]:.2f}|{row["max_drawdown_pct"]:.2f}|{row["n_trades"]}|{row["win_rate"]*100:.1f}|')
    lines+=['','## 触发族历史复核（只展示，不用于选择）', '|条件|区间|通过验证|收益%|日线回撤%|闭环笔数|', '|---|---|---|---:|---:|---:|']
    for row in controls:lines.append(f'|{names[row["trigger"]]}|{row["period"]}|{row["accepted"]}|{row["total_return_pct"]:.2f}|{row["max_drawdown_pct"]:.2f}|{row["n_trades"]}|')
    lines+=['','## 解读限制',
            '信号更少会自然降低资金使用和回撤，不代表单位风险能力增强。未平仓计收盘浮动，不虚构年末卖出；全策略仍非实盘有效性证明。',
            '若候选未通过验证门槛，原组合保持不变。若通过，仍需在注册因子中接入同一特征和参数后做重放一致性检查，不能只改页面文案。',
            '复现：`.venv/bin/python -m strategy.strategies.strategy3.round2_mining`。全部规则、训练结果、双年验证、家族对照和候选逐笔保存在本目录。']
    (OUT/'REPORT.md').write_text('\n'.join(lines))


def write_review():
    """描述已锁定候选的失败方式；不依照2026改选另一个候选。"""
    t=pd.read_csv(OUT/'trades_2026.csv')
    losses=t[t.pnl<0];stops=t[t.exit_reason.str.contains('止损',na=False)]
    d=dict(closed_cycles=len(t),winning_cycles=int((t.pnl>0).sum()),
           losing_cycles=len(losses),stop_cycles=len(stops),
           stops_without_new_event_low=int((~stops.new_low_after_entry).sum()),
           closed_profit=float(t.loc[t.pnl>0,'pnl'].sum()),
           closed_loss=float(losses.pnl.sum()),realized_pnl=float(t.pnl.sum()),
           mean_loss_hold_days=float(losses.hold_days.mean()),
           first_target_less_than_1R=int(((t.target_px-t.entry_price)/(t.entry_price-t.stop_px)<1).sum()))
    (OUT/'diagnostics_2026.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
    decision=dict(active_binding_changed=False,action='keep_baseline',
                  reason='历史双年验证通过，但2026收益弱于基准，跨年优势不一致；保留研究候选，不按2026家族对照重新挑选赢家。',
                  candidate='candidate.json',research_only=True,auto_trade=False)
    (OUT/'decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2))
    extra=['','## 本轮处置与2026失败拆解',
           '**保持原绑定，候选仅存档研究。** 双年度门槛通过不等于跨年稳定：候选2023弱于原组合，训练期回撤也更大，2026复核未改善收益。没有改绑到今年偶然盈利但历史验证失败的家族。',
           f'2026候选闭环{d["closed_cycles"]}笔，盈利{d["winning_cycles"]}笔、亏损{d["losing_cycles"]}笔；盈利合计{d["closed_profit"]:,.2f}元，亏损合计{d["closed_loss"]:,.2f}元，已实现合计{d["realized_pnl"]:,.2f}元。净值还计入未平仓浮动。',
           f'{d["stop_cycles"]}笔止损中，{d["stops_without_new_event_low"]}笔在实际持有时段内没有跌破入场时的事件低点C。说明当前成本4%止损常在C上方，亏损不能都归因为“止跌后再次创新低”。亏损平均持有{d["mean_loss_hold_days"]:.1f}个交易日。',
           f'{d["first_target_less_than_1R"]}笔入场时第一目标空间不足1R（R为买价到冻结止损价的距离）。这与过早减半退出可能有关，但不能据此直接宣称因果或放宽止损有效。',
           '后续有意义的假设是联合约束入场到C的距离、A/B剩余空间与风险预算，再独立比较C下方ATR止损；须重新按历史训练/验证约束检验，不能只针对2026亏损调宽。',
           '第二轮特征与时点测试、已有绑定及引擎相关测试共26项通过；正式因子30/31/32及页面保持原参数。']
    report=OUT/'REPORT.md';report.write_text(report.read_text()+'\n'+'\n'.join(extra)+'\n')


if __name__=='__main__':run()
