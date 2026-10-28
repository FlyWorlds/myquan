"""组合因子决策：显式日线收盘快照/次开重放上下文；不接实盘自动下单。"""
from __future__ import annotations
import math
import pandas as pd
from strategy.core.context import Decision
from strategy.factors.factor30 import signal as structural
from strategy.factors.factor31 import signal as exhaustion
from strategy.factors.factor32 import levels
from strategy.costs import SLIPPAGE_VALUE
from .combo_config import config_from_bindings


class Strategy3Decision:
    strategy_id='strategy3'
    strategy_name='策略三·鲍鱼捞饭'

    def __init__(self,bindings):
        self.bindings=tuple(bindings)
        cfg=config_from_bindings(bindings);self.rule=cfg['rule'];self.policy=cfg['policy']

    def decide(self,ctx):
        # 禁止把默认策略16的盘中报价或未收盘K线误当日线信号。
        row=ctx.meta.get('strategy3_daily_feature')
        if not isinstance(row,dict) or not row.get('date') or not ctx.session:
            return Decision.hold('策略3需要完整日线结构快照',research_only=True)
        try:
            prior=pd.Timestamp(row['date']).date();today=pd.Timestamp(ctx.session).date()
        except (ValueError,TypeError):return Decision.hold('日线时间无效')
        if prior>=today:return Decision.hold('日线尚未完成，禁止当日回填')
        if ctx.holding:
            state=ctx.meta.get('strategy3_position') or {}
            if not state:return Decision.hold('缺少入场冻结A/B/C，不推断持仓止损')
            if ctx.t_plus_one:return Decision.hold('T+1买入当日不可卖')
            if ctx.prev_close and ctx.open<=ctx.prev_close*.902:
                return Decision.hold('跌停开盘卖出保守顺延')
            cost=float(state.get('cost_basis') or ctx.entry_price or 0)
            stop=cost*(1-self.policy['stop']) if self.policy['stop_mode']=='cost' and self.policy['risk_budget']==0 else float(state['stop_px'])
            reason=''
            if ctx.meta.get('strategy3_stop_tick') and self.policy.get('stop_trigger')=='intraday' and ctx.price<=stop:
                reason='冻结止损触价'
                px=ctx.price
            elif ctx.meta.get('strategy3_next_open'):
                px=ctx.open
                if state.get('pending_exit'):reason=state['pending_exit']
                elif row['close']<=stop:reason='收盘跌破冻结失效位'
                elif self.policy.get('stop_trigger') in ('intraday','touch_next_open') and row['low']<=stop:
                    reason='日低触线后次开退出'
                elif int(state.get('age',0))>=self.policy['hold']:reason='持有到期'
                elif not state.get('reduced') and row['close']>=state['target_px']:
                    qty=int(ctx.position_qty*self.policy['reduce']//100)*100
                    qty=qty if qty>=100 else ctx.position_qty
                    return Decision.sell(px,reason='前低/前高目标减仓',factor_id='factor32',qty=qty,
                                         research_only=True,auto_trade=False)
                elif state.get('reduced') and state.get('second_target_px') and row['close']>=state['second_target_px']:
                    reason='前高目标清仓'
                elif state.get('reduced') and row['close']<=state.get('peak',row['close'])*.97:
                    reason='止盈后峰值回落3%'
            else:return Decision.hold('等待次开或过夜持仓触价检查')
            if reason:return Decision.sell(px,reason=reason,factor_id='factor32',research_only=True,auto_trade=False)
            return Decision.hold('未触发结构退出')
        if not ctx.meta.get('strategy3_next_open'):return Decision.hold('日线信号等待下一交易日开盘')
        if not structural(row,**self.rule)['passed'] or not exhaustion(row,**self.rule)['passed']:
            return Decision.hold('结构或放量止跌因子未满足')
        if ctx.prev_close and not .902<ctx.open/ctx.prev_close<1.098:
            return Decision.hold('开盘接近涨跌停，保守跳过')
        p=levels(ctx.open*(1+SLIPPAGE_VALUE),feature=row,**self.policy)
        if not p['allowed']:return Decision.hold(p['reason'])
        target_pct=self.policy['slot']*self.policy['initial']
        if self.policy['risk_budget']>0:target_pct=min(target_pct,self.policy['risk_budget']/p['risk_pct'])
        return Decision.buy(ctx.open,reason='因子30结构破位+因子31放量止跌',factor_id='factor31',
                            target_pct=target_pct,plan=p,event_id=row['event_id'],
                            factor_ids=['factor30','factor31','factor32'],research_only=True,auto_trade=False)


def create_decision_engine(spec=None):
    from .bindings import FACTOR_BINDINGS
    return Strategy3Decision(spec.factor_bindings if spec else FACTOR_BINDINGS)
