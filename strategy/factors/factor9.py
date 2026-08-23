"""因子9：日线多空动能（追涨杀跌，选股 / 开仓门控）。

T 日收盘计算，T+1 开盘可用。研究 overlay，默认不改援军战法绑定。
"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.ls_energy import DEFAULT_PARAMS, compute_ls_energy, ls_energy_rules_text

FACTOR_ID = "factor9"
FACTOR_NAME = "因子9·日线多空动能"


def _rules() -> str:
    return ls_energy_rules_text(DEFAULT_PARAMS)


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="日线多空动能：追涨杀跌净能量，截面 TopK 作为因子1 开仓门控",
    rules_text=_rules(),
    implemented=True,
    meta={
        "kind": "ls_energy",
        "params": dict(DEFAULT_PARAMS),
        "timing": "close_t_exec_tplus1",
        "compute": compute_ls_energy,
    },
)

register_factor(SPEC)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC"]
