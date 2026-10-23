"""因子32：冻结结构失效位、前低/前高目标与风险仓位。"""
from strategy.abalone_risk import entry_plan
from strategy.core.protocols import FactorSpec
from strategy.core.factor_registry import register_factor
FACTOR_ID='factor32'
RULES_TEXT='介入前冻结A前低、B前高、C破位止跌低点，买后不下移C。比较成本止损、C下百分比及ATR缓冲。价在A下先到A减仓、再到B清仓；已收复A则到B减仓。日线收盘止损次开执行；触价版本遵守T+1与跳空成交。单票上限20%，每笔名义风险预算0.5%，再破新低不摊低补仓。'


def levels(entry_price,*,feature,**params):
    return entry_plan(feature,entry_price,params)


SPEC=FactorSpec(id=FACTOR_ID,name='因子32-结构失效与反弹退出',description='A/B/C结构空间、冻结止损、分批退出及风险仓位',
                rules_text=RULES_TEXT,levels=levels,meta={'category':'take_profit','frequency':'daily','research_only':True})
register_factor(SPEC)
