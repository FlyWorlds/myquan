"""策略三·鲍鱼捞饭：缠论结构前低与破位后的量价衰竭实验。"""
from __future__ import annotations
import json
from functools import lru_cache
import pandas as pd
from strategy.strategies.strategy3.reversal import POOL, ROOT, load_daily, Policy
from strategy.strategies.strategy3.factor_mining import OUT as MINING_OUT, features
from strategy.strategies.strategy3.stop_study import OUT
from strategy.strategies.strategy3.bindings import FACTOR_BINDINGS
from strategy.strategies.strategy3.combo_config import config_from_bindings
from strategy.factors.factor30 import signal as structure_signal
from strategy.factors.factor31 import signal as exhaustion_signal
from strategy.factors.factor32 import levels as risk_levels
from strategy.costs import SLIPPAGE_VALUE
from strategy.strategies.strategy3.market_scan import completed_day, config_hash
from strategy.strategies.strategy3.manual_scan import OUT as SCAN_OUT, SCOPE

RULES=('前低A=最新向上一笔起点的底分型；终点为顶分型B。B后的相邻下行笔（允许正在发展）跌破A，'
       '才进入本轮观察。破位后10日内比较放量、长阴缩短、下影线、低点抬高、收复前低；'
       '日收盘信号次日开盘评估，不事后回填。所有候选仍为研究观察。')


def _load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def load_backtest_summary():
    return _load(OUT/'summary.json',[])


def build_strategy3_payload(rows=None, *, session=None, get_quote=None, batch_quote=None):
    del rows,get_quote,batch_quote
    scan=_load(SCAN_OUT/'snapshot.json',{})
    if scan.get('scope')!=SCOPE:scan={}
    pool={'as_of':scan.get('as_of'),'picks':[r for r in scan.get('rows',[]) if r.get('status')=='ready' and (r.get('warning') or r.get('candidate'))]}
    selected=config_from_bindings(FACTOR_BINDINGS)
    rule=selected['rule']
    policy=Policy(**selected['policy'])
    completed=completed_day()
    if session:completed=min(completed,pd.Timestamp(session).normalize())
    scan_valid=(scan.get('as_of')==str(completed.date()) and scan.get('config_hash')==config_hash(selected))
    result=[]
    for item in pool['picks']:
        code=item['code'];symbol=('sh' if code.startswith('6') else 'sz')+code
        cached=SCAN_OUT/'features'/f'{symbol}.parquet'
        f=pd.read_parquet(cached) if cached.exists() else pd.DataFrame()
        if len(f):f=f[f.date<=completed]
        meta=item.get('meta',{})
        row={'代码':code,'名称':item['name'],'状态':'历史不足','可操作':False,'数据截至':meta.get('end')}
        if len(f):
            r=f.iloc[-1]
            state=('破位后量价观察' if r.broken else '相邻下行笔未破前低' if r.down_leg else '等待底分型→上笔→顶分型')
            if r.broken and r.recovered:state='破前低后收复'
            elif r.broken and r.shadow:state='破位后长下影'
            elif r.broken and r.small_bear:state='破位后阴线缩短'
            plan=risk_levels(float(r.close)*(1+SLIPPAGE_VALUE),feature=r,**policy.dict())
            passed=structure_signal(r,**rule)['passed'] and exhaustion_signal(r,**rule)['passed']
            row.update({'状态':state,'前底日期':r.anchor_date,'顶分型日期':r.top_date,
                        '破位预警':bool(scan_valid and item.get('warning')),
                        '前底':None if pd.isna(r.anchor) else float(r.anchor),
                        '破位深度':float(r.depth),'三日动量':float(r.mom3),
                        '加速下跌':bool(r.accelerated),'止跌确认':bool(r.higher_low),
                        '候选信号':bool(scan_valid and passed and plan['allowed']),'现价':float(r.close),
                        '量比':float(r.vol_ratio),'破位最大量比':float(r.break_volume),
                        '下影占比':float(r.lower_shadow),'阴线实体ATR':float(r.body_atr),
                        '数据截至':str(r.date.date()),'挂单说明':'参考价位按完整日线收盘估算；次开重算，入场后冻结C，不自动成交',
                        '前高':None if pd.isna(r.peak) else float(r.peak),
                        '止跌低点':None if pd.isna(r.trough) else float(r.trough),
                        '参考止损':plan.get('stop_px'),'第一目标':plan.get('target_px'),
                        '第二目标':plan.get('second_target_px'),'止损距离':plan.get('risk_pct'),
                        '空间风险比':plan.get('reward_risk'),'入场位置':plan.get('location'),
                        '价位可用':plan['allowed']})
        result.append(row)
    result.sort(key=lambda r:(not r.get('候选信号',False),not r.get('破位预警',False),r['代码']))
    comparisons=[];failed=None
    summary=[]  # 手动监控面板不混用旧固定池/80股回测。
    return dict(name='鲍鱼捞饭',rules=RULES,rows=result,backtest=summary,policy=policy.dict(),
                poolDate=pool.get('as_of'),poolCount=len(result),effectiveTradeDate=str(completed.date()),
                scanCoverage=dict(universeCount=scan.get('universe_count',0),scannedCount=scan.get('scanned_count',0),
                                  candidateCount=sum(bool(r.get('候选信号')) for r in result),
                                  warningCount=sum(bool(r.get('破位预警')) for r in result),
                                  counts=scan.get('counts',{}),valid=scan_valid),
                researchOnly=True,boundFactors=[b.factor_id for b in FACTOR_BINDINGS],factorResearch=dict(rule=rule,failed=failed,comparisons=comparisons),
                cacheNote=('仅手动点击扫描。范围为中证1000成分股，剔除ST、科创、创业及新三板；不混入中证500或原策略池。'
                           +('尚未扫描或结果已过期，请点击扫描。' if not scan_valid else '')
                           +'相邻下笔破前低A列入预警；满足因子30/31/32再标记鲍鱼捞饭，不自动买入。'))


@lru_cache(maxsize=128)
def _features_completed(symbol,stamp,cutoff):
    del stamp
    d,meta=load_daily(symbol)
    if not d.empty:d=d[d.date<=pd.Timestamp(cutoff)]
    return (features(d,symbol) if len(d)>=70 else pd.DataFrame()),meta
