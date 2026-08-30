"""因子13：策略一·因子1 契合选股。

双轨实现（详见 docs/FACTOR13.md）：
  · A 质量带：factor13_fit.py（夏普/回撤甜区 walk-forward）
  · B 熊市盾牌 thr* Top3：factor13_bear_shield.py（当前锁定，WF 样本外）
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor13_fit import (
    DEFAULT_PARAMS,
    factor13_rules_text,
    factor13_signal,
    load_best_rule,
)

FACTOR_ID = "factor13"
FACTOR_NAME = "因子13·策略1契合选股（质量带 / 熊盾）"


def _rules() -> str:
    return factor13_rules_text(load_best_rule())


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "策略1开盘突破契合选股。质量带：夏普适中、回撤甜区、score_quality TopK；"
        "生产研究默认见 factor13_bear_shield（WF thr* Top3，LOCKED.json）"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor13_signal,
    meta={
        "kind": "strategy_fit_quality_band",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "year_t_quality_band_hold_year_t_plus_1",
        "research_only": True,
        "best_rule": load_best_rule(),
        "bear_shield_locked": "backtest/factor13_bear_shield/LOCKED.json",
        "docs": "docs/FACTOR13.md",
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor13_signal(**kwargs)
