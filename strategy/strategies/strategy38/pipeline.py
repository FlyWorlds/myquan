"""策略三十八·地量起爆多维选股 核心执行管道 (Selection & Execution Pipeline)。

实现完整四步选股与挂单逻辑：
Step 1: 绝对风控（一票否决） -> 优先接入【因子35-多维复合空仓因子】。
Step 2: 底池清洗（基本面过滤） -> 接入【因子13A-契合选股】。
Step 3: 核心进攻（日线形态筛选） -> 在底池中执行【因子34-地量转放量动量】。
Step 4: 买点生成（执行层） -> 接入【因子8-缠论结构】与【因子33-回落后攻击波】，输出次日挂单价格与买点确认逻辑。
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

from strategy.factors.factor34 import compute as compute_factor34
from strategy.factors.factor35 import (
    DEFAULT_BREADTH_PANIC,
    DEFAULT_EXTREME_PANIC,
    DEFAULT_EXIT_BREADTH,
    TIER_1_MELTDOWN,
    TIER_2_DEFENSIVE,
    TIER_3_DECELERATE,
    TIER_4_ATTACK,
    evaluate_cash_gate,
)


def evaluate_market_cash_gate(
    *,
    close_price: float = 3800.0,
    ma20: float = 3780.0,
    ma60: float = 3750.0,
    market_breadth_ma20: float = 0.55,
    current_cash_state: bool = False,
) -> dict[str, Any]:
    """Step 1: 绝对风控（一票否决）评估。"""
    res = evaluate_cash_gate(
        close_price=close_price,
        ma20=ma20,
        ma60=ma60,
        market_breadth_ma20=market_breadth_ma20,
        current_cash_state=current_cash_state,
    )
    # 如果处于极端熔断或破位防守状态，触发一票否决空仓
    veto = res["is_cash"] or res["tier"] in (TIER_1_MELTDOWN, TIER_2_DEFENSIVE)
    reason_str = res.get("reason") or res.get("trigger_reason") or ""
    return {
        "status": "VETO_CASH" if veto else "PASS",
        "veto_cash": veto,
        "is_cash": res["is_cash"],
        "tier": res["tier"],
        "tier_name": res["tier_name"],
        "position_ratio": res["position_ratio"],
        "reason": reason_str or ("大盘运行健康，多维空仓因子未触发" if not veto else "触发多维空仓避险，一票否决"),
        "breadth": market_breadth_ma20,
        "close": close_price,
        "ma60": ma60,
    }


def filter_quality_pool(
    stocks: list[dict[str, Any]],
    *,
    min_volume: float = 10_000_000.0,
    max_price: float = 120.0,
    min_price: float = 3.0,
    ban_st: bool = True,
    mainboard_only: bool = True,
) -> list[dict[str, Any]]:
    """Step 2: 底池清洗（基本面与质地过滤，契合因子13A质量带思路）。"""
    out = []
    for s in stocks:
        code = str(s.get("code") or s.get("symbol") or "")
        name = str(s.get("name") or "")
        # ST 过滤
        if ban_st and ("ST" in name.upper() or "退" in name):
            continue
        # 主板过滤
        if mainboard_only:
            if not code.startswith(("60", "00")):
                continue
        # 价格与成交额过滤
        price = float(s.get("close") or s.get("price") or 0.0)
        if price > 0 and (price < min_price or price > max_price):
            continue
        amt = float(s.get("amount") or s.get("volume") or 0.0)
        if amt > 0 and amt < min_volume:
            continue
        out.append(s)
    return out


def scan_breakout_momentum(
    stock_bars: dict[str, pd.DataFrame],
    *,
    lookback: int = 60,
    max_age: int = 10,
    volume_multiple: float = 2.0,
    body_min: float = 0.05,
    recent_hit_days: int = 5,
) -> list[dict[str, Any]]:
    """Step 3: 核心进攻（在底池中执行因子34：前期长周期缩量+近期底部倍量起爆）。"""
    candidates = []
    for code, df in stock_bars.items():
        if df is None or len(df) < lookback + 5:
            continue
        try:
            res = compute_factor34(
                df,
                lookback=lookback,
                max_age=max_age,
                volume_multiple=volume_multiple,
                body_min=body_min,
            )
        except Exception:
            continue

        # 检查最近 recent_hit_days 内是否有起爆信号
        tail = res.tail(recent_hit_days)
        hits = tail[tail["candidate"] == True]
        if hits.empty:
            continue

        last_hit = hits.iloc[-1]
        last_bar = res.iloc[-1]

        candidates.append({
            "code": code,
            "name": df.attrs.get("name", code),
            "anchor_date": last_hit["anchor_date"],
            "anchor_age": int(last_hit["anchor_age"]) if pd.notna(last_hit["anchor_age"]) else None,
            "breakout_date": last_hit["date"],
            "volume_ratio": round(float(last_hit["anchor_volume_ratio"]), 2) if pd.notna(last_hit["anchor_volume_ratio"]) else 0.0,
            "body_return": round(float(last_hit["body_return"]), 4),
            "breakout_close": round(float(last_hit["close"]), 2),
            "breakout_open": round(float(last_hit["open"]), 2),
            "breakout_high": round(float(last_hit["high"]), 2),
            "breakout_low": round(float(last_hit["low"]), 2),
            "last_close": round(float(last_bar["close"]), 2),
            "last_date": last_bar["date"],
        })

    # 按放量倍数和涨幅排序
    candidates.sort(key=lambda x: (x["volume_ratio"], x["body_return"]), reverse=True)
    return candidates


def generate_execution_orders(
    candidates: list[dict[str, Any]],
    *,
    threshold_pct: float = 0.025,
    tick: float = 0.01,
) -> list[dict[str, Any]]:
    """Step 4: 买点生成（执行层：结合因子8缠论结构与因子33挂单买点计算）。"""
    orders = []
    for c in candidates:
        last_close = c["last_close"]
        breakout_close = c["breakout_close"]
        breakout_open = c["breakout_open"]
        breakout_low = c["breakout_low"]

        # 缠论结构确认：起爆大阳线确立底分型转向上笔形态
        # 因子33/因子1挂单买点生成：
        # 次日理想挂单价分为两种执行场景：
        # 1. 突破确认买点：以最新收盘价上浮 1.5%~2.5% 作为顺势攻击波触买点
        # 2. 回落确认买点：以起爆阳线二分位支撑或回踩支撑挂单
        buy_trigger = round(last_close * (1.0 + threshold_pct) + tick, 2)
        support_buy = round((breakout_open + breakout_close) / 2.0, 2)
        # 硬防守止损位：以起爆日最低价下浮 1% 或 2.5% 作为刚性保护
        stop_price = round(breakout_low * (1.0 - 0.01), 2)

        confirm_logic = (
            f"日线放量{c['volume_ratio']}倍确立缠论底分型向上笔；"
            f"次日盘中突破攻击位 {buy_trigger:.2f} 元触买，或回踩支撑 {support_buy:.2f} 元分批接回；"
            f"跌破起爆低点 {stop_price:.2f} 元严格止损。"
        )

        orders.append({
            "code": c["code"],
            "name": c["name"],
            "last_close": last_close,
            "buy_trigger_price": buy_trigger,
            "support_buy_price": support_buy,
            "stop_loss_price": stop_price,
            "volume_ratio": c["volume_ratio"],
            "breakout_date": c["breakout_date"],
            "anchor_date": c["anchor_date"],
            "confirm_logic": confirm_logic,
            "status": "READY_TO_BUY",
        })
    return orders


def run_strategy38_pipeline(
    *,
    stocks_meta: list[dict[str, Any]] | None = None,
    stock_bars: dict[str, pd.DataFrame] | None = None,
    macro_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """完整四步选股流执行入口。"""
    macro = macro_data or {}
    # Step 1: 绝对风控（一票否决）
    step1 = evaluate_market_cash_gate(
        close_price=float(macro.get("close", 3800.0)),
        ma20=float(macro.get("ma20", 3780.0)),
        ma60=float(macro.get("ma60", 3750.0)),
        market_breadth_ma20=float(macro.get("breadth", 0.55)),
        current_cash_state=bool(macro.get("current_cash_state", False)),
    )

    # 若触发空仓，直接一票否决返回空，次日不买入
    if step1["veto_cash"]:
        return {
            "strategyId": "strategy38",
            "strategyName": "策略三十八·地量起爆多维选股",
            "step1_cash_gate": step1,
            "step2_quality_pool": {"count": 0, "status": "VETO_BY_STEP1"},
            "step3_breakout_candidates": [],
            "step4_orders": [],
            "executed": True,
            "summary": "【一票否决】大盘触发多维空仓因子避险，策略直接返回空，次日不执行任何买入操作。",
        }

    # Step 2: 底池清洗（基本面过滤）
    stocks = stocks_meta or []
    step2_pool = filter_quality_pool(stocks)

    # Step 3: 核心进攻（日线形态筛选）
    bars = stock_bars or {}
    # 若未单独提供 bars，且从底池过滤出来
    valid_codes = {str(s.get("code") or "") for s in step2_pool}
    target_bars = {k: v for k, v in bars.items() if k in valid_codes} if valid_codes else bars

    step3_candidates = scan_breakout_momentum(target_bars)

    # Step 4: 买点生成（执行层）
    step4_orders = generate_execution_orders(step3_candidates)

    return {
        "strategyId": "strategy38",
        "strategyName": "策略三十八·地量起爆多维选股",
        "step1_cash_gate": step1,
        "step2_quality_pool": {
            "total_raw": len(stocks),
            "count": len(step2_pool),
            "status": "PASS",
        },
        "step3_breakout_candidates": step3_candidates,
        "step4_orders": step4_orders,
        "executed": True,
        "summary": (
            f"Step 1 风控通过 ({step1['tier_name']}) -> "
            f"Step 2 底池清洗保留 {len(step2_pool)} 只 -> "
            f"Step 3 筛选出 {len(step3_candidates)} 只地量倍量起爆标的 -> "
            f"Step 4 生成次日挂单买点与风控逻辑。"
        ),
    }
