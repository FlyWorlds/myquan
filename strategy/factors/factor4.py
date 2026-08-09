"""因子4：动量因子（独立，单票时序）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.momentum import DEFAULT_KIND, DEFAULT_PARAMS, momentum_rules_text

FACTOR_ID = "factor4"
FACTOR_NAME = "因子4·动量"

_RULES = momentum_rules_text(DEFAULT_KIND, DEFAULT_PARAMS)

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="动量因子：默认 dist_hl(N日高低点时间距离)；收盘确认、次日开盘；可解释实现（非 Alpha191 黑盒）",
    rules_text=_RULES,
    implemented=True,
    meta={
        "kind": "momentum",
        "standalone": True,
        "default_kind": DEFAULT_KIND,
        "default_params": {
            "n": DEFAULT_PARAMS["n"],
            "enter": DEFAULT_PARAMS["enter"],
            "exit": DEFAULT_PARAMS["exit"],
        },
        "mine_window": "2022+",
        "akquant_sharpe_kaicheng": 1.536,
    },
)

register_factor(SPEC, replace=True)
