"""Explainable scoring rules for market timing and rebound candidates."""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

from indicators import add_indicators, latest_snapshot


MARKET_WEIGHTS = {
    "市场情绪": 30.0,
    "大盘资金流向": 20.0,
    "资金结构": 20.0,
    "盘面特点": 20.0,
    "国家队证据": 10.0,
}
CANDIDATE_WEIGHTS = {
    "超跌程度": 30.0,
    "抛压衰竭": 20.0,
    "止跌确认": 25.0,
    "资金回流": 15.0,
    "板块共振": 10.0,
}
NATIONAL_TEAM_KEYWORDS = (
    "中央汇金",
    "中国证券金融",
    "证金公司",
    "中央汇金资产",
)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _valid_number(value: Any) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _linear(value: Any, bad: float, good: float, reverse: bool = False) -> float | None:
    if not _valid_number(value):
        return None
    number = float(value)
    if bad == good:
        return 50.0
    score = (number - bad) / (good - bad) * 100
    if reverse:
        score = 100 - score
    return clamp(score)


def weighted_available(
    items: Iterable[tuple[str, float | None, float]],
) -> tuple[float | None, float, list[dict[str, Any]]]:
    """Normalize over available components and expose missing items."""
    numerator = 0.0
    denominator = 0.0
    total_weight = 0.0
    detail = []
    for name, score, weight in items:
        total_weight += weight
        available = score is not None and _valid_number(score)
        if available:
            denominator += weight
            numerator += float(score) * weight
        detail.append(
            {
                "name": name,
                "score": round(float(score), 1) if available else None,
                "weight": weight,
                "available": available,
            }
        )
    normalized = numerator / denominator if denominator else None
    coverage = denominator / total_weight * 100 if total_weight else 0.0
    return (
        round(normalized, 1) if normalized is not None else None,
        round(coverage, 1),
        detail,
    )


def score_sentiment(breadth: dict[str, Any]) -> dict[str, Any]:
    if not breadth:
        return unavailable_dimension("市场情绪", "全市场日线无有效横截面")
    score, coverage, components = weighted_available(
        [
            ("上涨占比", _linear(breadth.get("advance_ratio_pct"), 20, 65), 25),
            ("中位数涨幅", _linear(breadth.get("median_pct"), -4, 2), 25),
            (
                "大跌尾部占比",
                _linear(
                    breadth.get("down_5_count", 0) / max(breadth.get("sample_size", 1), 1) * 100,
                    15,
                    1,
                ),
                20,
            ),
            (
                "近跌停占比",
                _linear(
                    breadth.get("near_limit_down_count", 0) / max(breadth.get("sample_size", 1), 1) * 100,
                    5,
                    0.1,
                ),
                10,
            ),
            ("连续三日下跌占比", _linear(breadth.get("consecutive_down_3d_pct"), 45, 10), 20),
        ]
    )
    evidence = [
        f"上涨 {breadth.get('advances', 'N/A')} / 下跌 {breadth.get('declines', 'N/A')} 家",
        f"全市场中位数涨幅 {breadth.get('median_pct', 'N/A')}%",
        f"≤-5% {breadth.get('down_5_count', 'N/A')} 家；近跌停 {breadth.get('near_limit_down_count', 'N/A')} 家",
    ]
    return dimension("市场情绪", score, coverage, evidence, [], components, ["get_stock_daily"])


def score_market_flow(breadth: dict[str, Any], etf_proxy: dict[str, Any] | None = None) -> dict[str, Any]:
    if not breadth:
        return unavailable_dimension("大盘资金流向", "全市场成交额数据不可用")
    components_input: list[tuple[str, float | None, float]] = [
        ("上涨股成交额占比", _linear(breadth.get("advancing_amount_pct"), 25, 65), 40),
        ("当日成交额/20日均额", _linear(breadth.get("amount_ratio_20"), 0.6, 1.3), 30),
        ("近5日成交额趋势", _linear(breadth.get("amount_trend_5"), 0.75, 1.25), 20),
    ]
    etf_score = None
    etf_evidence: list[str] = []
    if etf_proxy and etf_proxy.get("score") is not None:
        etf_score = etf_proxy["score"]
        etf_evidence = etf_proxy.get("evidence", [])
    components_input.append(("宽基ETF净申赎代理", etf_score, 10))
    score, coverage, components = weighted_available(components_input)
    evidence = [
        f"上涨股成交额占比 {breadth.get('advancing_amount_pct', 'N/A')}%",
        f"当日成交额/20日均额 {breadth.get('amount_ratio_20', 'N/A')}",
        f"近5日成交额趋势 {breadth.get('amount_trend_5', 'N/A')}",
        *etf_evidence,
    ]
    missing = [] if etf_score is not None else ["ETF净申赎不可用，不纳入评分"]
    return dimension(
        "大盘资金流向", score, coverage, evidence, missing, components,
        ["get_stock_daily", "get_fund_etf_cr_net"],
    )


def analyze_margin(frame: pd.DataFrame) -> dict[str, Any] | None:
    required = {"date", "margin_balance", "buy_on_margin_value", "margin_repayment"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    df = frame.copy()
    for column in required - {"date"}:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    # PandaData currently returns duplicated financing fields for margin_type
    # cash and stock. Financing analysis uses one comparable row per symbol/date.
    if "margin_type" in df.columns:
        cash = df[df["margin_type"].astype(str).str.lower() == "cash"]
        if not cash.empty:
            df = cash
    dedup_keys = [column for column in ("symbol", "date") if column in df.columns]
    if dedup_keys:
        df = df.drop_duplicates(dedup_keys, keep="last")
    group_columns = {
        "margin_balance": "sum",
        "buy_on_margin_value": "sum",
        "margin_repayment": "sum",
    }
    daily = df.groupby("date", as_index=False).agg(group_columns).sort_values("date")
    daily["net"] = daily["buy_on_margin_value"] - daily["margin_repayment"]
    if daily.empty:
        return None
    recent = daily.tail(10)
    net_5 = recent.tail(5)["net"].sum()
    previous_5 = recent.head(max(0, len(recent) - 5))["net"].sum() if len(recent) > 5 else np.nan
    balance_change_5 = None
    if len(daily) >= 6 and daily["margin_balance"].iloc[-6] != 0:
        balance_change_5 = (daily["margin_balance"].iloc[-1] / daily["margin_balance"].iloc[-6] - 1) * 100
    improvement = None if pd.isna(previous_5) else float(net_5 - previous_5)
    scale = max(float(daily["margin_balance"].iloc[-1]), 1.0)
    normalized_net = net_5 / scale * 100
    score = clamp(50 + normalized_net * 12)
    if improvement is not None:
        score = clamp(score + np.sign(improvement) * min(abs(improvement) / scale * 300, 20))
    return {
        "score": round(score, 1),
        "net_5_billion": round(float(net_5) / 1e8, 2),
        "balance_billion": round(float(daily["margin_balance"].iloc[-1]) / 1e8, 2),
        "balance_change_5_pct": round(float(balance_change_5), 2) if balance_change_5 is not None else None,
        "evidence": f"融资近5日净额 {net_5/1e8:.2f} 亿，余额5日变化 {balance_change_5 if balance_change_5 is not None else 'N/A'}%",
    }


def _find_column(columns: Iterable[str], patterns: tuple[str, ...]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in columns}
    for pattern in patterns:
        for lower, original in lowered.items():
            if pattern in lower:
                return original
    return None


def analyze_northbound(frame: pd.DataFrame) -> dict[str, Any] | None:
    """Score quarterly HSGT holding snapshots returned by get_hsgt_hold."""
    if frame.empty or "date" not in frame.columns:
        return None
    value_col = _find_column(
        frame.columns,
        ("adjusted_holding_ratio", "holding_ratio", "shares_num", "holding", "hold_amount", "hold_vol"),
    )
    if value_col is None:
        return None
    df = frame.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
    df = df.dropna(subset=[value_col, "date"])
    if df.empty:
        return None
    key = "symbol" if "symbol" in df.columns else None
    changes = []
    groups = df.groupby(key) if key else [("all", df)]
    for _, group in groups:
        series = group.sort_values("date")[["date", value_col]].drop_duplicates("date").dropna()
        if len(series) >= 2:
            # Compare the latest two disclosed snapshots. The API's date is
            # the disclosure/report date, not a daily trading-flow timestamp.
            changes.append(float(series[value_col].iloc[-1] - series[value_col].iloc[-2]))
    if not changes:
        return None
    positive = sum(value > 0.01 for value in changes)
    negative = sum(value < -0.01 for value in changes)
    unchanged = len(changes) - positive - negative
    score = clamp(50 + (positive - negative) / max(len(changes), 1) * 50)
    return {
        "score": round(score, 1),
        "comparable_count": len(changes),
        "positive_count": positive,
        "negative_count": negative,
        "unchanged_count": unchanged,
        "field": value_col,
        "evidence": f"北向持仓可比 {len(changes)} 只，增加 {positive}、减少 {negative}、基本不变 {unchanged}（持仓变化，非实时流量）",
    }


def analyze_lhb(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    agency_col = _find_column(frame.columns, ("agency", "seat", "department", "营业部"))
    buy_col = _find_column(frame.columns, ("b_value", "buy_value", "buy_amount"))
    sell_col = _find_column(frame.columns, ("s_value", "sell_value", "sell_amount"))
    if not agency_col or not buy_col or not sell_col:
        return None
    inst = frame[frame[agency_col].astype(str).str.contains("机构", na=False)].copy()
    if inst.empty:
        return None
    buy = pd.to_numeric(inst[buy_col], errors="coerce").fillna(0)
    sell = pd.to_numeric(inst[sell_col], errors="coerce").fillna(0)
    net = float((buy - sell).sum())
    gross = max(float((buy + sell).sum()), 1.0)
    score = clamp(50 + net / gross * 50)
    return {
        "score": round(score, 1),
        "net_billion": round(net / 1e8, 2),
        "record_count": len(inst),
        "evidence": f"龙虎榜机构席位净额 {net/1e8:.2f} 亿（仅上榜样本）",
    }


def score_fund_structure(funds: dict[str, pd.DataFrame]) -> dict[str, Any]:
    margin = analyze_margin(funds.get("margin", pd.DataFrame()))
    northbound = analyze_northbound(funds.get("northbound", pd.DataFrame()))
    lhb = analyze_lhb(funds.get("lhb", pd.DataFrame()))
    score, coverage, components = weighted_available(
        [
            ("融资趋势", margin.get("score") if margin else None, 45),
            ("北向持仓变化", northbound.get("score") if northbound else None, 30),
            ("龙虎榜机构净买卖", lhb.get("score") if lhb else None, 25),
        ]
    )
    evidence = [item["evidence"] for item in (margin, northbound, lhb) if item]
    missing = []
    if not margin:
        missing.append("融资数据/字段不可用")
    if not northbound:
        missing.append("北向持仓数据/字段不可用")
    if not lhb:
        missing.append("龙虎榜机构数据/字段不可用")
    if score is None:
        return unavailable_dimension("资金结构", "；".join(missing))
    result = dimension(
        "资金结构", score, coverage, evidence, missing, components,
        ["get_margin", "get_hsgt_hold", "get_lhb_detail"],
    )
    result["raw"] = {"margin": margin, "northbound": northbound, "lhb": lhb}
    return result


def score_tape(index_frame: pd.DataFrame) -> dict[str, Any]:
    if index_frame.empty or "symbol" not in index_frame.columns:
        return unavailable_dimension("盘面特点", "宽基指数日线不可用")
    snapshots = {}
    for symbol, group in index_frame.groupby("symbol"):
        if len(group) >= 20:
            snapshots[str(symbol)] = latest_snapshot(group)
    if not snapshots:
        return unavailable_dimension("盘面特点", "宽基指数历史不足")
    component_scores = []
    evidence = []
    stop_evidence = 0
    for symbol, snap in snapshots.items():
        oversold = _linear(snap.get("rsi6"), 10, 55)
        trend = _linear(snap.get("ret_5d"), -10, 3)
        reversal_flags = sum(
            bool(snap.get(flag))
            for flag in ("low_holds", "rsi_turn_up", "macd_contracting", "ma5_reclaim", "decline_narrowing")
        )
        reversal = clamp(reversal_flags / 4 * 100)
        if reversal_flags >= 2:
            stop_evidence += 1
        component_scores.append((f"{symbol}趋势", trend, 1))
        component_scores.append((f"{symbol}修复", reversal, 1))
        component_scores.append((f"{symbol}RSI", oversold, 0.5))
        evidence.append(
            f"{symbol}: 5日 {snap.get('ret_5d')}%，RSI6 {snap.get('rsi6')}，止跌信号 {reversal_flags} 项"
        )
    score, coverage, components = weighted_available(component_scores)
    result = dimension("盘面特点", score, coverage, evidence, [], components, ["get_index_daily"])
    result["stop_evidence_count"] = stop_evidence
    result["snapshots"] = snapshots
    return result


def analyze_etf_proxy(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    column = next(
        (
            candidate
            for candidate in ("net_inflow", "net_redemption", "shares_change", "size_change")
            if candidate in frame.columns
        ),
        None,
    )
    if column is None:
        return None
    df = frame.copy()
    df[column] = pd.to_numeric(df[column], errors="coerce")
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
        # Aggregate all tracked broad ETFs by date, then inspect five trading days.
        recent = df.groupby("date")[column].sum(min_count=1).sort_index().dropna().tail(5)
    else:
        recent = df[column].dropna().tail(5)
    if recent.empty:
        return None
    # PandaData net_redemption is redemption-minus-creation; invert its sign so
    # positive always means capital entering the tracked broad ETFs.
    inflow = -recent if column == "net_redemption" else recent
    positive_ratio = float((inflow > 0).mean())
    latest = float(inflow.iloc[-1])
    scale = float(inflow.abs().median()) if float(inflow.abs().median()) > 0 else 1.0
    directional = clamp(50 + latest / scale * 20)
    score = clamp(positive_ratio * 60 + directional * 0.4)
    return {
        "score": round(score, 1),
        "field": column,
        "latest_inflow_proxy": round(latest, 2),
        "positive_days": int((inflow > 0).sum()),
        "sample_days": int(len(inflow)),
        "evidence": [
            f"宽基ETF {column} 口径最近{len(inflow)}日资金流入代理："
            f"正值{int((inflow > 0).sum())}日，最新{latest:.2f}（仅代理信号）"
        ],
    }


def analyze_national_team(holder_frame: pd.DataFrame, etf_proxy: dict[str, Any] | None) -> dict[str, Any]:
    hard_evidence: list[dict[str, Any]] = []
    change_scores: list[float] = []
    if not holder_frame.empty:
        holder_col = _find_column(holder_frame.columns, ("holder_name", "shareholder_name", "holder", "name"))
        report_col = _find_column(holder_frame.columns, ("end_date", "report_date"))
        publish_col = "date" if "date" in holder_frame.columns else None
        holding_col = _find_column(holder_frame.columns, ("hold_amount", "holding", "shareholding", "hold_num"))
        ratio_col = _find_column(
            holder_frame.columns,
            ("hold_percent_float", "hold_percent_total", "hold_ratio", "holding_ratio", "shareholding_ratio"),
        )
        if holder_col:
            matched = holder_frame[
                holder_frame[holder_col].astype(str).apply(
                    lambda value: any(keyword in value for keyword in NATIONAL_TEAM_KEYWORDS)
                )
            ].copy()
            key_columns = [column for column in ("symbol", holder_col, report_col) if column]
            if key_columns:
                matched = matched.drop_duplicates(key_columns, keep="last")
            if ratio_col:
                matched[ratio_col] = pd.to_numeric(matched[ratio_col], errors="coerce")
            group_columns = [column for column in ("symbol", holder_col) if column]
            groups = matched.groupby(group_columns, dropna=False) if group_columns else [("all", matched)]
            for _, group in groups:
                if report_col:
                    group = group.assign(
                        _report_sort=group[report_col].astype(str).str.replace("-", "", regex=False)
                    ).sort_values("_report_sort")
                latest = group.iloc[-1]
                previous = group.iloc[-2] if len(group) >= 2 else None
                comparable = False
                if previous is not None and report_col:
                    try:
                        current_report = pd.to_datetime(str(latest.get(report_col)), format="%Y%m%d")
                        previous_report = pd.to_datetime(str(previous.get(report_col)), format="%Y%m%d")
                        gap_days = int((current_report - previous_report).days)
                        # Only regular adjacent quarter/half-year disclosures are
                        # comparable. Ad-hoc holder snapshots can change float
                        # denominators and would create false "reductions".
                        comparable = 60 <= gap_days <= 200
                    except (TypeError, ValueError):
                        comparable = False
                change = None
                if ratio_col and previous is not None and comparable:
                    current_ratio = latest.get(ratio_col)
                    previous_ratio = previous.get(ratio_col)
                    if _valid_number(current_ratio) and _valid_number(previous_ratio):
                        change = float(current_ratio) - float(previous_ratio)
                        # Small reporting/float-base noise stays neutral.
                        if change > 0.01:
                            change_scores.append(100.0)
                        elif change < -0.01:
                            change_scores.append(0.0)
                        else:
                            change_scores.append(50.0)
                hard_evidence.append(
                    {
                        "symbol": str(latest.get("symbol", "")) or None,
                        "holder": str(latest.get(holder_col, "")),
                        "report_date": str(latest.get(report_col, "")) if report_col else None,
                        "publish_date": str(latest.get(publish_col, "")) if publish_col else None,
                        "holding": latest.get(holding_col) if holding_col else None,
                        "holding_ratio": latest.get(ratio_col) if ratio_col else None,
                        "holding_ratio_change": round(change, 6) if change is not None else None,
                        "note": "定期报告持仓，存在披露滞后；只有可比报告期增持才构成方向性硬证据。",
                    }
                )
    if hard_evidence:
        # Keep the strongest disclosed changes in the report; aggregate counts
        # still use every comparable series.
        hard_evidence.sort(
            key=lambda item: abs(item.get("holding_ratio_change") or 0.0),
            reverse=True,
        )
        hard_evidence = hard_evidence[:20]
        if change_scores:
            hard_score = round(float(np.mean(change_scores)), 1)
            increased = sum(score == 100 for score in change_scores)
            decreased = sum(score == 0 for score in change_scores)
            unchanged = sum(score == 50 for score in change_scores)
            interpretation = (
                f"发现明确主体持仓记录；可比序列中增持 {increased}、减持 {decreased}、基本不变 {unchanged}。"
                "这是滞后披露的持仓变化，不等同于分析日实时入场。"
            )
            missing = []
            coverage = 100.0
        else:
            hard_score = None
            interpretation = (
                "发现明确国家队主体历史持仓，但没有可比持股比例变化；仅证明持有，"
                "不能判断本期增持或实时入场。"
            )
            missing = ["缺少两个可比报告期的持股比例，国家队方向分记为N/A"]
            coverage = 0.0
        return {
            "name": "国家队证据",
            "score": hard_score,
            "coverage_pct": coverage,
            "available": hard_score is not None,
            "evidence_level": "HARD",
            "evidence": hard_evidence,
            "missing": missing,
            "sources": ["get_top_holders"],
            "interpretation": interpretation,
        }
    if etf_proxy and etf_proxy.get("score") is not None:
        return {
            "name": "国家队证据",
            "score": float(etf_proxy["score"]),
            "coverage_pct": 50.0,
            "available": True,
            "evidence_level": "PROXY",
            "evidence": etf_proxy.get("evidence", []),
            "missing": ["未发现明确中央汇金/证金等股东硬证据"],
            "sources": ["get_fund_etf_cr_net"],
            "interpretation": "仅有宽基ETF代理信号，不能表述为国家队已经入场。",
        }
    return {
        "name": "国家队证据",
        "score": None,
        "coverage_pct": 0.0,
        "available": False,
        "evidence_level": "N/A",
        "evidence": [],
        "missing": ["PandaData 未返回可验证的明确主体持仓变化或可用 ETF 代理数据"],
        "sources": ["get_top_holders", "get_fund_etf_cr_net"],
        "interpretation": "无法确认国家队动作；不得由指数上涨推断国家队入场。",
    }


def dimension(
    name: str,
    score: float | None,
    coverage: float,
    evidence: list[Any],
    missing: list[str],
    components: list[dict[str, Any]],
    sources: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "score": round(float(score), 1) if score is not None else None,
        "coverage_pct": coverage,
        "available": score is not None,
        "evidence": evidence,
        "missing": missing,
        "components": components,
        "sources": sources,
    }


def unavailable_dimension(name: str, reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "score": None,
        "coverage_pct": 0.0,
        "available": False,
        "evidence": [],
        "missing": [reason],
        "components": [],
        "sources": [],
    }


def infer_stage(
    environment_score: float | None,
    dimensions: dict[str, dict[str, Any]],
    breadth: dict[str, Any],
) -> dict[str, Any]:
    sentiment = dimensions.get("市场情绪", {}).get("score")
    tape = dimensions.get("盘面特点", {}).get("score")
    funds = dimensions.get("资金结构", {}).get("score")
    stop_count = dimensions.get("盘面特点", {}).get("stop_evidence_count", 0)
    median_pct = breadth.get("median_pct")
    down_5 = breadth.get("down_5_count", 0)
    sample = max(breadth.get("sample_size", 1), 1)
    down_tail_pct = down_5 / sample * 100
    index_snaps = dimensions.get("盘面特点", {}).get("snapshots", {})
    hot_count = sum(
        (snap.get("rsi6") or 0) > 75 or (snap.get("ret_5d") or -999) > 8
        for snap in index_snaps.values()
    )
    reasons = []

    panic = (
        sentiment is not None
        and sentiment < 30
        and ((median_pct is not None and median_pct <= -1.5) or down_tail_pct >= 8)
    )
    exhaustion = hot_count >= max(2, len(index_snaps) // 2) and sentiment is not None and sentiment < 55
    confirmed = (
        environment_score is not None
        and environment_score >= 65
        and sentiment is not None
        and sentiment >= 55
        and tape is not None
        and tape >= 55
        and (funds is None or funds >= 45)
    )
    probing = environment_score is not None and environment_score >= 48 and stop_count >= 2

    if panic:
        stage = "恐慌加速"
        gate = "FAIL"
        reasons.extend(["市场情绪仍弱", "大跌尾部或中位数跌幅仍处高位"])
    elif exhaustion:
        stage = "反弹衰竭"
        gate = "FAIL"
        reasons.extend(["宽基短线过热", "市场广度未同步维持"])
    elif confirmed:
        stage = "反弹确认"
        gate = "PASS"
        reasons.extend(["环境总分达到确认阈值", "情绪和盘面同步改善"])
    elif probing:
        stage = "止跌试探"
        gate = "CAUTION"
        reasons.extend(["出现多项止跌证据", "尚未达到反弹确认阈值"])
    else:
        stage = "情绪冰点"
        gate = "FAIL"
        reasons.extend(["存在超卖或极端下跌背景", "止跌确认不足"])
    return {"stage": stage, "market_gate": gate, "reasons": reasons}


def aggregate_market(
    dimensions: dict[str, dict[str, Any]], breadth: dict[str, Any]
) -> dict[str, Any]:
    """Aggregate dimensions using each dimension's actually covered sub-weight."""
    numerator = 0.0
    available_weight = 0.0
    components = []
    for name, base_weight in MARKET_WEIGHTS.items():
        item = dimensions.get(name, {})
        score = item.get("score")
        sub_coverage = item.get("coverage_pct", 100.0 if score is not None else 0.0)
        sub_coverage = clamp(sub_coverage, 0, 100)
        effective_weight = base_weight * sub_coverage / 100
        available = _valid_number(score) and effective_weight > 0
        if available:
            numerator += float(score) * effective_weight
            available_weight += effective_weight
        components.append(
            {
                "name": name,
                "score": round(float(score), 1) if _valid_number(score) else None,
                "base_weight": base_weight,
                "sub_coverage_pct": round(sub_coverage, 1),
                "effective_weight": round(effective_weight, 2) if available else 0.0,
                "available": available,
            }
        )
    score = round(numerator / available_weight, 1) if available_weight else None
    coverage = round(available_weight / sum(MARKET_WEIGHTS.values()) * 100, 1)
    stage = infer_stage(score, dimensions, breadth)
    return {
        "environment_score": score,
        "coverage_pct": coverage,
        "weighted_dimensions": components,
        **stage,
    }


def _piecewise_points(value: Any, rules: list[tuple[float, float]], *, lower_is_better: bool = True) -> float | None:
    if not _valid_number(value):
        return None
    number = float(value)
    sorted_rules = sorted(rules, key=lambda item: item[0], reverse=not lower_is_better)
    for threshold, points in sorted_rules:
        if (lower_is_better and number <= threshold) or (not lower_is_better and number >= threshold):
            return points
    return 0.0


def score_candidate(
    symbol: str,
    snapshot: dict[str, Any],
    market: dict[str, Any],
    fund_signal: dict[str, Any] | None = None,
    relative_strength: float | None = None,
    name: str | None = None,
    min_amount: float = 50_000_000,
) -> dict[str, Any]:
    reasons: list[str] = []
    counter_evidence: list[str] = []
    vetoes: list[str] = []
    downgrades: list[str] = []

    if snapshot.get("history_rows", 0) < 60:
        vetoes.append("有效历史不足60个交易日")
    if not snapshot.get("valid_trade", False):
        vetoes.append("最新日无有效成交，可能停牌或数据缺失")
    if name and re.search(r"(?:\*ST|ST)", name.upper()):
        vetoes.append("股票名称含 ST，默认不参与抢反弹")
    pct = snapshot.get("pct")
    close_location = snapshot.get("close_location")
    volume_ratio = snapshot.get("volume_ratio_20")
    if _valid_number(pct) and float(pct) <= -9.5 and (close_location or 0) < 0.15:
        vetoes.append("最新日近跌停且收盘接近日内最低")
    last_3 = snapshot.get("last_3_pcts", [])
    if (
        len(last_3) >= 2
        and last_3[-1] < last_3[-2] < 0
        and _valid_number(volume_ratio)
        and float(volume_ratio) >= 1.5
    ):
        vetoes.append("跌幅扩大且放量，仍处加速下跌")
    amount_ma20 = snapshot.get("amount_ma20")
    if _valid_number(amount_ma20) and float(amount_ma20) < min_amount:
        downgrades.append(f"20日平均成交额低于 {min_amount/1e8:.1f} 亿，流动性偏低")

    oversold_components: list[tuple[str, float | None, float]] = [
        ("5日跌幅", _piecewise_points(snapshot.get("ret_5d"), [(-12, 100), (-8, 80), (-4, 55), (0, 20)]), 20),
        ("10日跌幅", _piecewise_points(snapshot.get("ret_10d"), [(-20, 100), (-12, 80), (-6, 55), (0, 20)]), 20),
        ("20日回撤", _piecewise_points(snapshot.get("drawdown_20d"), [(-25, 100), (-18, 80), (-10, 55), (-3, 20)]), 20),
        ("60日回撤", _piecewise_points(snapshot.get("drawdown_60d"), [(-35, 100), (-25, 80), (-15, 55), (-5, 20)]), 15),
        ("RSI6", _piecewise_points(snapshot.get("rsi6"), [(15, 100), (25, 80), (35, 55), (50, 20)]), 15),
        ("布林%B", _piecewise_points(snapshot.get("bb_pct"), [(0, 100), (15, 80), (30, 55), (50, 20)]), 10),
    ]
    oversold, oversold_cov, oversold_detail = weighted_available(oversold_components)

    exhaustion_flags = []
    if snapshot.get("decline_narrowing"):
        exhaustion_flags.append("跌幅收窄")
    if snapshot.get("down_volume_trend") is not None and snapshot["down_volume_trend"] < 0.85:
        exhaustion_flags.append("下跌日量能递减")
    if _valid_number(volume_ratio) and float(volume_ratio) < 0.8:
        exhaustion_flags.append("成交量低于20日均量")
    if _valid_number(snapshot.get("atr14_pct")) and float(snapshot["atr14_pct"]) < 4:
        exhaustion_flags.append("短线波动收敛")
    exhaustion = clamp(20 + len(exhaustion_flags) * 22) if snapshot else None

    confirmation_flags = []
    if (snapshot.get("lower_shadow_ratio") or 0) >= 0.35 and (snapshot.get("close_location") or 0) >= 0.55:
        confirmation_flags.append("长下影且收盘位置较高")
    if snapshot.get("low_holds"):
        confirmation_flags.append("低点不再下移")
    if snapshot.get("rsi_turn_up"):
        confirmation_flags.append("RSI6拐头")
    if snapshot.get("macd_contracting"):
        confirmation_flags.append("MACD绿柱收窄")
    if snapshot.get("ma5_reclaim"):
        confirmation_flags.append("重新站上MA5")
    confirmation = clamp(10 + len(confirmation_flags) * 18)

    fund_score = fund_signal.get("score") if fund_signal else None
    if fund_signal and fund_signal.get("evidence"):
        reasons.extend(fund_signal["evidence"] if isinstance(fund_signal["evidence"], list) else [fund_signal["evidence"]])

    sector_score = _linear(relative_strength, -5, 5) if relative_strength is not None else None
    if relative_strength is not None:
        if relative_strength > 0.05:
            reasons.append(f"个股5日相对基准强 {relative_strength:+.2f} 个百分点")
        elif relative_strength < -0.05:
            counter_evidence.append(f"个股5日相对基准弱 {relative_strength:+.2f} 个百分点")

    sub_scores = {
        "超跌程度": oversold,
        "抛压衰竭": round(exhaustion, 1),
        "止跌确认": round(confirmation, 1),
        "资金回流": round(float(fund_score), 1) if _valid_number(fund_score) else None,
        "板块共振": round(float(sector_score), 1) if _valid_number(sector_score) else None,
    }
    total, coverage, components = weighted_available(
        [(label, sub_scores[label], weight) for label, weight in CANDIDATE_WEIGHTS.items()]
    )
    if downgrades and total is not None:
        total = round(max(0.0, total - 8 * len(downgrades)), 1)

    reasons.extend(confirmation_flags + exhaustion_flags)
    if oversold is not None and oversold >= 65:
        reasons.append(
            f"超跌：5日 {snapshot.get('ret_5d')}%，20日回撤 {snapshot.get('drawdown_20d')}%，RSI6 {snapshot.get('rsi6')}"
        )
    if snapshot.get("consecutive_down_days", 0) >= 4:
        counter_evidence.append(f"已连续下跌 {snapshot['consecutive_down_days']} 日，趋势惯性仍强")
    if _valid_number(volume_ratio) and float(volume_ratio) > 1.5 and (pct or 0) < 0:
        counter_evidence.append("下跌日仍明显放量")
    if (snapshot.get("close") or 0) < (snapshot.get("ma20") or -math.inf):
        counter_evidence.append("价格仍在MA20下方")

    if confirmation >= 70 and (total or 0) >= 70:
        horizon = "1–3日"
    elif confirmation >= 45:
        horizon = "3–5日"
    else:
        horizon = "5–10日观察"

    market_gate = market.get("market_gate", "FAIL")
    if market_gate == "FAIL":
        counter_evidence.append("市场门控未通过，个股信号容易失败")

    passes_candidate_threshold = (
        total is not None
        and total >= 45
        and oversold is not None
        and oversold >= 40
        and confirmation >= 28
    )
    if not vetoes and not passes_candidate_threshold:
        downgrades.append("未同时达到总分45、超跌分40和止跌确认分28的候选阈值")

    return {
        "symbol": symbol,
        "name": name,
        "score": total,
        "coverage_pct": coverage,
        "sub_scores": sub_scores,
        "component_detail": {"超跌程度": oversold_detail, "总分": components},
        "market_gate": market_gate,
        "expected_window": horizon,
        "selected": not vetoes and passes_candidate_threshold,
        "vetoes": vetoes,
        "downgrades": downgrades,
        "evidence": list(dict.fromkeys(reasons)),
        "counter_evidence": list(dict.fromkeys(counter_evidence)),
        "invalidation": [
            "下一交易日继续放量创新低",
            "收盘重新落到信号日低点下方",
            "市场阶段退回恐慌加速",
        ],
        "snapshot": snapshot,
    }
