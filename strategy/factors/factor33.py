"""因子33：10:00后当日最低价反弹，阈值使用策略个股阈值。"""
from strategy.core.protocols import FactorSpec
from strategy.core.factor_registry import register_factor
from strategy.open_break import entry_trigger_price


def levels(low_px, *, threshold_pct=.025, tick=.01, **kwargs):
    if float(low_px) <= 0:
        raise ValueError('当日最低价必须为正')
    return {'buy_trigger': entry_trigger_price(float(low_px), entry_pct=threshold_pct, tick=tick)}


def signal(*, low_px, last_px, threshold_pct=.025, tick=.01, **kwargs):
    target = levels(low_px, threshold_pct=threshold_pct, tick=tick)['buy_trigger']
    return {'hit_buy': float(last_px) >= target, 'buy_trigger': target}


SPEC = FactorSpec(id='factor33', name='因子33-日内低点反弹', description='10:00后以当日最低价上涨个股阈值触买，禁止开盘突破补买',
                  implemented=True, levels=levels, signal=signal,
                  rules_text='当日新鲜行情最低价×(1+个股阈值)，向上按最小价位取整；仅10:00后；实时报价成交，不回填历史低价',
                  meta={'kind': 'day_low_rebound', 'window': '10:00:00-15:00:00'})
register_factor(SPEC, replace=True)
