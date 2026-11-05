"""因子33：10:00后回落后的攻击波；low_px 必须是已观测的本轮低点。"""
from strategy.core.protocols import FactorSpec
from strategy.core.factor_registry import register_factor
from strategy.open_break import entry_trigger_price


def levels(low_px, *, threshold_pct=.025, tick=.01, **kwargs):
    if float(low_px) <= 0:
        raise ValueError('本轮回落低点必须为正')
    return {'buy_trigger': entry_trigger_price(float(low_px), entry_pct=threshold_pct, tick=tick)}


def signal(*, low_px, last_px, threshold_pct=.025, tick=.01, **kwargs):
    target = levels(low_px, threshold_pct=threshold_pct, tick=tick)['buy_trigger']
    return {'hit_buy': float(last_px) >= target, 'buy_trigger': target}


SPEC = FactorSpec(id='factor33', name='因子33-回落后攻击波', description='10:00后任何回落重新计波，从本轮低点上涨个股阈值触买',
                  implemented=True, levels=levels, signal=signal,
                  rules_text='仅用10:00后新鲜报价；任何下跌启动新回落，连续下跌更新低点，平价不改变方向；本轮低点×(1+个股阈值)向上取整；接回必须在清仓后形成新波段；重启重新观察',
                  meta={'kind': 'day_low_rebound', 'window': '10:00:00-15:00:00'})
register_factor(SPEC, replace=True)
