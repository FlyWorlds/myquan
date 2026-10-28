# -*- coding: utf-8 -*-
"""实证研究：前一日过门，看「阳线涨幅」还是「阳线实体」更好？

脱离具体策略买卖点，全市场大样本（1,000+只股票，2023-2026年数十万个交易日样本）
直接统计前日不同【实体涨幅】与【全天涨幅】对次日表现的影响：
  1. 次日开盘到收盘涨跌幅 (日内收益)
  2. 次日冲高幅度 (high/open - 1)
  3. 次日日内破位/下杀概率 (low/open - 1 <= -2.5%)
  4. 次日高开低走/收阴概率 (close < open)
  5. 2x2 控制变量对比 (高开小实体 vs 低开大实体)
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
DATA_CACHE = _ROOT / "data_cache"


def run_research():
    files = list(DATA_CACHE.glob("*_daily_qfq.parquet"))
    print(f"找到缓存日线数据文件: {len(files)} 个")

    # 抽取 800 只股票做全量分析 (保证统计效力与运行速度)
    selected_files = files[:800]

    all_records = []

    for f in selected_files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if df is None or len(df) < 60:
            continue

        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        # 限制在 2023-01-01 至 2026-10-26
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df[df["date"] >= pd.Timestamp("2023-01-01")].reset_index(drop=True)
        if len(df) < 30:
            continue

        o = df["open"].to_numpy(dtype=float)
        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        c = df["close"].to_numpy(dtype=float)

        n = len(df)
        for i in range(1, n - 1):
            prev_o, prev_h, prev_l, prev_c = o[i - 1], h[i - 1], l[i - 1], c[i - 1]
            prev2_c = c[i - 2] if i >= 2 else prev_o

            # 前一日必须是阳线 (收盘 > 开盘 + 0.01)
            if prev_c < prev_o + 0.01 - 1e-9 or prev_o <= 0:
                continue

            # 前日实体涨幅 (日内推动幅度)
            prev_body_pct = (prev_c - prev_o) / prev_o

            # 前日全天涨幅 (相对前前日收盘，包含跳空)
            prev_tot_pct = (prev_c - prev2_c) / prev2_c if prev2_c > 0 else prev_body_pct

            # 前日开盘跳空幅度
            prev_gap_pct = (prev_o - prev2_c) / prev2_c if prev2_c > 0 else 0.0

            # 次日 (第 i 日) 表现
            curr_o, curr_h, curr_l, curr_c = o[i], h[i], l[i], c[i]
            if curr_o <= 0:
                continue

            next_intra_ret = (curr_c - curr_o) / curr_o         # 次日日内收益 (开盘买，收盘平)
            next_max_up = (curr_h - curr_o) / curr_o            # 次日冲高空间
            next_max_down = (curr_l - curr_o) / curr_o          # 次日最大下杀
            next_is_yin = curr_c < curr_o - 1e-9                # 次日是否收阴 (高开低走/冲高回落)
            next_hit_stop25 = next_max_down <= -0.025           # 次日是否跌破开盘-2.5% (触止损)

            all_records.append({
                "prev_body_pct": prev_body_pct * 100.0,
                "prev_tot_pct": prev_tot_pct * 100.0,
                "prev_gap_pct": prev_gap_pct * 100.0,
                "next_intra_ret": next_intra_ret * 100.0,
                "next_max_up": next_max_up * 100.0,
                "next_max_down": next_max_down * 100.0,
                "next_is_yin": next_is_yin,
                "next_hit_stop25": next_hit_stop25,
            })

    data = pd.DataFrame(all_records)
    print(f"总计提取阳线样本量: {len(data):,} 根\n")

    # 1. 实体涨幅分档统计
    bins = [0, 1.0, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 999]
    labels = ["0%~1%", "1%~2%", "2%~2.5%", "2.5%~3%", "3%~4%", "4%~5%", "5%~7%", "≥7%"]

    data["body_bin"] = pd.cut(data["prev_body_pct"], bins=bins, labels=labels)
    data["tot_bin"] = pd.cut(data["prev_tot_pct"], bins=bins, labels=labels)

    body_grp = data.groupby("body_bin", observed=False).agg(
        样本数=("next_intra_ret", "count"),
        次日开到收均值=("next_intra_ret", "mean"),
        次日冲高均值=("next_max_up", "mean"),
        次日收阴概率=("next_is_yin", lambda x: np.mean(x) * 100.0),
        次日触及止损率=("next_hit_stop25", lambda x: np.mean(x) * 100.0),
    ).reset_index()

    tot_grp = data.groupby("tot_bin", observed=False).agg(
        样本数=("next_intra_ret", "count"),
        次日开到收均值=("next_intra_ret", "mean"),
        次日冲高均值=("next_max_up", "mean"),
        次日收阴概率=("next_is_yin", lambda x: np.mean(x) * 100.0),
        次日触及止损率=("next_hit_stop25", lambda x: np.mean(x) * 100.0),
    ).reset_index()

    print("=========================================================================")
    print("【维度一：按「前日阳线实体 (日内推升幅度)」分档的次日表现】")
    print("=========================================================================")
    print(body_grp.to_string(index=False))

    print("\n=========================================================================")
    print("【维度二：按「前日全天总涨幅 (含隔夜跳空)」分档的次日表现】")
    print("=========================================================================")
    print(tot_grp.to_string(index=False))

    # 2. 控制变量 2x2 对照实验 (揭示本质):
    # 分离跳空与实体：
    # 场景 A: 跳空高开但实体小 (前日跳空≥2%，前日实体<1.5%) -> 隔夜资金强，但日内未过度拉升
    # 场景 B: 平开但大实体推升 (前日跳空在[-0.5%, 0.5%]，前日实体≥3.5%) -> 纯日内多头激战推升
    # 场景 C: 低开逆袭大实体 (前日跳空≤-1.5%，前日实体≥3.5%) -> 日内极度透支推升
    print("\n=========================================================================")
    print("【维度三：控制变量对照分析（分离跳空情绪 vs 日内实体推升）】")
    print("=========================================================================")

    case_a = data[(data["prev_gap_pct"] >= 2.0) & (data["prev_body_pct"] < 1.5)]
    case_b = data[(data["prev_gap_pct"].between(-0.5, 0.5)) & (data["prev_body_pct"] >= 3.0)]
    case_c = data[(data["prev_gap_pct"] <= -1.5) & (data["prev_body_pct"] >= 3.0)]

    cases = [
        ("场景A：大高开+小实体 (跳空≥2%, 实体<1.5%)", case_a),
        ("场景B：平开+大实体 (跳空±0.5%, 实体≥3.0%)", case_b),
        ("场景C：深低开+逆袭大实体 (低开≤-1.5%, 实体≥3.0%)", case_c),
    ]

    case_rows = []
    for c_name, sub in cases:
        case_rows.append({
            "对照组特征": c_name,
            "样本数": len(sub),
            "次日开到收均值%": round(sub["next_intra_ret"].mean(), 2),
            "次日冲高均值%": round(sub["next_max_up"].mean(), 2),
            "次日收阴概率%": round(sub["next_is_yin"].mean() * 100.0, 2),
            "次日触止损概率%": round(sub["next_hit_stop25"].mean() * 100.0, 2),
        })

    print(pd.DataFrame(case_rows).to_string(index=False))


if __name__ == "__main__":
    run_research()
