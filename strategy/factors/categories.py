"""因子池分类（Web / 文档共用）。

策略 = 因子组合 + 执行；因子按经济含义归类，不按「是否曾注册成 strategyN」。
"""

from __future__ import annotations

from typing import Any, Mapping

# 展示顺序即因子说明页分区顺序
CATEGORIES: tuple[dict[str, str], ...] = (
    {
        "id": "execution",
        "label": "开盘执行",
        "hint": "开盘突破买卖、止损与 T+1 规则，可被多策略复用。",
    },
    {
        "id": "drawdown",
        "label": "回撤补仓",
        "hint": "按权益回撤给加减仓预警，默认回测不注资。",
    },
    {
        "id": "take_profit",
        "label": "止盈持股",
        "hint": "牛市 regime 内暂停/放宽止损，或趋势持股叠加。",
    },
    {
        "id": "momentum",
        "label": "动量",
        "hint": "截面/时序动量、近高、ETF 轮动与价格选股。",
    },
    {
        "id": "reversal",
        "label": "反转",
        "hint": "超跌反转、流动性门控反转。",
    },
    {
        "id": "chan",
        "label": "缠论",
        "hint": "结构买卖点与笔归因盈亏比（评估，不直接下单）。",
    },
    {
        "id": "sentiment",
        "label": "情绪题材",
        "hint": "涨停/跌停情绪、题材共振、前瞻主题。",
    },
    {
        "id": "quality",
        "label": "选股质量",
        "hint": "策略1 契合度、熊盾名单、龙头排序。",
    },
)

CATEGORY_LABEL: dict[str, str] = {c["id"]: c["label"] for c in CATEGORIES}

# factor_id → category_id
FACTOR_CATEGORY: dict[str, str] = {
    "factor1": "execution",
    "factor2": "drawdown",
    "factor3": "momentum",
    "factor4": "take_profit",
    "factor5": "sentiment",
    "factor6": "momentum",
    "factor7": "momentum",
    "factor8": "chan",
    "factor9": "momentum",
    "factor10": "momentum",
    "factor11": "momentum",
    "factor12": "reversal",
    "factor13a": "quality",
    "factor13b": "quality",
    "factor13": "quality",
    "factor14": "sentiment",
    "factor15": "sentiment",
    "factor16": "quality",
    "factor17": "chan",
    "factor18": "sentiment",
    "factor19": "reversal",
    "factor20": "reversal",
    "factor21": "reversal",
    "factor22": "momentum",
    "factor23": "take_profit",
    "factor24": "sentiment",
    "factor25": "take_profit",
    "cf1": "reversal",
}


def category_of(factor_id: str, meta: Mapping[str, Any] | None = None) -> str:
    fid = str(factor_id)
    if fid in FACTOR_CATEGORY:
        return FACTOR_CATEGORY[fid]
    m = dict(meta or {})
    raw = str(m.get("category") or m.get("kind") or "").strip()
    if raw in CATEGORY_LABEL:
        return raw
    return "momentum"


def category_label(category_id: str) -> str:
    return CATEGORY_LABEL.get(str(category_id), "其他")


def list_category_catalog() -> list[dict[str, str]]:
    return [dict(c) for c in CATEGORIES]
