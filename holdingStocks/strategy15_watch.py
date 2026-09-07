"""策略十五盯盘：T-1 连板情绪 + 震荡市因子25（30m）提示。"""

from __future__ import annotations

from typing import Any

from strategy.ladder_tp import resolve_ladder_tp_policy
from strategy.m30_chop import M30ChopParams, advisory_levels
from strategy.open_break import TICK_SIZE, ceil_to_tick
from strategy3_watch import get_market_sentiment
from watch_config import code_key, strategy_watchlist_codes

_F25 = M30ChopParams()


def build_strategy15_payload(
    *,
    session: str | None,
    strategy1_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sent = get_market_sentiment(session or "")
    policy = resolve_ladder_tp_policy(
        max_height=sent.get("mkt_max_height"),
        ladder_score=sent.get("mkt_ladder_score"),
        lianban=sent.get("mkt_lianban"),
    )
    f25_on = bool(policy.use_factor22)
    pool = strategy_watchlist_codes()
    rows_out: list[dict[str, Any]] = []
    for r in strategy1_rows or []:
        if r.get("error"):
            continue
        if pool and code_key(str(r.get("代码") or "")) not in pool:
            continue
        item = dict(r)
        cost = r.get("成本") or r.get("成交价")
        try:
            cost_f = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_f = None
        stop = r.get("卖出侧价") or r.get("止损")
        try:
            stop_f = float(stop) if stop is not None else None
        except (TypeError, ValueError):
            stop_f = None
        tp_px = None
        trail_arm = None
        if cost_f and cost_f > 0:
            if f25_on:
                trail_arm = round(
                    ceil_to_tick(cost_f * (1.0 + _F25.trail_arm_pct), TICK_SIZE), 3
                )
                tp_px = trail_arm
            else:
                tp_px = round(
                    ceil_to_tick(cost_f * (1.0 + policy.tp_pct), TICK_SIZE), 3
                )
        high = r.get("最高")
        hit_tp = False
        try:
            if tp_px is not None and high is not None and float(high) + 1e-12 >= tp_px:
                hit_tp = True
        except (TypeError, ValueError):
            hit_tp = False
        adv = advisory_levels(cost=cost_f, stop_px=stop_f, sell_px=None, params=_F25)
        item["止盈目标%"] = (
            round(_F25.trail_arm_pct * 100, 1) if f25_on else round(policy.tp_pct * 100, 1)
        )
        item["止盈价"] = tp_px
        item["已触止盈"] = "是" if hit_tp else "否"
        item["因子22"] = "开" if policy.use_factor22 else "关"
        item["因子25"] = "开" if f25_on else "关"
        item["情绪档"] = policy.regime
        item["F25止损确认"] = f"{_F25.stop_confirm_bars}根30m收盘"
        item["F25回补带%"] = round(_F25.reclaim_band * 100, 1)
        if trail_arm is not None:
            item["F25动态臂"] = trail_arm
        item["F25提示"] = (
            f"臂{adv.get('trail_arm_pct', 0):.0%}/回撤{adv.get('trail_giveback_pct', 0):.0%}"
            f"；卖飞±{adv.get('reclaim_band', 0):.1%}"
            if f25_on
            else "高潮·关30m回补"
        )
        note = str(item.get("说明") or "")
        extra = (
            f"S15 {policy.reason}；F22={'开' if policy.use_factor22 else '关'}；"
            f"F25={'开' if f25_on else '关'}"
        )
        item["说明"] = f"{note}；{extra}" if note else extra
        if not policy.use_factor22 and str(item.get("因子侧") or "") == "买入":
            trig = str(item.get("因子触发") or "")
            if "动量" in trig or "再买" in note:
                item["因子侧"] = "空仓"
                item["已触买"] = "否"
                item["说明"] = f"{item['说明']}（高潮梯度·今日禁用F22/F25再买）"
        rows_out.append(item)
    rules = (
        "建仓因子1；止损后是否接回看因子24；"
        + (
            f"震荡·F25：30m×{_F25.stop_confirm_bars}确认止损，"
            f"涨{_F25.trail_arm_pct:.0%}后回撤{_F25.trail_giveback_pct:.0%}半仓，"
            f"卖飞±{_F25.reclaim_band:.1%}回补；"
            if f25_on
            else f"止盈减半目标 {policy.tp_pct:.0%}（因子23×24）；"
        )
        + f"F22={'开' if policy.use_factor22 else '关'}"
    )
    return {
        "sentiment": sent,
        "policy": {
            **policy.as_dict(),
            "use_factor25": f25_on,
            "factor25": _F25.as_dict(),
        },
        "rules": rules,
        "rows": rows_out,
    }
