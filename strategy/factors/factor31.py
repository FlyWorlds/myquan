"""因子31：破位后量能释放与下影/收复的组合止跌信号。"""
from strategy.abalone_risk import value
from strategy.core.protocols import FactorSpec
from strategy.core.factor_registry import register_factor
FACTOR_ID='factor31'
RULES_TEXT='本轮破位后最大量比≥1.5（每日日量/此前20日均量）；下影占振幅≥45%、收盘在上方40%、下影≥0.5个前日ATR14，或收复前低。加速与长阴变短仅作对照，不能单独代替确认。'


def signal(row,*,trigger='shadow',volume=1.5,**_):
    shadow=bool(value(row,'shadow',False));recover=bool(value(row,'recovered',False))
    passed={'shadow':shadow,'recover':recover,'either':shadow or recover}.get(trigger,False)
    try:passed=passed and float(value(row,'break_volume',0))>=float(volume)
    except (TypeError,ValueError):passed=False
    return dict(passed=bool(passed),factor_id=FACTOR_ID,trigger=trigger)


SPEC=FactorSpec(id=FACTOR_ID,name='因子31-放量破位止跌',description='放量释放后，下影线或收复结构前低的日线止跌候选',
                rules_text=RULES_TEXT,signal=signal,meta={'category':'reversal','frequency':'daily','research_only':True})
register_factor(SPEC)
