"""固定组合退出，对照信号次开与下一交易日收阳后再于后一天开盘买入。"""
from __future__ import annotations
import hashlib,json
import pandas as pd
from .manual_scan import OUT as SOURCE
from .combo_config import config_from_bindings,compose_entry
from .market_scan import config_hash
from .reversal import Policy
from .research import simulate

OUT=SOURCE/'confirmation_study'
VARIANTS={'baseline':'原组合：信号次开买入','bullish':'次日收阳确认，再次开买入',
          'bullish_no_new_low':'次日收阳且不破信号日低点，再次开买入'}
STRUCTURE=('event_id','anchor_date','anchor','peak','top_date','known_date','break_age',
           'trough','break_volume','accelerated','stage20','stage60','stage120','depth','broken')


def confirm_frame(f,mode,calendar):
    """确认行只读前一行信号与本行收盘，OHLC始终保留本行，执行由simulate再延后一根。"""
    if mode=='baseline':return f.copy()
    if mode not in VARIANTS:raise ValueError(mode)
    g=f.copy();g['stabilize']=False;g['confirmation_source_date']=''
    next_day={a:b for a,b in zip(calendar[:-1],calendar[1:])}
    for prev_i in f.stabilize.fillna(False).to_numpy().nonzero()[0]:
        i=int(prev_i)+1
        if i>=len(f):continue
        prev=f.iloc[i-1];now=f.iloc[i]
        if not prev.stabilize or next_day.get(prev.date)!=now.date:continue
        if not now.close>now.open:continue
        if mode=='bullish_no_new_low' and now.low<prev.low:continue
        for field in STRUCTURE:g.at[i,field]=prev[field]
        # 原A/B事件保留，C仅吸收截至确认日已知的低点，不从之后的走势回填。
        trough=min(float(prev.trough),float(now.low))
        g.at[i,'trough']=trough;g.at[i,'depth']=max(0.,1-trough/float(prev.anchor))
        g.at[i,'break_age']=int(prev.break_age)+1
        g.at[i,'break_volume']=max(float(prev.break_volume),float(now.vol_ratio))
        g.at[i,'stabilize']=True;g.at[i,'confirmation_source_date']=str(prev.date.date())
    return g


def run():
    from .bindings import FACTOR_BINDINGS
    cfg=config_from_bindings(FACTOR_BINDINGS);scan=json.loads((SOURCE/'snapshot.json').read_text())
    if scan.get('config_hash')!=config_hash(cfg):raise ValueError('扫描与当前绑定不一致')
    OUT.mkdir(parents=True,exist_ok=True)
    raw={};coverage=[]
    for r in sorted(scan['rows'],key=lambda r:r['symbol']):
        if r['status']!='ready':continue
        s=r['symbol'];path=SOURCE/'features'/f'{s}.parquet';f=pd.read_parquet(path)
        raw[s]=f
        coverage.append(dict(symbol=s,name=r['name'],start=str(f.date.min().date()),end=str(f.date.max().date()),
                             rows2025=int(f.date.between('2025-01-01','2025-12-31').sum()),
                             rows2026=int(f.date.between('2026-01-01',scan['as_of']).sum()),
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if not raw:raise ValueError('无行情')
    calendar=sorted(set(t for f in raw.values() for t in f.date));base=compose_entry(raw,cfg['rule'])
    policy=Policy(**cfg['policy']);periods=[('2025','2025-01-01','2025-12-31'),('2026','2026-01-01',scan['as_of']),('continuous','2025-01-01',scan['as_of'])]
    pd.DataFrame(coverage).to_csv(OUT/'coverage.csv',index=False)
    (OUT/'config.json').write_text(json.dumps(dict(binding=cfg,variants=VARIANTS,universe_count=len(raw),
         as_of=scan['as_of'],scan_generated_at=scan['generated_at'],initial_cash=1_000_000.,
         primary_comparison='bullish_vs_baseline',active_binding_changed=False),ensure_ascii=False,indent=2))
    results=[];signals=[]
    for mode,label in VARIANTS.items():
        frames={s:confirm_frame(f,mode,calendar) for s,f in base.items()}
        for period,start,end in periods:
            summary,eq,orders,tr=simulate(frames,policy,start=start,end=end,initial_cash=1_000_000.)
            assert (eq.cash>=-1e-6).all()
            summary.update(variant=mode,variant_label=label,period=period,net_profit=summary['final_nav']-1_000_000.,universe_count=len(raw))
            results.append(summary);folder=OUT/mode/period;folder.mkdir(parents=True,exist_ok=True)
            for name,df in [('equity',eq),('orders',orders),('trades',tr)]:df.to_csv(folder/f'{name}.csv',index=False)
            n=sum(int((f.stabilize & f.date.between(start,end)).sum()) for f in frames.values())
            stopped=int(tr.exit_reason.str.contains('止损').sum()) if len(tr) else 0
            signals.append(dict(variant=mode,period=period,signal_days=n,closed_trades=len(tr),stop_cycles=stopped))
            print(mode,period,round(summary['total_return_pct'],3),summary['n_trades'],flush=True)
    pd.DataFrame(results).to_csv(OUT/'summary.csv',index=False);pd.DataFrame(signals).to_csv(OUT/'signal_counts.csv',index=False)
    (OUT/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    matched=matched_entries()
    lines=['# 鲍鱼捞饭：次日阳线二次确认对照','',
           f'固定当前因子30/31/32与仓位退出，只改变入场确认。范围为当前中证1000过滤后、日线截至{scan["as_of"]}齐备的{len(raw)}只股票；不是之前80只，旧收益不能直接当作本轮基准。当前成分/名称与数据覆盖回看历史，有存活及覆盖偏差，尚未重建历史逐日成分与ST状态。',
           '', '## 事先定义的三组',
           '- 原组合：D日收盘形成鲍鱼信号，D+1开盘重算价格后买入。',
           '- 主对照：D+1收盘价>当日开盘价才确认，D+2开盘评估买入；十字星或阴线不确认。阳线允许收盘低于D日收盘。',
           '- 附加对照：在收阳之外，要求D+1最低价>=D日最低价，再于D+2开盘评估。',
           '- D+1必须是全样本交易日历中的下一交易日，停牌导致缺这一日则不把隔数日的K线冒充次日确认。确认后实际执行仍按原引擎的次开及停牌间隔约束。',
           '- 确认沿用D日A/B事件，C吸收确认日已知低点；确认时ATR与价格取确认日已知值，买入后止损冻结。允许确认日进入反弹上笔，不要求它再独立出现一次下影信号。',
           '- 原信号的破位窗口为D日判断，额外确认最多延后一日。连续信号各可产生次日确认机会；每轮结构最多成功买入一次。',
           '- 年度各从100万元空仓开始；连续区间跨年持仓延续。成本4%触价止损、每笔名义风险0.5%、单票20%上限、不补仓、A/B分批止盈和20日持仓上限全部固定。含费用、滑点、整手及T+1。',
           '', '|区间|入场条件|组合收益%|日线最大回撤%|闭环笔数|胜率%|平均持有日|期末持仓|', '|---|---|---:|---:|---:|---:|---:|---:|']
    for period,_,_ in periods:
        for r in results:
            if r['period']!=period:continue
            lines.append(f'|{period}|{r["variant_label"]}|{r["total_return_pct"]:.2f}|{r["max_drawdown_pct"]:.2f}|{r["n_trades"]}|{r["win_rate"]*100:.1f}|{r["mean_hold_days"]:.1f}|{r["open_positions"]}|')
    lines+=['','## 信号与止损数量','|区间|条件|信号日数|闭环笔数|止损闭环|','|---|---|---:|---:|---:|']
    for r in signals:lines.append(f'|{r["period"]}|{VARIANTS[r["variant"]]}|{r["signal_days"]}|{r["closed_trades"]}|{r["stop_cycles"]}|')
    lines+=['','结果是描述性对照，不按2026收益反复调阈值，也不自动替换正式绑定。信号减少、交易更少不必然意味着更可靠；比较总账户净值，期末持仓按收盘浮动计价，不虚构平仓。',
            '复现：`.venv/bin/python -m strategy.strategies.strategy3.confirmation_study`。各组/区间逐日净值、订单、交易明细，及输入哈希、覆盖表均保存在本目录。']
    lines+=['','## 同一结构的买入价格对照',
            '只比较两组都实际买入的同一股票/事件，因此是成交交集描述，不能解释所有过滤与资金占用变化，也不声称因果。']
    for r in matched:
        lines.append(f'{r["period"]}共有{r["matched_events"]}轮匹配结构，确认组{r["higher_entry_fraction"]*100:.1f}%买价更高；买价变化中位数{r["median_entry_change_pct"]:.2f}%，均值{r["mean_entry_change_pct"]:.2f}%。')
    lines+=['','## 本轮处置','主对照在2025、2026收益均弱于原组合，且回撤更大、胜率更低；当前结果不支持加入单纯次日收阳确认。附加“不破信号日低点”也没有改善2026结果。正式绑定保持不变。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(results=results,output=str(OUT)),ensure_ascii=False,indent=2),flush=True)
    return results


def matched_entries():
    results=[]
    for year in ('2025','2026'):
        a=pd.read_csv(OUT/'baseline'/year/'orders.csv');b=pd.read_csv(OUT/'bullish'/year/'orders.csv')
        g=a[a.side=='buy'].merge(b[b.side=='buy'],on=['symbol','event_id'],suffixes=('_base','_confirm'))
        delta=(g.price_confirm/g.price_base-1)*100
        results.append(dict(period=year,matched_events=len(g),higher_entry_fraction=float((delta>0).mean()),
                            median_entry_change_pct=float(delta.median()),mean_entry_change_pct=float(delta.mean())))
        g.to_csv(OUT/f'matched_entries_{year}.csv',index=False)
    (OUT/'matched_entry_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return results


if __name__=='__main__':run()
