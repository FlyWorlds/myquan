"""因子研究的性价比约束、持有期诊断和可检查图例。"""
from __future__ import annotations
import json
from dataclasses import replace
import pandas as pd
import numpy as np
from .factor_mining import OUT, FactorRule, as_portfolio, event_observations, stats
from .research import simulate


def build_evidence(frames,policy):
    rules=[('放量后下影线',FactorRule(trigger='shadow',volume=1.5)),
           ('放量后收复前低',FactorRule(trigger='recover',volume=1.5))]
    rows=[];periods=[('训练','2020-01-01','2023-12-31'),('验证','2024-01-01','2024-12-31'),('历史复核','2025-01-01','2026-10-21')]
    horizons=[]
    for name,rule in rules:
        fr=as_portfolio(frames,rule)
        obs=pd.concat([event_observations(f,rule,s) for s,f in frames.items()],ignore_index=True)
        for period,start,end in periods:
            for h in (3,5,10,20):
                horizons.append(dict(name=name,period=period,horizon=h,**stats(obs,start,end,h)))
        obs.to_csv(OUT/f'{rule.trigger}_events.csv',index=False)
        for rr in (0.,1.,1.5,2.):
            # 已收复前低时目标在入场价下，不满足空间约束会被跳过，这正是检验内容。
            p=replace(policy,stop_mode='event_low',take_mode='swing_top' if rule.trigger=='recover' else 'anchor',risk_budget=.005,min_rr=rr,
                      max_entry_risk=.08,initial=1.,reduce=.5)
            for period,start,end in periods:
                st,eq,ev,tr=simulate(fr,p,start=start,end=end)
                rows.append(dict(name=name,period=period,min_rr=rr,**st))
    pd.DataFrame(rows).to_csv(OUT/'structural_risk_portfolios.csv',index=False)
    pd.DataFrame(horizons).to_csv(OUT/'control_horizons.csv',index=False)
    report=['','## 性价比约束的固定情景比较',
            '失效位=信号当日已知本轮破位低点−0.3×前日ATR14；下影线入场第一目标为前低A，已收复A的入场目标改为前顶B；次日实际开盘仍须满足目标空间/失效距离≥门槛。',
            '每笔名义风险预算=组合净值0.5%，单票资金仍不超过20%，入场风险距离超过8%跳过；不补仓。到目标减半，余仓按峰值回落3%、失效或期限退出。',
            '0/1/1.5/2是预设门槛情景，未据历史复核重新优化。止损仍按收盘判断、次开执行，因此实际损失可能超过0.5%风险预算。',
            '|条件|区间|最低空间比|收益%|最大回撤%|闭环笔数|','|---|---|---:|---:|---:|---:|']
    for r in rows:
        if r['period']!='训练':
            report.append(f'|{r["name"]}|{r["period"]}|{r["min_rr"]:.1f}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["n_trades"]}|')
    report+=['','## 放量后下影线：持有期诊断（等权事件，非组合）',
             '|区间|持有日|事件数|平均净收益%|胜率%|平均不利幅度%|','|---|---:|---:|---:|---:|---:|']
    for r in horizons:
        if r['name']=='放量后下影线':
            report.append(f'|{r["period"]}|{r["horizon"]}|{r["n"]}|{r["mean_pct"]:.2f}|{r["win_rate"]*100:.1f}|{r["mae_pct"]:.2f}|')
    report+=['','图例：[两个已发生的结构事件](structure_examples.html)。按放量后下影线的复核事件分别取正/负收益组的中位事件，纯为解释结构，不作为效果证明。',
             '图中底分型A、顶分型B、首次破位和信号日均来自逐日特征；信号后灰色区域是后续已发生行情，不是当时已知信息。']
    path=OUT/'REPORT.md'
    base=path.read_text().split("\n## 性价比约束的固定情景比较")[0]
    path.write_text(base+'\n'.join(report))
    draw_examples(frames,rules[0][1])
    return rows


def draw_examples(frames,rule):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    obs=pd.concat([event_observations(f,rule,s) for s,f in frames.items()],ignore_index=True)
    mature=obs[(obs.entry_date>='2025-01-01')&obs.return_10.notna()&(obs.label_end_10<='2026-10-21')]
    cases=[]
    for positive in (True,False):
        g=mature[mature.return_10.gt(0)==positive].sort_values('return_10')
        if len(g):cases.append(g.iloc[len(g)//2])
    fig=make_subplots(rows=2,cols=len(cases),shared_xaxes=True,row_heights=[.75,.25],
                      vertical_spacing=.08,subplot_titles=[f'{r.symbol} | 10日净收益 {r.return_10*100:.2f}%' for r in cases])
    for col,event in enumerate(cases,1):
        f=frames[event.symbol];r=f[f.date==pd.Timestamp(event.signal_date)].iloc[0]
        a,b=pd.Timestamp(r.anchor_date),pd.Timestamp(r.top_date)
        start=max(0,int(f.index[f.date==a][0])-5)
        finish=min(len(f),int(f.index[f.date==pd.Timestamp(event.signal_date)][0])+22)
        d=f.iloc[start:finish]
        fig.add_trace(go.Candlestick(x=d.date,open=d.open,high=d.high,low=d.low,close=d.close,
                                     increasing_line_color='#df6b65',decreasing_line_color='#28a78f',name='日K'),row=1,col=col)
        fig.add_trace(go.Bar(x=d.date,y=d.volume,name='成交量',marker_color='#7288b7',showlegend=False),row=2,col=col)
        fig.add_hline(y=r.anchor,line_dash='dash',line_color='#d3a455',row=1,col=col)
        first=f[(f.event_id==r.event_id)&(f.break_age==0)]
        points=[(a,r.anchor,'底分型 A'),(b,r.peak,'顶分型 B'),
                (pd.Timestamp(event.signal_date),r.close,'下影信号（收盘）')]
        if len(first):points.append((first.date.iloc[0],first.low.iloc[0],'相邻下行破前低'))
        for x,y,text in points:
            fig.add_trace(go.Scatter(x=[x],y=[y],mode='markers+text',text=[text],textposition='bottom left' if text.startswith('相邻') else 'top right' if text.startswith('下影') else 'top center',
                                     marker_size=8,name=text,showlegend=False),row=1,col=col)
        fig.add_vrect(x0=event.entry_date,x1=str(d.date.iloc[-1].date()),fillcolor='gray',opacity=.12,line_width=0,row=1,col=col)
        fig.update_xaxes(rangeslider_visible=False,row=1,col=col)
    fig.update_layout(title='缠论结构前低 → 破位放量 → 下影线：成功与失败图例（灰区为信号后的未知未来）',
                      template='plotly_dark',height=680,showlegend=False,margin=dict(l=55,r=30,t=95,b=45))
    fig.write_html(OUT/'structure_examples.html',include_plotlyjs=True,full_html=True)


if __name__=='__main__':
    frames={f.name.split('_features')[0]:pd.read_parquet(f) for f in OUT.glob('*_features.parquet')}
    from .reversal import Policy
    p=Policy(**json.loads((OUT/'selected_policy.json').read_text())['policy'])
    print(pd.DataFrame(build_evidence(frames,p)).to_string(index=False))
