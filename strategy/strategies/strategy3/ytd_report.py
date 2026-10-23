"""固定已绑定参数的年内回测；全历史预热，年初空仓起算，不重新选参。"""
from __future__ import annotations
import json
import hashlib
import numpy as np
import pandas as pd
from strategy.costs import ENGINE_COMMISSION_RATE as FEE, STAMP_TAX_RATE as TAX
from .reversal import ROOT,POOL,Policy,load_daily
from .factor_mining import features
from .combo_config import config_from_bindings,compose_entry
from .research import simulate


def run_ytd(year=2026,initial_cash=1_000_000.):
    from .bindings import FACTOR_BINDINGS
    cfg=config_from_bindings(FACTOR_BINDINGS)
    now=pd.Timestamp.now(tz='Asia/Shanghai')
    latest=now.normalize().tz_localize(None)
    if (now.hour,now.minute)<(15,15):latest-=pd.Timedelta(days=1)
    data={};coverage=[]
    for it in json.loads(POOL.read_text())['picks']:
        code=it['code'];s=('sh' if code.startswith('6') else 'sz')+code
        d,meta=load_daily(s)
        if d.empty:raise ValueError(f'{s}无日线')
        d=d[d.date<=latest]
        if d.empty:raise ValueError(f'{s}无完整日线')
        data[s]=d;coverage.append(meta)
    end=min(d.date.max() for d in data.values())
    start=pd.Timestamp(f'{year}-01-01')
    if end<start:raise ValueError('年内尚无可回测的共同完整日线')
    out=ROOT/f'backtest/strategy3_abalone/ytd_{year}'
    out.mkdir(parents=True,exist_ok=True)
    frames={}
    for s,d in data.items():
        d=d[d.date<=end]
        frames[s]=features(d,s)
        frames[s].to_parquet(out/f'{s}_features.parquet',index=False)
        meta=next(x for x in coverage if x['symbol']==s)
        meta['used_end']=str(end.date());meta['used_rows']=len(d)
        meta['input_hash']=hashlib.sha256(pd.util.hash_pandas_object(d,index=False).values.tobytes()).hexdigest()
    print('features ready',len(frames),'end',str(end.date()),flush=True)
    pf=compose_entry(frames,cfg['rule']);policy=Policy(**cfg['policy'])
    summary,eq,orders,tr=simulate(pf,policy,start=str(start.date()),end=str(end.date()),initial_cash=initial_cash)
    for name,d in [('equity',eq),('orders',orders),('trades',tr)]:d.to_csv(out/f'{name}.csv',index=False)
    positions={};realized=0.
    for row in orders.itertuples():
        s=row.symbol;qty=int(row.shares)
        if row.side=='buy':
            pos=positions.setdefault(s,dict(shares=0,cost=0.,entry_date=row.date,stop_px=row.stop_px,
                                           anchor=row.anchor,prior_high=row.prior_high,event_low=row.event_low))
            pos['shares']+=qty;pos['cost']+=qty*row.price*(1+FEE)
        else:
            pos=positions[s];basis=pos['cost']*qty/pos['shares']
            realized+=qty*row.price*(1-FEE-TAX)-basis
            pos['cost']-=basis;pos['shares']-=qty
            if not pos['shares']:del positions[s]
    names={('sh' if p['code'].startswith('6') else 'sz')+p['code']:p['name'] for p in json.loads(POOL.read_text())['picks']}
    held=[]
    for s,pos in positions.items():
        close=float(frames[s].close.iloc[-1]);value=close*pos['shares']
        held.append(dict(symbol=s,name=names[s],**pos,close=close,average_cost=pos['cost']/pos['shares'],
                         market_value=value,floating_pnl=value-pos['cost'],weight=value/summary['final_nav']))
    floating=sum(r['floating_pnl'] for r in held)
    cash=float(eq.cash.iloc[-1]);nav=float(eq.nav.iloc[-1])
    assert abs(realized+floating-(nav-initial_cash))<1e-6
    assert abs(cash+sum(r['market_value'] for r in held)-nav)<1e-6
    summary.update(initial_cash=initial_cash,net_profit=nav-initial_cash,realized_pnl=realized,floating_pnl=floating,
                   cash=cash,holding_weight=sum(r['market_value'] for r in held)/nav,requested_start=str(start.date()),
                   data_end=str(end.date()),universe_count=len(frames),start_flat=True)
    monthly=[];prior=initial_cash
    for month,g in eq.groupby(eq.date.str[:7],sort=True):
        last=float(g.nav.iloc[-1]);series=pd.Series([prior,*g.nav.to_list()])
        exits=tr[tr.exit_date.str.startswith(month)] if len(tr) else tr
        monthly.append(dict(month=month,return_pct=(last/prior-1)*100,pnl=last-prior,
                            max_drawdown_pct=float((series/series.cummax()-1).min()*100),
                            closed_trades=len(exits),end_nav=last))
        prior=last
    pd.DataFrame(monthly).to_csv(out/'monthly.csv',index=False)
    pd.DataFrame(held).to_csv(out/'open_positions.csv',index=False)
    (out/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (out/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))
    report=[f'# 鲍鱼捞饭：{year}年至今固定参数回测','',
            f'区间：{summary["start"]}—{end.date()}（共同完整日线；当前日期为{now.date()}）。资金{initial_cash:,.0f}元，年初空仓起算；更早历史仅预热结构，不带入上一年持仓。',
            '因子30结构前低破位 AND 因子31破位后1.5倍放量下影线，因子32执行成交价下4%触价止损、A前低/B前高分批退出、最长20交易日。沿用已绑定参数，本轮未重新选参。',
            '每笔名义风险预算0.5%，单票资金上限20%，按止损距离缩放股数；不补仓。双边0.1%滑点及统一佣金/杂费/卖出印花税计入收益。T+1买日触线次开处理，过夜触价可退出；跳空与跌停顺延可能扩大损失。',
            '', '## 结果',
            f'- 总收益：{summary["total_return_pct"]:.2f}%；净收益：{summary["net_profit"]:,.2f}元；期末净值：{nav:,.2f}元。',
            f'- 日线最大回撤：{summary["max_drawdown_pct"]:.2f}%；夏普：{summary["sharpe_ratio"]:.2f}。',
            f'- 平仓{summary["n_trades"]}轮，胜率{summary["win_rate"]*100:.1f}%，平均持有{summary["mean_hold_days"]:.1f}个交易日；期末未平仓{len(held)}只。',
            f'- 已实现收益：{realized:,.2f}元；期末浮动收益：{floating:,.2f}元；现金：{cash:,.2f}元；期末持仓占比{summary["holding_weight"]*100:.1f}%。',
            '', '## 月度', '|月份|收益%|盈亏元|月内最大回撤%|平仓轮数|','|---|---:|---:|---:|---:|']
    for r in monthly:report.append(f'|{r["month"]}|{r["return_pct"]:.2f}|{r["pnl"]:,.2f}|{r["max_drawdown_pct"]:.2f}|{r["closed_trades"]}|')
    report+=['','## 期末持仓','|股票|股数|买入日|含佣成本|期末收盘|浮盈亏元|占净值%|','|---|---:|---|---:|---:|---:|---:|']
    for r in held:report.append(f'|{r["name"]} {r["symbol"]}|{r["shares"]}|{r["entry_date"]}|{r["average_cost"]:.4f}|{r["close"]:.2f}|{r["floating_pnl"]:,.2f}|{r["weight"]*100:.1f}|')
    report+=['','## 逐轮平仓交易','|股票|买入日|平仓日|持有日|整轮净收益%|盈亏元|退出原因|','|---|---|---|---:|---:|---:|---|']
    for r in tr.itertuples():report.append(f'|{names[r.symbol]} {r.symbol}|{r.entry_date}|{r.exit_date}|{r.hold_days}|{r.return_pct:.2f}|{r.pnl:,.2f}|{r.exit_reason}|')
    report+=['','## 边界',
            '使用策略16截至2026-09-30的当前30只冻结名单回看年初，含选股/幸存者偏差；不是当时已知选股池的可交易实绩。2025以后也曾用于历史复核，不是全新盲测。',
            '期末未平仓按共同截止日收盘计价，未虚构卖出；浮动收益未预扣未来卖出费税。最大回撤来自逐日组合净值，不是盘中回撤。',
            '逐笔委托见orders.csv、逐轮平仓见trades.csv、每日净值见equity.csv；已实现+浮动=净收益、现金+市值=期末净值均已对账。',
            '复现：`.venv/bin/python -m strategy.strategies.strategy3.ytd_report`。']
    (out/'REPORT.md').write_text('\n'.join(report))
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    return dict(summary=summary,monthly=monthly,open_positions=held,output=str(out))


if __name__=='__main__':run_ytd()
