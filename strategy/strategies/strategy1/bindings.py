"""援军战法（strategy1）· 因子绑定与策略侧过滤器。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_alert import (
    DEFAULT_AVG_YEARLY_MAX_DD,
    DEFAULT_HIST_MAX_DD,
    default_thresholds,
)
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    entry_filters_ok,
)

STRATEGY_ID = "strategy1"
STRATEGY_NAME = "援军战法"

_TH = default_thresholds()


def strategy1_factor_filter(
    prev_open: float | None = None,
    prev_close: float | None = None,
    prev2_open: float | None = None,
    prev2_close: float | None = None,
    **params: object,
) -> bool:
    mode = str(params.get("prev_entry_mode") or "yin_or_small_yang")
    pct = float(params.get("prev_small_yang_pct") or params.get("entry_pct") or DEFAULT_PCT)
    ban_double = bool(params.get("ban_double_yang", DEFAULT_BAN_DOUBLE_YANG))
    ban_single = bool(params.get("ban_single_yang", DEFAULT_BAN_SINGLE_YANG))
    yang_min = float(params.get("yang_min_pct") or 0.0)
    sec = params.get("double_yang_second_min_pct", None)
    comb = params.get(
        "double_yang_combined_min_pct", DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT
    )
    comb_mode = str(
        params.get("double_yang_combined_mode") or DEFAULT_DOUBLE_YANG_COMBINED_MODE
    )
    smin = params.get("single_yang_min_pct", None)
    return entry_filters_ok(
        prev_open,
        prev_close,
        prev2_open,
        prev2_close,
        entry_pct=pct,
        prev_entry_mode=mode,
        ban_double_yang=ban_double,
        ban_single_yang=ban_single,
        yang_min_pct=yang_min,
        double_yang_second_min_pct=float(sec) if sec is not None else None,
        double_yang_combined_min_pct=float(comb) if comb is not None else None,
        double_yang_combined_mode=comb_mode,
        single_yang_min_pct=float(smin) if smin is not None else None,
    )


FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破主因子",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        prev_small_yang_pct=DEFAULT_PCT,
        prev_entry_mode="yin_or_small_yang",
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
        filter=strategy1_factor_filter,
        filter_desc="前日阴/小阳 + 禁双阳跨日≥5%",
    ),
    bind_factor(
        "factor2",
        label="回撤加减仓预警",
        role="custom",
        hist_max_dd=DEFAULT_HIST_MAX_DD,
        avg_yearly_max_dd=DEFAULT_AVG_YEARLY_MAX_DD,
        add_alert_dd=_TH.add_alert_dd,
        reduce_alert_dd=_TH.reduce_alert_dd,
        overlay=False,
        filter_desc=(
            f"加仓≥{_TH.add_alert_dd*100:.0f}% / 减仓≤{_TH.reduce_alert_dd*100:.0f}% "
            f"(年均值{_TH.avg_yearly_max_dd*100:.0f}% / 历史最大{_TH.hist_max_dd*100:.0f}%)；"
            "回测不注资"
        ),
        enabled=True,
    ),
)
