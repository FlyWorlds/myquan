# -*- coding: utf-8 -*-
"""深度研究：策略16大阳线禁买与波动率的关系。

1. 统计前日阳线标准化实体 (前日日内涨幅 / 20日波动率) 对次日开盘突破收益率的影响分布。
2. 回测对比：
   - 现行基准 (固定个股阈值 2%~3%)
   - 动态波动率门槛: 大阳线 = k * vol20 (k=0.8, 1.0, 1.2, 1.5)
   - 动态ATR门槛: 大阳线 = k * ATR20
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import strategy16_watchlist
from strategy.costs import (
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.data import fetch_daily
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    is_t1_buy_day,
    should_block_entry_by_yang,
)
from strategy.pullback_wave_stop import pullback_stop_price, realized_vol_daily

LOOKBACK_START = "20241201"
END_FETCH = "20261026"
START_EVAL = "2025-01-01"


def compute_atr(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """计算百分比 ATR (真实波幅 / 前收盘)。"""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window).mean()
    atr_pct = atr / df["close"]
    return atr_pct


def run_vol_relation_analysis(stocks: list[dict[str, Any]]):
    """分析：前日阳线实体相对日频波动率倍数 Z = (前日收-开)/开 / vol20，与次日买入盈亏的关系。"""
    records = []

    for s in stocks:
        df = s["daily"].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        closes = df["close"].tolist()

        # 计算 rolling vol20
        vol_list = [None] * len(df)
        for i in range(21, len(df)):
            v = realized_vol_daily(closes[:i], window=20)
            vol_list[i] = v
        df["vol20"] = vol_list

        ep = s["entry_pct"]
        pb = s["pullback_pct"]

        ws = pd.Timestamp(START_EVAL)
        we = pd.Timestamp(END_FETCH)

        for i in range(2, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            prev2 = df.iloc[i - 2]
            day = pd.Timestamp(row["date"]).normalize()
            if not (ws <= day <= we):
                continue

            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            if o <= 0:
                continue

            po, pc = float(prev["open"]), float(prev["close"])
            p_vol = prev["vol20"]
            if p_vol is None or p_vol <= 0:
                continue

            # 仅观察当日触达买点的样本
            open_buy = entry_trigger_price(o, entry_pct=ep, tick=TICK_SIZE)
            if h + 1e-12 < open_buy:
                continue

            # 排除双阳禁买样本，以便纯粹观察单日大阳线效应
            is_dbl = should_block_entry_by_yang(
                float(prev2["open"]), float(prev2["close"]),
                po, pc,
                ban_double_yang=True, ban_single_yang=False,
                double_yang_combined_min_pct=0.05,
            )
            if is_dbl:
                continue

            # 前日如果是阴线或十字星
            body_pct = (pc - po) / po
            z_score = body_pct / p_vol  # 实体相对自身20日日频波动的倍数

            # 模拟该次买入的持有收益 (T+1 峰值回落 2.5% 或在未来几天出局)
            # 简化观测：次日单笔交易真实收益 (按策略16卖出逻辑)
            # 在未来若干天内模拟退出
            holding = True
            peak = max(h, open_buy)
            buy_px = open_buy * (1.0 + SLIP)
            trade_pnl = None
            exit_day = None

            for j in range(i, min(i + 30, len(df))):
                r_j = df.iloc[j]
                oj, hj, lj, cj = float(r_j["open"]), float(r_j["high"]), float(r_j["low"]), float(r_j["close"])
                peak = max(peak, hj)
                stop_px = pullback_stop_price(peak, pullback_pct=pb, tick=TICK_SIZE)
                if j > i and lj <= stop_px + 1e-12:
                    sell_fill = min(oj, stop_px) if oj <= stop_px else stop_px
                    sell_fill *= (1.0 - SLIP)
                    fee = COMMISSION + STAMP
                    trade_pnl = (sell_fill / buy_px - 1.0) - fee
                    exit_day = j - i
                    break

            if trade_pnl is None:
                # 仍持仓则按第30天收盘平仓
                last_c = float(df.iloc[min(i + 29, len(df) - 1)]["close"]) * (1.0 - SLIP)
                trade_pnl = (last_c / buy_px - 1.0) - (COMMISSION + STAMP)
                exit_day = 30

            records.append({
                "code": s["code"],
                "name": s["name"],
                "date": str(day.date()),
                "entry_pct": ep,
                "vol20": p_vol,
                "body_pct": body_pct,
                "z_score": z_score,
                "pnl_pct": trade_pnl * 100.0,
                "is_win": trade_pnl > 0,
                "holding_days": exit_day,
            })

    df_rec = pd.DataFrame(records)
    print(f"共提取 2025-01 至今触买样本: {len(df_rec)} 次")

    # 按 Z-score (前日实体 / 波动率) 分组
    bins = [-999, -0.01, 0.0, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 999]
    labels = [
        "前日阴线 (Z < 0)",
        "前日十字 (Z ≈ 0)",
        "极弱阳 (0 < Z ≤ 0.5σ)",
        "弱小阳 (0.5σ < Z ≤ 0.8σ)",
        "标称小阳 (0.8σ < Z ≤ 1.0σ)",
        "中阳临界 (1.0σ < Z ≤ 1.2σ)",
        "中大阳线 (1.2σ < Z ≤ 1.5σ)",
        "明显大阳 (1.5σ < Z ≤ 2.0σ)",
        "极端大阳 (Z > 2.0σ)",
    ]

    df_rec["z_group"] = pd.cut(df_rec["z_score"], bins=bins, labels=labels)

    grouped = df_rec.groupby("z_group", observed=False).agg(
        样本数=("pnl_pct", "count"),
        单笔均收益=("pnl_pct", "mean"),
        单笔中位数=("pnl_pct", "median"),
        胜率=("is_win", lambda x: np.mean(x) * 100.0),
        平均前日涨幅=("body_pct", lambda x: np.mean(x) * 100.0),
        平均波动率=("vol20", lambda x: np.mean(x) * 100.0),
    ).reset_index()

    print("\n--- 【核心发现：前日阳线波动率倍数 Z 与次日买入期望收益分布】 ---")
    print(grouped.to_string(index=False))

    return df_rec


def simulate_with_vol_gate(
    stocks: list[dict[str, Any]],
    gate_type: str,  # "fixed", "vol_ratio", "atr_ratio"
    param: float,
    start_date: str = "2025-01-01",
    end_date: str = "2026-10-26",
) -> dict[str, Any]:
    """对比不同大阳线过滤机制下的全池个股表现。"""
    ws = pd.Timestamp(start_date)
    we = pd.Timestamp(end_date)
    all_rets = []
    all_trades = 0
    all_blocked = 0
    all_wins = 0

    for s in stocks:
        df = s["daily"].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        closes = df["close"].tolist()

        vol_list = [None] * len(df)
        for i in range(21, len(df)):
            vol_list[i] = realized_vol_daily(closes[:i], window=20)
        df["vol20"] = vol_list

        ep = s["entry_pct"]
        pb = s["pullback_pct"]

        cash = 100_000.0
        shares = 0
        buy_px = 0.0
        buy_day = None
        peak_high = 0.0
        stock_trades = []

        for i in range(2, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            prev2 = df.iloc[i - 2]
            day = pd.Timestamp(row["date"]).normalize()
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            if o <= 0:
                continue

            in_win = ws <= day <= we

            # 卖出
            if shares > 0:
                sess = str(day.date())
                bt = str(buy_day.date()) if buy_day is not None else None
                can_sell = not is_t1_buy_day(bt, sess)
                peak_high = max(peak_high, h)
                stop_px = pullback_stop_price(peak_high, pullback_pct=pb, tick=TICK_SIZE)
                if can_sell and l <= stop_px + 1e-12:
                    sell_fill = min(o, stop_px) if o <= stop_px else stop_px
                    sell_fill *= (1.0 - SLIP)
                    fee = shares * sell_fill * (COMMISSION + STAMP)
                    cash += shares * sell_fill - fee
                    pnl = sell_fill / buy_px - 1.0
                    stock_trades.append(pnl)
                    shares = 0
                    buy_day = None
                    buy_px = 0.0

            # 买入
            if shares == 0 and in_win:
                open_buy = entry_trigger_price(o, entry_pct=ep, tick=TICK_SIZE)
                if h + 1e-12 >= open_buy:
                    po, pc = float(prev["open"]), float(prev["close"])
                    p_vol = prev["vol20"] or 0.025

                    # 计算动态门槛
                    if gate_type == "fixed":
                        d_thr = ep if param == 0 else param
                    elif gate_type == "vol_ratio":
                        d_thr = param * p_vol  # 大阳线门槛 = param * 20日波动率
                    else:
                        d_thr = ep

                    # 判断过门
                    is_yang = pc >= po + TICK_SIZE - 1e-12
                    body = (pc - po) / po if po > 0 else 0.0
                    is_dayang = is_yang and (body >= d_thr - 1e-8)

                    is_dbl = should_block_entry_by_yang(
                        float(prev2["open"]), float(prev2["close"]),
                        po, pc,
                        ban_double_yang=True, ban_single_yang=False,
                        double_yang_combined_min_pct=0.05,
                    )

                    if is_dayang or is_dbl:
                        all_blocked += 1
                    else:
                        px = open_buy * (1.0 + SLIP)
                        raw = math.floor((cash * 0.95) / (px * 100)) * 100
                        if raw >= 100:
                            fee = raw * px * COMMISSION
                            if raw * px + fee <= cash:
                                cash -= raw * px + fee
                                shares = raw
                                buy_px = px
                                buy_day = day
                                peak_high = h

        if shares > 0:
            last_c = float(df.iloc[-1]["close"]) * (1.0 - SLIP)
            fee = shares * last_c * (COMMISSION + STAMP)
            cash += shares * last_c - fee
            stock_trades.append(last_c / buy_px - 1.0)

        tot_ret = (cash / 100_000.0 - 1.0) * 100.0
        all_rets.append(tot_ret)
        all_trades += len(stock_trades)
        all_wins += sum(1 for p in stock_trades if p > 0)

    mean_ret = np.mean(all_rets)
    med_ret = np.median(all_rets)
    pos_ratio = sum(1 for r in all_rets if r > 0) / len(all_rets) * 100.0
    wr = (all_wins / all_trades * 100.0) if all_trades else 0.0

    return {
        "mean_ret": round(mean_ret, 2),
        "med_ret": round(med_ret, 2),
        "pos_ratio": round(pos_ratio, 1),
        "trade_count": all_trades,
        "win_rate": round(wr, 2),
        "blocked_count": all_blocked,
    }


def main():
    pool = strategy16_watchlist()
    stocks = []
    for w in pool:
        code = str(w["code"]).zfill(6)
        sina = str(w.get("sina") or ("sh" if code.startswith(("5", "6", "9")) else "sz") + code).lower()
        name = str(w.get("name") or code)
        ep = float(w.get("entry_pct") or 0.025)
        pb = float(w.get("stop_pct") or 0.025)
        daily = fetch_daily(sina, LOOKBACK_START, END_FETCH)
        if daily is None or daily.empty:
            continue
        stocks.append({
            "code": code,
            "name": name,
            "entry_pct": ep,
            "pullback_pct": pb,
            "daily": daily,
        })

    # 1. 波动率倍数 Z 与买入期望收益分布
    run_vol_relation_analysis(stocks)

    # 2. 对比回测：固定门槛 vs 动态波动率门槛
    print("\n--- 【不同大阳线过滤机制的回测性能对比 (2025-01 ~ 2026-10)】 ---")
    experiments = [
        ("现行固定基准 (各票2%~3%)", "fixed", 0),
        ("固定大阳 = 3.0%", "fixed", 0.03),
        ("固定大阳 = 5.0%", "fixed", 0.05),
        ("波动率自适应 = 0.8 * Vol20 (严过滤)", "vol_ratio", 0.8),
        ("波动率自适应 = 1.0 * Vol20 (1倍标准差)", "vol_ratio", 1.0),
        ("波动率自适应 = 1.2 * Vol20 (中度过滤)", "vol_ratio", 1.2),
        ("波动率自适应 = 1.5 * Vol20 (宽过滤)", "vol_ratio", 1.5),
    ]

    comp_rows = []
    for label, g_type, p_val in experiments:
        res = simulate_with_vol_gate(stocks, gate_type=g_type, param=p_val)
        comp_rows.append({
            "过滤机制方案": label,
            "等权均值收益%": res["mean_ret"],
            "中位数收益%": res["med_ret"],
            "正收益标的比例%": f"{res['pos_ratio']}%",
            "总交易次数": res["trade_count"],
            "胜率%": f"{res['win_rate']}%",
            "被拦截次数": res["blocked_count"],
        })

    print(pd.DataFrame(comp_rows).to_string(index=False))


if __name__ == "__main__":
    main()
