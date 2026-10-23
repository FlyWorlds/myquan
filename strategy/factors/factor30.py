"""因子30：当时可知的A底分型→上笔→B顶分型→相邻下笔破A。"""
from strategy.abalone_risk import value
from strategy.core.protocols import FactorSpec
from strategy.core.factor_registry import register_factor

FACTOR_ID='factor30'
RULES_TEXT='A为最近向上一笔起点底分型低点，B为终点顶分型；只观察B之后的相邻下行笔破A。下笔允许正在发展；不等最终底分型再回填。每轮结构一个事件，破位后10日内有效。'


def signal(row,*,window=10,support='chan',**_):
    try:
        age=float(value(row,'break_age',-1))
        valid=(bool(value(row,'broken',False)) and bool(value(row,'down_leg',False))
               and 0<=age<=int(window) and bool(value(row,'event_id','')))
        if support!='chan':valid=valid and bool(value(row,support,False))
    except (TypeError,ValueError):valid=False
    return dict(passed=bool(valid),factor_id=FACTOR_ID)


SPEC=FactorSpec(id=FACTOR_ID,name='因子30-结构前低破位',description='缠论相邻笔结构前低、前高及破位事件过滤',
                rules_text=RULES_TEXT,signal=signal,meta={'category':'chan','frequency':'daily','research_only':True})
register_factor(SPEC)
