"""因子2 真源（预警版）：按策略回撤统计触发加仓/减仓预警。

设计要点：
  · 回测不注资、不改权益曲线，只根据历史回撤统计标定阈值
  · 加仓预警：接近「历史最大回撤取整档」，但留出与历史极值的缓冲
  · 减仓预警：曾进入加仓区后，回撤收窄到「年最大回撤均值」附近时提示减仓/兑现
  · 盯盘侧只报警，不自动改现金

阈值推导（可用任意策略权益曲线标定）：
  · hist_max_dd = 全程最大回撤
  · avg_yearly_max_dd = 各自然年最大回撤的平均值
  · add_alert = 将 hist_max_dd 向 10% 网格下取整（例 26%→20%）
  · 若与 hist_max 缓冲不足 MIN_GAP，再下调一档 10%
  · reduce_alert = 将 avg_yearly_max_dd 向 5% 网格下取整后再减 5%
    （例均值≈19%→15%→减仓线 10%）
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

# 网格与缓冲（开闭：只改这里）
GRID_ADD = 0.10          # 加仓线按 10% 取整
GRID_REDUCE = 0.05       # 减仓相关按 5% 取整
MIN_GAP_TO_MAX = 0.05    # 加仓线相对历史最大回撤至少留 5%
DEFAULT_REDUCE_EXTRA = 0.05  # 减仓线 = floor5(年均值) - 5%

# 半仓天通+凯盛（策略一、无叠加）经验默认；可用权益曲线重算覆盖
DEFAULT_HIST_MAX_DD = 0.26
DEFAULT_AVG_YEARLY_MAX_DD = 0.19


def drawdown(equity: float, peak: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, 1.0 - float(equity) / float(peak))


def floor_to_grid(x: float, grid: float) -> float:
    if grid <= 0:
        raise ValueError("grid must be > 0")
    x = abs(float(x))
    return math.floor(x / grid + 1e-12) * grid


def max_drawdown_pct(equity: pd.Series) -> float:
    eq = equity.dropna().sort_index()
    if eq.empty:
        return 0.0
    return float((1.0 - eq / eq.cummax()).max())


def yearly_max_drawdowns(equity: pd.Series) -> pd.Series:
    eq = equity.dropna().sort_index()
    if eq.empty:
        return pd.Series(dtype=float)
    if getattr(eq.index, "tz", None) is not None:
        years = eq.index.tz_convert("Asia/Shanghai").year
    else:
        years = eq.index.year
    out: dict[int, float] = {}
    for y, part in eq.groupby(years):
        out[int(y)] = max_drawdown_pct(part)
    return pd.Series(out).sort_index()


@dataclass(frozen=True)
class DdAlertThresholds:
    hist_max_dd: float
    avg_yearly_max_dd: float
    add_alert_dd: float
    reduce_alert_dd: float
    min_gap_to_max: float = MIN_GAP_TO_MAX

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}

    def label(self) -> str:
        return (
            f"加仓≥{self.add_alert_dd*100:.0f}% / "
            f"减仓≤{self.reduce_alert_dd*100:.0f}% / "
            f"年均值{self.avg_yearly_max_dd*100:.1f}% / "
            f"历史最大{self.hist_max_dd*100:.1f}%"
        )


def derive_thresholds(
    equity: pd.Series | None = None,
    *,
    hist_max_dd: float | None = None,
    avg_yearly_max_dd: float | None = None,
) -> DdAlertThresholds:
    """由权益曲线或显式统计值推导预警阈值。"""
    if equity is not None and len(equity):
        hist = max_drawdown_pct(equity)
        y = yearly_max_drawdowns(equity)
        avg = float(y.mean()) if len(y) else hist
    else:
        hist = float(
            DEFAULT_HIST_MAX_DD if hist_max_dd is None else hist_max_dd
        )
        avg = float(
            DEFAULT_AVG_YEARLY_MAX_DD
            if avg_yearly_max_dd is None
            else avg_yearly_max_dd
        )

    hist = abs(float(hist))
    avg = abs(float(avg))
    add = floor_to_grid(hist, GRID_ADD)
    # 与历史最大回撤缓冲不足则再降一档
    while add > 0 and hist - add < MIN_GAP_TO_MAX - 1e-12:
        add = max(0.0, add - GRID_ADD)
    # 加仓线不应高于/等于历史最大
    if add >= hist - 1e-12:
        add = max(0.0, floor_to_grid(hist - MIN_GAP_TO_MAX, GRID_ADD))

    # 减仓线：落在年均值下方一档，避免贴着历史极值操作
    reduce = floor_to_grid(avg, GRID_REDUCE) - DEFAULT_REDUCE_EXTRA
    reduce = max(GRID_REDUCE, reduce)  # 至少 5%
    if reduce >= add - 1e-12:
        reduce = max(GRID_REDUCE, add - GRID_REDUCE)

    return DdAlertThresholds(
        hist_max_dd=hist,
        avg_yearly_max_dd=avg,
        add_alert_dd=add,
        reduce_alert_dd=reduce,
        min_gap_to_max=MIN_GAP_TO_MAX,
    )


def default_thresholds() -> DdAlertThresholds:
    return derive_thresholds(
        hist_max_dd=DEFAULT_HIST_MAX_DD,
        avg_yearly_max_dd=DEFAULT_AVG_YEARLY_MAX_DD,
    )


def evaluate_alert(
    *,
    equity: float,
    peak: float,
    thresholds: DdAlertThresholds | None = None,
    in_add_zone: bool = False,
) -> dict[str, Any]:
    """根据当前回撤给出预警动作（不下单）。

    返回 action:
      · add_alert    加仓预警
      · reduce_alert 减仓预警（曾处加仓区，现已收窄到减仓线）
      · hold         观望
      · near_max     接近/超过历史最大回撤（不再鼓励加仓）
    """
    th = thresholds or default_thresholds()
    dd = drawdown(float(equity), float(peak))
    gap_to_max = th.hist_max_dd - dd

    if dd + 1e-12 >= th.hist_max_dd - 0.01:
        action = "near_max"
        note = (
            f"回撤{dd*100:.1f}% 已接近历史最大"
            f"{th.hist_max_dd*100:.1f}%，不宜继续加仓"
        )
    elif dd + 1e-12 >= th.add_alert_dd:
        action = "add_alert"
        note = (
            f"回撤{dd*100:.1f}%≥加仓线{th.add_alert_dd*100:.0f}%"
            f"（历史最大{th.hist_max_dd*100:.1f}%取整），可考虑加仓"
        )
    elif in_add_zone and dd <= th.reduce_alert_dd + 1e-12:
        action = "reduce_alert"
        note = (
            f"已从加仓区收窄至{dd*100:.1f}%≤减仓线"
            f"{th.reduce_alert_dd*100:.0f}%（年均值"
            f"{th.avg_yearly_max_dd*100:.1f}%附近），可考虑减仓/兑现"
        )
    else:
        action = "hold"
        note = (
            f"回撤{dd*100:.1f}% 观望（加仓≥{th.add_alert_dd*100:.0f}% / "
            f"减仓≤{th.reduce_alert_dd*100:.0f}%）"
        )

    return {
        "action": action,
        "dd": dd,
        "dd_pct": dd * 100.0,
        "gap_to_max_pct": gap_to_max * 100.0,
        "in_add_zone": bool(
            in_add_zone or action == "add_alert" or action == "near_max"
        ),
        "alert": note,
        "thresholds": th.as_dict(),
        "label": th.label(),
    }


def format_rules(thresholds: DdAlertThresholds | None = None) -> str:
    th = thresholds or default_thresholds()
    return "\n".join(
        [
            "================================================================================",
            "  因子2 — 回撤预警（加仓/减仓提示，回测不介入权益）",
            "================================================================================",
            "",
            "【作用】",
            "  用策略历史回撤统计标定阈值；盯盘触发加仓/减仓预警。",
            "  不改变买卖点，回测默认不注资、不叠加权益。",
            "",
            "【当前阈值】",
            f"  · 历史最大回撤: {th.hist_max_dd*100:.2f}%",
            f"  · 年最大回撤均值: {th.avg_yearly_max_dd*100:.2f}%",
            f"  · 加仓预警线: ≥{th.add_alert_dd*100:.0f}%  "
            f"(历史最大向{GRID_ADD*100:.0f}%下取整，且距极值≥{MIN_GAP_TO_MAX*100:.0f}%)",
            f"  · 减仓预警线: ≤{th.reduce_alert_dd*100:.0f}%  "
            f"(由年均值推导；须曾进入加仓区后收窄才触发)",
            f"  · 接近历史最大: 不宜继续加仓",
            "",
            "【说明】",
            "  · 可用策略权益曲线 derive_thresholds(equity) 重标定",
            "  · 半仓天通+凯盛默认见 DEFAULT_HIST_MAX_DD / DEFAULT_AVG_YEARLY_MAX_DD",
            "================================================================================",
        ]
    )


RULES_TEXT = format_rules()
