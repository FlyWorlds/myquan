"""因子2：回撤加减仓预警（回测不介入权益）。

真源：strategy.dd_alert
旧版「权益注资叠加」仍保留在 strategy.dd_topup，默认不再挂到策略一回测。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.dd_alert import (
    DEFAULT_AVG_YEARLY_MAX_DD,
    DEFAULT_HIST_MAX_DD,
    DdAlertThresholds,
    default_thresholds,
    derive_thresholds,
    evaluate_alert,
    format_rules,
    yearly_max_drawdowns,
)

FACTOR_ID = "factor2"
FACTOR_NAME = "因子2-回撤预警"


def factor2_rules(thresholds: DdAlertThresholds | None = None) -> str:
    return format_rules(thresholds)


def factor2_signal(
    *,
    equity: float,
    year_peak: float,
    in_add_zone: bool = False,
    hist_max_dd: float | None = None,
    avg_yearly_max_dd: float | None = None,
    thresholds: DdAlertThresholds | None = None,
    **_: Any,
) -> dict[str, Any]:
    """根据当前回撤给出加仓/减仓预警（不下单）。"""
    th = thresholds
    if th is None:
        th = derive_thresholds(
            hist_max_dd=hist_max_dd,
            avg_yearly_max_dd=avg_yearly_max_dd,
        )
    return evaluate_alert(
        equity=float(equity),
        peak=float(year_peak),
        thresholds=th,
        in_add_zone=bool(in_add_zone),
    )


def calibrate_from_equity(equity: pd.Series) -> DdAlertThresholds:
    """用策略权益曲线重标定因子2阈值。"""
    return derive_thresholds(equity)


def _default_description() -> str:
    th = default_thresholds()
    return (
        f"回撤预警：加仓≥{th.add_alert_dd*100:.0f}% / "
        f"减仓≤{th.reduce_alert_dd*100:.0f}% "
        f"(年均值{th.avg_yearly_max_dd*100:.0f}% / "
        f"历史最大{th.hist_max_dd*100:.0f}%)；回测不注资"
    )


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=_default_description(),
    rules_text=factor2_rules(),
    implemented=True,
    signal=factor2_signal,
    meta={
        "kind": "dd_alert",
        "overlay": False,
        "alert_only": True,
        "hist_max_dd": DEFAULT_HIST_MAX_DD,
        "avg_yearly_max_dd": DEFAULT_AVG_YEARLY_MAX_DD,
        "derive": derive_thresholds,
        "calibrate": calibrate_from_equity,
        "evaluate": evaluate_alert,
        "yearly_max_drawdowns": yearly_max_drawdowns,
        "requires": "account_or_strategy_equity",
        "adjust": "qfq",
        "tunable": ("hist_max_dd", "avg_yearly_max_dd"),
    },
)

register_factor(SPEC)
