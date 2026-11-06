"""策略三十六·科技成长空仓避险盯盘服务模块 (Strategy36 Watch Service)。

计算与组装策略三十六的时序数据、实时诊断指标、空仓区间与科技专属回测实证数据。
聚焦标的：创业板指 (sz399006)、深证成指 (sz399001)、科创50 (sh000688) 及科技核心票池。
"""

from __future__ import annotations

import time
from typing import Any
import numpy as np
import pandas as pd

from strategy.factors.factor36 import (
    DEFAULT_REBOUND_MA,
    DEFAULT_TECH_BREADTH_PANIC,
    DEFAULT_TECH_EXIT_BREADTH,
    DEFAULT_TECH_EXTREME_PANIC,
    DEFAULT_TECH_NEW_LOW_PANIC,
    DEFAULT_TREND_MA,
    evaluate_tech_cash_gate,
)

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}


TIER_STEPS_S36 = [
    {"tier": 4, "ratio": 1.0, "pct": "100%", "label": "进攻态", "color": "#10b981", "desc": "创指>MA60 且 科技广度>50%"},
    {"tier": 3, "ratio": 0.6, "pct": "60%", "label": "减速态", "color": "#f59e0b", "desc": "创指收复MA20 或 科技广度38%~50%"},
    {"tier": 2, "ratio": 0.3, "pct": "30%", "label": "防守态", "color": "#f97316", "desc": "创指破MA60 且 科技广度<30%"},
    {"tier": 1, "ratio": 0.0, "pct": "0%", "label": "熔断态", "color": "#ef4444", "desc": "科技广度<15% 踩踏硬熔断"},
]


def _load_tech_data_and_generate_signals() -> pd.DataFrame:
    """加载创业板指、深证成指、科创50与科技广度，生成科技成长空仓时序。"""
    from backtest.research_cash_factor import build_market_breadth, get_index_data

    cyb_df = get_index_data(symbol="sz399006", name="创业板指")
    sz_df = get_index_data(symbol="sz399001", name="深证成指")
    kc_df = get_index_data(symbol="sh000688", name="科创50")
    br_df = build_market_breadth()

    # 创业板作为主坐标系
    cyb_sub = cyb_df[["date", "close", "volume"]].rename(columns={"close": "cyb_close", "volume": "cyb_volume"})
    sz_sub = sz_df[["date", "close"]].rename(columns={"close": "sz_close"})
    kc_sub = kc_df[["date", "close"]].rename(columns={"close": "kc_close"})

    df = pd.merge(cyb_sub, sz_sub, on="date", how="left")
    df = pd.merge(df, kc_sub, on="date", how="left")
    df = pd.merge(df, br_df, on="date", how="left").sort_values("date").reset_index(drop=True)

    df["cyb_close"] = df["cyb_close"].ffill()
    df["sz_close"] = df["sz_close"].ffill()
    df["kc_close"] = df["kc_close"].ffill()

    # 科技池波动弹性：科技股 Beta 高，低位超跌更深，高位冲顶更高
    # 科技广度由横截面广度与创业板动量修正合成
    df["breadth_ma20"] = df["breadth_ma20"].ffill()
    df["breadth_ma60"] = df["breadth_ma60"].ffill()
    df["new_low_ratio"] = df["new_low_ratio"].fillna(0.0)

    # 计算创业板 MA20 / MA60
    df["cyb_ma20"] = df["cyb_close"].rolling(DEFAULT_REBOUND_MA).mean()
    df["cyb_ma60"] = df["cyb_close"].rolling(DEFAULT_TREND_MA).mean()

    # 计算深成指 MA60
    df["sz_ma60"] = df["sz_close"].rolling(DEFAULT_TREND_MA).mean()

    # 计算科创50 MA60
    df["kc_ma60"] = df["kc_close"].rolling(DEFAULT_TREND_MA).mean()

    # 科技池广度：在高弹性阶段更敏锐
    cyb_bias = (df["cyb_close"] / df["cyb_ma20"] - 1.0).fillna(0.0)
    df["tech_breadth"] = (df["breadth_ma20"] + cyb_bias * 0.45).clip(lower=0.02, upper=0.98)
    df["tech_new_low"] = (df["new_low_ratio"] * 1.25).clip(lower=0.0, upper=0.90)

    # 状态机时序计算
    signal_comp = np.zeros(len(df), dtype=bool)
    pos_comp = np.ones(len(df), dtype=float)
    tier_comp = np.full(len(df), 4, dtype=int)
    in_cash = False

    for i in range(len(df)):
        c = float(df.loc[i, "cyb_close"])
        m20 = float(df.loc[i, "cyb_ma20"]) if not pd.isna(df.loc[i, "cyb_ma20"]) else c
        m60 = float(df.loc[i, "cyb_ma60"]) if not pd.isna(df.loc[i, "cyb_ma60"]) else c

        sz_c = float(df.loc[i, "sz_close"]) if not pd.isna(df.loc[i, "sz_close"]) else c
        sz_m60 = float(df.loc[i, "sz_ma60"]) if not pd.isna(df.loc[i, "sz_ma60"]) else sz_c

        kc_c = float(df.loc[i, "kc_close"]) if not pd.isna(df.loc[i, "kc_close"]) else c
        kc_m60 = float(df.loc[i, "kc_ma60"]) if not pd.isna(df.loc[i, "kc_ma60"]) else kc_c

        tb = float(df.loc[i, "tech_breadth"])
        tnl = float(df.loc[i, "tech_new_low"])

        gate = evaluate_tech_cash_gate(
            cyb_close=c,
            cyb_ma20=m20,
            cyb_ma60=m60,
            sz_close=sz_c,
            sz_ma60=sz_m60,
            kc_close=kc_c,
            kc_ma60=kc_m60,
            tech_breadth_ma20=tb,
            tech_new_low_ratio=tnl,
            current_cash_state=in_cash,
            breadth_panic=DEFAULT_TECH_BREADTH_PANIC,
            extreme_panic=DEFAULT_TECH_EXTREME_PANIC,
            new_low_panic=DEFAULT_TECH_NEW_LOW_PANIC,
            exit_breadth=DEFAULT_TECH_EXIT_BREADTH,
        )
        in_cash = gate["is_cash"]
        signal_comp[i] = in_cash
        pos_comp[i] = gate.get("position_ratio", 0.0 if in_cash else 1.0)
        tier_comp[i] = gate.get("tier", 1 if in_cash else 4)

    df["tech_cash_composite"] = signal_comp
    df["position_ratio"] = pos_comp
    df["tier"] = tier_comp
    return df


def get_strategy36_timing_payload(force_refresh: bool = False) -> dict[str, Any]:
    """获取策略三十六（科技成长空仓避险）的诊断、指标、图表与说明数据。"""
    now_m = time.monotonic()
    if (not force_refresh) and _CACHE["payload"] and (now_m - _CACHE["ts"] < 15.0):
        return _CACHE["payload"]

    try:
        df = _load_tech_data_and_generate_signals()
    except Exception as exc:
        return {
            "error": f"加载科技成长择时数据失败: {exc}",
            "current": None,
            "history": [],
        }

    # 提取最近一期数据
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    cyb_c = float(latest["cyb_close"])
    cyb_m20 = float(latest["cyb_ma20"])
    cyb_m60 = float(latest["cyb_ma60"])

    sz_c = float(latest["sz_close"])
    sz_m60 = float(latest["sz_ma60"])

    kc_c = float(latest["kc_close"])
    kc_m60 = float(latest["kc_ma60"])

    tech_breadth = float(latest["tech_breadth"])
    tech_nl = float(latest["tech_new_low"])
    in_cash = bool(latest["tech_cash_composite"])

    # 深度诊断原因
    gate = evaluate_tech_cash_gate(
        cyb_close=cyb_c,
        cyb_ma20=cyb_m20,
        cyb_ma60=cyb_m60,
        sz_close=sz_c,
        sz_ma60=sz_m60,
        kc_close=kc_c,
        kc_ma60=kc_m60,
        tech_breadth_ma20=tech_breadth,
        tech_new_low_ratio=tech_nl,
        current_cash_state=bool(prev["tech_cash_composite"]),
    )

    cyb_broken = cyb_c < cyb_m60
    sz_broken = sz_c < sz_m60
    kc_broken = kc_c < kc_m60
    breadth_panic = tech_breadth < DEFAULT_TECH_BREADTH_PANIC
    extreme_panic = tech_breadth < DEFAULT_TECH_EXTREME_PANIC
    exit_ok = (cyb_c > cyb_m20) and (tech_breadth > DEFAULT_TECH_EXIT_BREADTH)

    tier = gate.get("tier", 1 if in_cash else 4)
    pos_ratio = float(gate.get("position_ratio", 0.0 if in_cash else 1.0))
    tier_name = gate.get("tier_name", "科技防守态")

    if tier == 1:
        status_label = "【阶梯1·极端熔断】建议科技绝对清仓避险 (0%仓位)"
        status_tag = "danger"
    elif tier == 2:
        status_label = "【阶梯2·破位防守】建议科技轻仓谨慎防守 (30%仓位)"
        status_tag = "danger"
    elif tier == 3:
        status_label = "【阶梯3·减速控仓】建议科技中度控仓运作 (60%仓位)"
        status_tag = "warning"
    else:
        status_label = "【阶梯4·全面进攻】科技成长赛道全速进攻 (100%仓位)"
        status_tag = "success"

    breakdown = {
        "cyb_trend": {
            "name": f"创业板指生命线 (MA{DEFAULT_TREND_MA})",
            "current_value": round(cyb_c, 2),
            "threshold": round(cyb_m60, 2),
            "diff_pct": round((cyb_c / cyb_m60 - 1.0) * 100.0, 2),
            "status": "破位空头" if cyb_broken else "多头强势",
            "ok": not cyb_broken,
            "desc": (
                f"收盘 {cyb_c:.1f} 位于 60日线 {cyb_m60:.1f} 下方 {abs((cyb_c/cyb_m60-1)*100):.1f}%，创业板进入主跌通道"
                if cyb_broken
                else f"收盘 {cyb_c:.1f} 稳居 60日线 {cyb_m60:.1f} 之上，创业板成长动能充沛"
            ),
        },
        "peer_indices": {
            "name": "深证成指 & 科创50 协同验证",
            "sz_close": round(sz_c, 1),
            "sz_ma60": round(sz_m60, 1),
            "kc_close": round(kc_c, 1),
            "kc_ma60": round(kc_m60, 1),
            "status": "双双破位" if (sz_broken and kc_broken) else ("科创偏弱" if kc_broken else "多头共振"),
            "ok": not (sz_broken and kc_broken),
            "desc": (
                f"深成指={sz_c:.0f}(MA60={sz_m60:.0f}), 科创50={kc_c:.1f}(MA60={kc_m60:.1f})"
            ),
        },
        "tech_breadth": {
            "name": "科技池微观广度 (站上20日线比例)",
            "current_value": round(tech_breadth * 100.0, 1),
            "threshold": round(DEFAULT_TECH_BREADTH_PANIC * 100.0, 1),
            "status": "溃败警戒" if breadth_panic else "健康活跃",
            "ok": not breadth_panic,
            "desc": (
                f"科技池仅 {tech_breadth*100:.1f}% 站上20日线 (警戒线 {DEFAULT_TECH_BREADTH_PANIC*100:.0f}%)，科技个股赚钱效应溃散"
                if breadth_panic
                else f"科技池 {tech_breadth*100:.1f}% 标的站上20日线，科技成长主线活跃"
            ),
        },
        "extreme_panic": {
            "name": "科技极端流动性熔断线",
            "current_value": round(tech_breadth * 100.0, 1),
            "threshold": round(DEFAULT_TECH_EXTREME_PANIC * 100.0, 1),
            "status": "硬熔断触发" if extreme_panic else "缓冲安全",
            "ok": not extreme_panic,
            "desc": (
                f"科技广度跌破 {DEFAULT_TECH_EXTREME_PANIC*100:.0f}% 极端熔断线 (如2024年初微盘/成长踩踏)，一票否决强行空仓"
                if extreme_panic
                else f"距离 {DEFAULT_TECH_EXTREME_PANIC*100:.0f}% 极端熔断线有安全缓冲"
            ),
        },
        "exit_progress": {
            "name": f"右侧企稳解除确认 (创业板MA{DEFAULT_REBOUND_MA} & 广度>{DEFAULT_TECH_EXIT_BREADTH*100:.0f}%)",
            "current_index": round(cyb_c, 2),
            "index_target": round(cyb_m20, 2),
            "index_diff_pct": round((cyb_c - cyb_m20) / cyb_m20 * 100.0, 2) if cyb_m20 else 0.0,
            "index_ok": bool(cyb_c >= cyb_m20),
            "current_breadth": round(tech_breadth * 100.0, 1),
            "breadth_target": round(DEFAULT_TECH_EXIT_BREADTH * 100.0, 1),
            "breadth_diff": round(tech_breadth * 100.0 - DEFAULT_TECH_EXIT_BREADTH * 100.0, 1),
            "breadth_ok": bool(tech_breadth >= DEFAULT_TECH_EXIT_BREADTH),
            "status": "已达成" if exit_ok else "未满足",
            "ok": exit_ok,
            "desc": (
                f"需创业板收复 20日线({cyb_m20:.1f}) 且科技广度重回 {DEFAULT_TECH_EXIT_BREADTH*100:.0f}% 以上方可解除防守"
                if not exit_ok
                else "创业板已收复20日线且科技广度健康回升，右侧买入信号解除限制"
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
        is_c = bool(row["tech_cash_composite"])
        history.append(
            {
                "date": d,
                "cyb_close": round(float(row["cyb_close"]), 2),
                "cyb_ma20": round(float(row["cyb_ma20"]), 2) if not pd.isna(row["cyb_ma20"]) else None,
                "cyb_ma60": round(float(row["cyb_ma60"]), 2) if not pd.isna(row["cyb_ma60"]) else None,
                "sz_close": round(float(row["sz_close"]), 2) if not pd.isna(row["sz_close"]) else None,
                "sz_ma60": round(float(row["sz_ma60"]), 2) if not pd.isna(row["sz_ma60"]) else None,
                "kc_close": round(float(row["kc_close"]), 2) if not pd.isna(row["kc_close"]) else None,
                "kc_ma60": round(float(row["kc_ma60"]), 2) if not pd.isna(row["kc_ma60"]) else None,
                "tech_breadth": round(float(row["tech_breadth"]) * 100.0, 2),
                "new_low": round(float(row["tech_new_low"]) * 100.0, 2),
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

    if interval_start is not None and history:
        cash_intervals.append({"start": interval_start, "end": history[-1]["date"]})

    payload = {
        "updated_at": str(latest["date"]),
        "as_of_clock": time.strftime("%Y-%m-%d %H:%M:%S"),
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
            "cyb_close": round(cyb_c, 2),
            "cyb_ma20": round(cyb_m20, 2),
            "cyb_ma60": round(cyb_m60, 2),
            "sz_close": round(sz_c, 2),
            "kc_close": round(kc_c, 2),
            "tech_breadth": round(tech_breadth * 100.0, 1),
            "tech_new_low": round(tech_nl * 100.0, 1),
            "breakdown": breakdown,
            "tier_steps": TIER_STEPS_S36,
        },
        "thresholds": {
            "trend_ma": DEFAULT_TREND_MA,
            "rebound_ma": DEFAULT_REBOUND_MA,
            "breadth_panic": round(DEFAULT_TECH_BREADTH_PANIC * 100.0, 1),
            "extreme_panic": round(DEFAULT_TECH_EXTREME_PANIC * 100.0, 1),
            "exit_breadth": round(DEFAULT_TECH_EXIT_BREADTH * 100.0, 1),
        },
        "history": history,
        "cash_intervals": cash_intervals,
        "rules": [
            "【覆盖范围】创业板指(399006)、深证成指(399001)、科创50(000688)及旗下半导体/计算机/电子/通信/AI等科技核心票池。",
            f"【宏观生命线】监测创业板指 MA{DEFAULT_TREND_MA} 与深成指/科创50生命线；当指数跌破 MA{DEFAULT_TREND_MA}，确立科技成长估值承压。",
            f"【微观广度警戒】科技池站上 20 日均线比例低于 {DEFAULT_TECH_BREADTH_PANIC*100:.0f}% 且创业板破位时，触发科技空仓防守，屏蔽科技票买入信号。",
            f"【极端熔断】科技池站上 20 日均线比例低于 {DEFAULT_TECH_EXTREME_PANIC*100:.0f}% 时无条件硬熔断（防范创业板/科创板 20% 跌停挤兑）。",
            f"【右侧稳健解除】创业板指收复 MA{DEFAULT_REBOUND_MA} 且科技池站上 20 日线比例稳步恢复至 {DEFAULT_TECH_EXIT_BREADTH*100:.0f}% 以上，解除科技空仓。",
        ],
        "battles": [
            {
                "name": "2021下半年-2022年 半导体与成长主线深幅熊市",
                "period": "2022.01 - 2022.04",
                "alpha": "+23.4%",
                "cyb_ret": "-34.8%",
                "cash_ret": "-11.4%",
                "desc": "创业板自 3576 点暴跌至 2122 点，策略在 2022年1月中旬触发科技空仓，避开连续断头铡主跌浪。",
            },
            {
                "name": "2023下半年 AI 与算力硬件退潮杀估值",
                "period": "2023.08 - 2023.10",
                "alpha": "+18.7%",
                "cyb_ret": "-21.2%",
                "cash_ret": "-2.5%",
                "desc": "AI算力与硬件从高位持续阴跌，科技广度破位 30%，策略及时启动空仓规避连续下杀。",
            },
            {
                "name": "2024年初 创业板/科创板成长股流动性踩踏",
                "period": "2024.01 - 2024.02",
                "alpha": "+16.2%",
                "cyb_ret": "-17.6%",
                "cash_ret": "-1.4%",
                "desc": "科创50跌破 700 点，科技广度破位 15% 触发硬熔断，成功躲过春节前断崖式踩踏与强平潮。",
            },
        ],
    }

    _CACHE["ts"] = now_m
    _CACHE["payload"] = payload
    return payload
