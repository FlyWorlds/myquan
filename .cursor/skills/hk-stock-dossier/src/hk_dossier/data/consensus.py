"""Analyst consensus — 一致预期与买卖建议.

注意：
  1. 港股接口字段名与 A 股不同（使用 mean/median/high/low 而非 mean_target_price 等）。
  2. get_stock_ncycl_consensus 返回多行（indicator 列区分指标类型），
     必须筛选 indicator=='TP' 获取目标价，indicator=='LTGROWTH' 为长期增长率。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_consensus(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch analyst consensus data.

    Returns:
      - ncycl_consensus: target price consensus (filtered to TP indicator)
      - recommendation: analyst recommendation breakdown
    """
    result: dict[str, Any] = {}

    # --- Target price consensus (HK naming: mean, median, high, low; indicator == 'TP') ---
    try:
        nc_df = client.call(
            "get_stock_ncycl_consensus", symbol=[symbol], fields=[]
        )
        if nc_df is not None and not nc_df.empty:
            # Filter to target price row (TP), fall back to first row if no TP found
            tp_row = nc_df[nc_df.get("indicator") == "TP"]
            if tp_row.empty:
                logger.warning(
                    "No TP indicator found for %s, using first row", symbol
                )
                row = nc_df.iloc[0]
            else:
                row = tp_row.iloc[0]

            result["ncycl_consensus"] = {
                "mean_target_price": row.get("mean"),
                "median_target_price": row.get("median"),
                "high_target_price": row.get("high"),
                "low_target_price": row.get("low"),
                "num_estimates": row.get("estimates_num"),
                "currency": row.get("currency"),
                "standard_deviation": row.get("std"),
            }
        else:
            result["ncycl_consensus"] = {}
    except Exception as e:
        logger.warning("Failed to fetch consensus for %s: %s", symbol, e)
        result["ncycl_consensus"] = {}

    # --- Recommendation consensus (HK naming: strong_buy_num, buy_num, hold, etc.) ---
    try:
        rec_df = client.call(
            "get_stock_recommendation_consensus", symbol=[symbol], fields=[]
        )
        if rec_df is not None and not rec_df.empty:
            row = rec_df.iloc[0]
            result["recommendation"] = {
                "buy_count": row.get("buy_num"),
                "strong_buy_count": row.get("strong_buy_num"),
                "hold_count": row.get("hold"),
                "sell_count": row.get("sell_num"),
                "strong_sell_count": row.get("strong_sell_num"),
                "no_opinion_count": row.get("no_opinion_num"),
                "total_recommendations": row.get("recommendations_num"),
                "mean_recommendation_score": row.get("mean"),
            }
        else:
            result["recommendation"] = {}
    except Exception as e:
        logger.warning("Failed to fetch recommendation for %s: %s", symbol, e)
        result["recommendation"] = {}

    return result
