"""因子14：美股隔夜主题 → A 股联动（选股 / 开仓门控）。

A 股 T 日开盘前，用上一美股交易日主题 ETF 涨跌 + 静态主题标签，
生成 us_link_score / us_link_hit；可与因子1、因子10、策略11 叠加。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.us_a_factor import (
    DEFAULT_PARAMS,
    compute_us_a_linkage,
    factor14_signal,
    panel_us_a_linkage,
    us_a_linkage_rules_text,
    weekly_allowed_from_factor,
)

FACTOR_ID = "factor14"
FACTOR_NAME = "因子14·美股隔夜主题联动"


def _rules() -> str:
    return us_a_linkage_rules_text(DEFAULT_PARAMS)


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "美股主题 ETF 隔夜涨跌映射 A 股主题标签："
        "us_link_score 连续得分，us_link_hit 强势主题门控；"
        "周频门控供因子1 开仓 overlay"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor14_signal,
    meta={
        "kind": "us_a_theme_linkage",
        "params": dict(DEFAULT_PARAMS),
        "timing": "us_prior_session_exec_a_open",
        "data": "yfinance_theme_etf",
        "compute": compute_us_a_linkage,
        "panel": panel_us_a_linkage,
        "weekly_gate": weekly_allowed_from_factor,
        "standalone": True,
        "research_only": True,
    },
)

register_factor(SPEC)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor14_signal(**kwargs)


__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "signal"]
