"""当前扫描子集的2025、2026独立年度与跨年连续组合回放。"""
from __future__ import annotations
import hashlib
import json
import pandas as pd
from .market_scan import OUT as SCAN_OUT, config_hash
from .combo_config import config_from_bindings, compose_entry
from .reversal import Policy
from .research import simulate


def run():
    from .bindings import FACTOR_BINDINGS
    config=config_from_bindings(FACTOR_BINDINGS)
    scan=json.loads((SCAN_OUT/'snapshot.json').read_text())
    if config_hash(config)!=scan['config_hash']:raise ValueError('当前绑定与扫描配置不同，须重新扫描')
    end=min(pd.Timestamp(scan['as_of']),pd.Timestamp('2026-12-31'))
    if end<pd.Timestamp('2026-01-01'):raise ValueError('无2026行情')
    out=SCAN_OUT/'annual_2025_2026';out.mkdir(parents=True,exist_ok=True)
    raw={};coverage=[]
    for row in sorted(scan['rows'],key=lambda r:r['symbol']):
        if row['status']!='ready':continue
        s=row['symbol'];p=SCAN_OUT/'features'/f'{s}.parquet'
        f=pd.read_parquet(p);raw[s]=f
        coverage.append(dict(symbol=s,name=row['name'],start=str(f.date.min().date()),end=str(f.date.max().date()),
                             rows_2025=int(f.date.between('2025-01-01','2025-12-31').sum()),
                             rows_2026=int(f.date.between('2026-01-01',end).sum()),
                             input_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    if not raw:raise ValueError('没有齐备扫描子集')
    frames=compose_entry(raw,config['rule']);policy=Policy(**config['policy'])
    (out/'config.json').write_text(json.dumps(dict(config=config,scan_generated_at=scan['generated_at'],
        as_of=str(end.date()),universe_count=len(frames),initial_cash=1_000_000.,scope='current_fresh_cache_subset'),ensure_ascii=False,indent=2))
    pd.DataFrame(coverage).to_csv(out/'coverage.csv',index=False)
    results=[]
    periods=[('2025','2025-01-01','2025-12-31'),('2026','2026-01-01',str(end.date())),
             ('continuous','2025-01-01',str(end.date()))]
    for label,start,finish in periods:
        summary,eq,orders,tr=simulate(frames,policy,start=start,end=finish,initial_cash=1_000_000.)
        assert len(eq) and abs(float(eq.nav.iloc[-1])-summary['final_nav'])<1e-6
        assert (eq.cash>=-1e-6).all() and (orders.shares%100==0).all()
        # 逐笔按移动平均成本还原未平仓成本，验证净值收益可由已实现与浮动相加。
        held={};realized=0.
        from strategy.costs import ENGINE_COMMISSION_RATE as FEE,STAMP_TAX_RATE as TAX
        for order in orders.itertuples():
            pos=held.setdefault(order.symbol,dict(shares=0,cost=0.))
            if order.side=='buy':
                pos['shares']+=order.shares;pos['cost']+=order.shares*order.price*(1+FEE)
            else:
                basis=pos['cost']*order.shares/pos['shares']
                realized+=order.shares*order.price*(1-FEE-TAX)-basis
                pos['cost']-=basis;pos['shares']-=order.shares
        positions=[]
        for s,pos in held.items():
            if pos['shares']<=0:continue
            close=float(raw[s].loc[raw[s].date<=pd.Timestamp(finish),'close'].iloc[-1])
            positions.append(dict(symbol=s,**pos,close=close,market_value=close*pos['shares'],floating_pnl=close*pos['shares']-pos['cost']))
        floating=sum(r['floating_pnl'] for r in positions);profit=summary['final_nav']-1_000_000.
        assert abs(realized+floating-profit)<1e-6
        assert abs(float(eq.cash.iloc[-1])+sum(r['market_value'] for r in positions)-summary['final_nav'])<1e-6
        summary.update(period=label,universe_count=len(frames),net_profit=profit,realized_pnl=realized,floating_pnl=floating)
        results.append(summary)
        sub=out/label;sub.mkdir(exist_ok=True)
        for tag,df in [('equity',eq),('orders',orders),('trades',tr),('open_positions',pd.DataFrame(positions))]:df.to_csv(sub/f'{tag}.csv',index=False)
        (sub/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (out/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    lines=['# 鲍鱼捞饭：2025与2026组合回测','',
           f'当前因子30/31/32原参数固定，扫描行情齐备的{len(frames)}只主板股票，2026截至{end.date()}。范围已不限策略16，但当前名单与数据齐备状态用于选取回看子集，存在覆盖/存活偏差，不能代表全市场回测。',
           '2025、2026独立年度均从100万元空仓开始；连续区间仅在2025年初注入100万元，跨年持仓与现金延续。逐日净值包含未平仓浮动，未虚构期末平仓。费税、滑点、整手、T+1与涨跌停约束沿用现有引擎；不重新选参。',
           '入场：日线相邻下笔破前低A、破位后10日内最大量比≥1.5、下影线止跌；前收信号次开评估。风险：买价下方4%冻结止损，每笔名义风险0.5%、单票20%上限、不补仓；按A/B分批退出、最长20日。跳空与T+1可使实际亏损超过4%。',
           '', '|区间|组合收益%|净盈亏元|期末净值元|日线最大回撤%|闭环笔数|胜率%|期末持仓数|',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in results:
        title={'2025':'2025全年（独立）','2026':f'2026至{end.date()}（独立）','continuous':f'2025至{end.date()}（连续）'}[r['period']]
        lines.append(f'|{title}|{r["total_return_pct"]:.2f}|{r["net_profit"]:,.2f}|{r["final_nav"]:,.2f}|{r["max_drawdown_pct"]:.2f}|{r["n_trades"]}|{r["win_rate"]*100:.1f}|{r["open_positions"]}|')
    lines+=['','## 口径与校验',
            '- 组合收益是总账户净值变化，闭环胜率仅计算已经完全退出的交易周期。',
            '- 连续收益直接重放跨年持仓；不能由两个空仓年度收益直接相乘得到。',
            '- 全历史逐根特征预热后按区间截取。各股2025/2026实际日线条数、输入文件哈希见coverage.csv，交易日缺口不能仅凭缓存判定为停牌。',
            '- 已核对：已实现盈亏+浮动盈亏=账户净盈亏；现金+持仓市值=净值；现金非负，成交股数为100股整手。',
            '- 名单和行情覆盖来自当前截面，未完成历史逐日上市/退市/ST状态重建；少量缓存日期有间隔。退出遇开盘接近跌停时引擎保守延期，实际成交可能不同。',
            '', '复现：`.venv/bin/python -m strategy.strategies.strategy3.annual_report`。各区间的逐日净值、订单、闭环交易与期末持仓分别保存在同名子目录。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(results=results,output=str(out)),ensure_ascii=False,indent=2))
    return results


if __name__=='__main__':run()
