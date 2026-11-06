"""策略三十五·多维空仓避险盯盘服务模块 (Strategy35 Watch Service)。

计算与组装策略三十五的时序数据、实时诊断指标、空仓区间与回测实证数据。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
import numpy as np
import pandas as pd

from strategy.factors.factor35 import (
    DEFAULT_BREADTH_PANIC,
    DEFAULT_EXIT_BREADTH,
    DEFAULT_EXTREME_PANIC,
    DEFAULT_NEW_LOW_PANIC,
    DEFAULT_REBOUND_MA,
    DEFAULT_TREND_MA,
    evaluate_cash_gate,
)

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}


TIER_STEPS_S35 = [
    {"tier": 4, "ratio": 1.0, "pct": "100%", "label": "进攻态", "color": "#10b981", "desc": "指数>MA60 且 广度>50%"},
    {"tier": 3, "ratio": 0.6, "pct": "60%", "label": "减速态", "color": "#f59e0b", "desc": "收复MA20 或 广度35%~50%"},
    {"tier": 2, "ratio": 0.3, "pct": "30%", "label": "防守态", "color": "#f97316", "desc": "破位MA60 且 广度<28%"},
    {"tier": 1, "ratio": 0.0, "pct": "0%", "label": "熔断态", "color": "#ef4444", "desc": "广度<12% 踩踏硬熔断"},
]


def _load_data_and_generate_signals() -> pd.DataFrame:
    """加载中证1000指数日线与全市场广度，生成多维空仓信号时序。"""
    from backtest.research_cash_factor import (
        build_market_breadth,
        generate_cash_signals,
        get_index_data,
    )

    idx_df = get_index_data(symbol="sh000852", name="中证1000")
    br_df = build_market_breadth()

    # 以指数日线为基准进行左连接，补充最新交易日
    df = pd.merge(idx_df, br_df, on="date", how="left").sort_values("date").reset_index(drop=True)
    df["breadth_ma20"] = df["breadth_ma20"].ffill()
    df["breadth_ma60"] = df["breadth_ma60"].ffill()
    df["new_low_ratio"] = df["new_low_ratio"].fillna(0.0)

    # 计算指数均线
    df["ma20"] = df["close"].rolling(DEFAULT_REBOUND_MA).mean()
    df["ma60"] = df["close"].rolling(DEFAULT_TREND_MA).mean()

    # 状态机时序计算
    signal_comp = np.zeros(len(df), dtype=bool)
    pos_comp = np.ones(len(df), dtype=float)
    tier_comp = np.full(len(df), 4, dtype=int)
    in_cash = False
    for i in range(len(df)):
        c = float(df.loc[i, "close"])
        m20 = float(df.loc[i, "ma20"]) if not pd.isna(df.loc[i, "ma20"]) else c
        m60 = float(df.loc[i, "ma60"]) if not pd.isna(df.loc[i, "ma60"]) else c
        b = float(df.loc[i, "breadth_ma20"]) if not pd.isna(df.loc[i, "breadth_ma20"]) else 0.5
        nl = float(df.loc[i, "new_low_ratio"]) if not pd.isna(df.loc[i, "new_low_ratio"]) else 0.0

        gate = evaluate_cash_gate(
            close_price=c,
            ma20=m20,
            ma60=m60,
            market_breadth_ma20=b,
            new_low_ratio=nl,
            current_cash_state=in_cash,
            breadth_panic=DEFAULT_BREADTH_PANIC,
            extreme_panic=DEFAULT_EXTREME_PANIC,
            new_low_panic=DEFAULT_NEW_LOW_PANIC,
            exit_breadth=DEFAULT_EXIT_BREADTH,
        )
        in_cash = gate["is_cash"]
        signal_comp[i] = in_cash
        pos_comp[i] = gate.get("position_ratio", 0.0 if in_cash else 1.0)
        tier_comp[i] = gate.get("tier", 1 if in_cash else 4)

    df["cash_composite"] = signal_comp
    df["position_ratio"] = pos_comp
    df["tier"] = tier_comp
    return df


def get_strategy35_timing_payload(force_refresh: bool = False) -> dict[str, Any]:
    """获取策略三十五的诊断、指标、图表与说明数据。"""
    now_m = time.monotonic()
    if (not force_refresh) and _CACHE["payload"] and (now_m - _CACHE["ts"] < 15.0):
        return _CACHE["payload"]

    try:
        df = _load_data_and_generate_signals()
    except Exception as exc:
        return {
            "error": f"加载大盘择时数据失败: {exc}",
            "current": None,
            "history": [],
        }

    # 提取最近一期数据
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    c = float(latest["close"])
    m20 = float(latest["ma20"])
    m60 = float(latest["ma60"])
    breadth = float(latest["breadth_ma20"])
    nl = float(latest["new_low_ratio"])
    in_cash = bool(latest["cash_composite"])

    # 深度诊断原因
    gate = evaluate_cash_gate(
        close_price=c,
        ma20=m20,
        ma60=m60,
        market_breadth_ma20=breadth,
        new_low_ratio=nl,
        current_cash_state=bool(prev["cash_composite"]),
    )

    macro_broken = c < m60
    breadth_panic = breadth < DEFAULT_BREADTH_PANIC
    extreme_panic = breadth < DEFAULT_EXTREME_PANIC
    new_low_panic = nl > DEFAULT_NEW_LOW_PANIC
    exit_ok = (c > m20) and (breadth > DEFAULT_EXIT_BREADTH)

    tier = gate.get("tier", 1 if in_cash else 4)
    pos_ratio = float(gate.get("position_ratio", 0.0 if in_cash else 1.0))
    tier_name = gate.get("tier_name", "防守态")

    if tier == 1:
        status_label = "【阶梯1·极端熔断】建议绝对清仓避险 (0%仓位)"
        status_tag = "danger"
    elif tier == 2:
        status_label = "【阶梯2·破位防守】建议轻仓谨慎防守 (30%仓位)"
        status_tag = "danger"
    elif tier == 3:
        status_label = "【阶梯3·减速控仓】建议中度控仓运作 (60%仓位)"
        status_tag = "warning"
    else:
        status_label = "【阶梯4·全面进攻】多头共振全速运行 (100%仓位)"
        status_tag = "success"

    breakdown = {
        "macro_trend": {
            "name": f"宏观指数生命线 (MA{DEFAULT_TREND_MA})",
            "current_value": round(c, 2),
            "threshold": round(m60, 2),
            "diff_pct": round((c / m60 - 1.0) * 100.0, 2),
            "status": "破位空头" if macro_broken else "多头强势",
            "ok": not macro_broken,
            "desc": (
                f"收盘价 {c:.1f} 位于 60日生命线 {m60:.1f} 下方 {abs((c/m60-1)*100):.1f}%，处于弱势主跌通道"
                if macro_broken
                else f"收盘价 {c:.1f} 站上 60日生命线 {m60:.1f}，宏观大势稳固"
            ),
        },
        "market_breadth": {
            "name": "全市场广度 (站上20日线比例)",
            "current_value": round(breadth * 100.0, 1),
            "threshold": round(DEFAULT_BREADTH_PANIC * 100.0, 1),
            "status": "溃散警报" if breadth_panic else "良性轮动",
            "ok": not breadth_panic,
            "desc": (
                f"全市场仅 {breadth*100:.1f}% 个股站上20日线 (警戒线 {DEFAULT_BREADTH_PANIC*100:.0f}%)，微观亏钱效应严重"
                if breadth_panic
                else f"全市场 {breadth*100:.1f}% 个股站上20日线，赚钱效应健康"
            ),
        },
        "extreme_panic": {
            "name": "极端流动性熔断线",
            "current_value": round(breadth * 100.0, 1),
            "threshold": round(DEFAULT_EXTREME_PANIC * 100.0, 1),
            "status": "硬熔断触发" if extreme_panic else "缓冲安全",
            "ok": not extreme_panic,
            "desc": (
                f"广度单边跌破 {DEFAULT_EXTREME_PANIC*100:.0f}% 极端熔断线 (如2024年初雪球爆仓)，一票否决强行空仓"
                if extreme_panic
                else f"距离 {DEFAULT_EXTREME_PANIC*100:.0f}% 极端熔断线有缓冲，处于常态防御"
            ),
        },
        "exit_progress": {
            "name": f"右侧解除空仓确认 (MA{DEFAULT_REBOUND_MA} & 广度>{DEFAULT_EXIT_BREADTH*100:.0f}%)",
            "current_index": round(c, 2),
            "index_target": round(m20, 2),
            "index_diff_pct": round((c - m20) / m20 * 100.0, 2) if m20 else 0.0,
            "index_ok": bool(c >= m20),
            "current_breadth": round(breadth * 100.0, 1),
            "breadth_target": round(DEFAULT_EXIT_BREADTH * 100.0, 1),
            "breadth_diff": round(breadth * 100.0 - DEFAULT_EXIT_BREADTH * 100.0, 1),
            "breadth_ok": bool(breadth >= DEFAULT_EXIT_BREADTH),
            "status": "已达成" if exit_ok else "未满足",
            "ok": exit_ok,
            "desc": (
                f"需收复 20日线({m20:.1f}) 且全市场广度回升至 {DEFAULT_EXIT_BREADTH*100:.0f}% 以上方可解除防守"
                if not exit_ok
                else "指数已收复20日线且市场广度恢复，右侧信号确立"
            ),
        },
    }

    # 提取最近 150 个交易日作为图表序列
    chart_df = df.tail(150).copy().reset_index(drop=True)
    history = []
    cash_intervals: list[dict[str, str]] = []
    interval_start: str | None = None

    for idx, row in chart_df.iterrows():
        d = str(row["date"])
        is_c = bool(row["cash_composite"])
        history.append(
            {
                "date": d,
                "close": round(float(row["close"]), 2),
                "ma20": round(float(row["ma20"]), 2) if not pd.isna(row["ma20"]) else None,
                "ma60": round(float(row["ma60"]), 2) if not pd.isna(row["ma60"]) else None,
                "breadth": round(float(row["breadth_ma20"]) * 100.0, 2),
                "new_low": round(float(row["new_low_ratio"]) * 100.0, 2),
                "is_cash": is_c,
            }
        )
        if is_c:
            if interval_start is None:
                interval_start = d
        else:
            if interval_start is not None:
                cash_intervals.append({"start": interval_start, "end": d})
                interval_start = None

    if interval_start is not None:
        cash_intervals.append({"start": interval_start, "end": str(chart_df.iloc[-1]["date"])})

    payload = {
        "updated_at": str(latest["date"]),
        "as_of_clock": f"{latest['date']} 15:00:00",
        "current": {
            "date": str(latest["date"]),
            "is_cash": in_cash,
            "is_cash_mode": in_cash,
            "tier": tier,
            "tier_name": tier_name,
            "position_ratio": pos_ratio,
            "status_label": status_label,
            "status_tag": status_tag,
            "reason": gate["reason"],
            "close": round(c, 2),
            "ma20": round(m20, 2),
            "ma60": round(m60, 2),
            "breadth": round(breadth * 100.0, 2),
            "new_low_ratio": round(nl * 100.0, 2),
            "breakdown": breakdown,
            "tier_steps": TIER_STEPS_S35,
        },
        "thresholds": {
            "trend_ma": DEFAULT_TREND_MA,
            "rebound_ma": DEFAULT_REBOUND_MA,
            "breadth_panic": round(DEFAULT_BREADTH_PANIC * 100.0, 1),
            "extreme_panic": round(DEFAULT_EXTREME_PANIC * 100.0, 1),
            "exit_breadth": round(DEFAULT_EXIT_BREADTH * 100.0, 1),
            "new_low_panic": round(DEFAULT_NEW_LOW_PANIC * 100.0, 1),
        },
        "history": history,
        "cash_intervals": cash_intervals,
        "backtest_summary": {
            "benchmark_dd": "-46.71%",
            "composite_dd": "-33.96%",
            "dd_reduction": "12.75%",
            "oos_benchmark_dd": "-31.20%",
            "oos_composite_dd": "-18.54%",
            "oos_calmar": "0.28 (较基准0.11提升近3倍)",
        },
        "battles": [
            {
                "name": "2022年春 俄乌与封控主跌浪",
                "period": "2022-01-01 ~ 2022-04-26",
                "index_ret": "-31.18%",
                "cash_ret": "-12.13%",
                "alpha": "+19.05%",
                "desc": "指数跌破MA60且广度跌破25%，因子提前进入空仓规避后续20%单边深跌",
            },
            {
                "name": "2024年初 微盘踩踏与雪球爆仓",
                "period": "2024-01-02 ~ 2024-02-08",
                "index_ret": "-14.72% (最大回撤 -26.67%)",
                "cash_ret": "+0.05% (最大回撤 -0.14%)",
                "alpha": "+14.77%",
                "desc": "全市场广度单边跌破12%触碰硬熔断线，期间全现金空仓，以近0回撤平稳穿越",
            },
            {
                "name": "2026年最新下杀防守",
                "period": "2026-01 ~ 2026-11",
                "index_ret": "-20.54% (最大回撤 -31.20%)",
                "cash_ret": "-3.25% (最大回撤 -15.68%)",
                "alpha": "+17.29%",
                "desc": "有效识别今年多轮结构性急跌，空仓防守超额显著",
            },
        ],
        "rules": [
            "1. 宏观防守：大盘指数 (中证1000/全A) 收盘跌破 60日生命线 (Close < MA60)。",
            "2. 微观共振：全市场个股站上 20日均线比例跌破 28%，或 20日新低股票比例超过 15%。",
            "3. 极端硬熔断：全市场站上 20日均线比例跌破 12% 时，一票否决强行空仓 (如2024年初雪球爆仓)。",
            "4. 空仓执行：信号触发次日生效；冻结所有新开仓，持仓根据保护线快速清仓，资金转入现金防守。",
            "5. 右侧解除：指数收复 20日均线 且 全市场广度恢复至 35% 以上方可解除空仓恢复开仓，过滤震荡假突破。",
        ],
    }

    _CACHE["ts"] = now_m
    _CACHE["payload"] = payload
    return payload
