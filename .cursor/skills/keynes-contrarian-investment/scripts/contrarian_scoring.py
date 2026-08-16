"""Explainable Keynes/Graham/Marks scoring and value-trap vetoes."""
from __future__ import annotations
from typing import Any

WEIGHTS = {"expectation_gap": 25.0, "fundamental_durability": 30.0, "valuation_safety": 20.0, "market_positioning": 15.0, "catalyst_falsification": 10.0}


def weighted_available(items: list[tuple[str, float | None, float]]) -> tuple[float | None, float, list[dict[str, Any]]]:
    available = [(name, float(value), weight) for name, value, weight in items if value is not None]
    if not available:
        return None, 0.0, []
    total_weight = sum(weight for _, _, weight in available)
    score = sum(value * weight for _, value, weight in available) / total_weight
    return round(score, 2), round(total_weight / sum(weight for _, _, weight in items) * 100, 2), [{"name": name, "score": value, "weight": weight} for name, value, weight in available]


def apply_vetoes(fundamentals: dict[str, Any], valuation: dict[str, Any]) -> dict[str, Any]:
    vetoes: list[str] = []
    downgrades: list[str] = []
    flags = fundamentals.get("deterioration_flags", [])
    metrics = fundamentals.get("reported_reality", {}).get("metrics", {})
    if "净利润同比显著下降" in flags and "经营现金流/净利润偏低" in flags:
        vetoes.append("便宜但盈利与现金流同步恶化，疑似价值陷阱")
    elif flags:
        downgrades.extend(flags)
    if "审计意见存在非标准风险" in flags:
        vetoes.append("非标准审计意见触发基本面硬风险")
    if valuation.get("pe_ttm") is None and valuation.get("pb") is None:
        downgrades.append("估值字段不可用，无法确认安全边际")
    return {"vetoes": vetoes, "downgrades": downgrades}


def score_case(expectation_gap: float | None, fundamental_durability: float | None, valuation_safety: float | None, market_positioning: float | None, catalyst_falsification: float | None, fundamentals: dict[str, Any], valuation: dict[str, Any]) -> dict[str, Any]:
    score, coverage, details = weighted_available([
        ("expectation_gap", expectation_gap, WEIGHTS["expectation_gap"]),
        ("fundamental_durability", fundamental_durability, WEIGHTS["fundamental_durability"]),
        ("valuation_safety", valuation_safety, WEIGHTS["valuation_safety"]),
        ("market_positioning", market_positioning, WEIGHTS["market_positioning"]),
        ("catalyst_falsification", catalyst_falsification, WEIGHTS["catalyst_falsification"]),
    ])
    gates = apply_vetoes(fundamentals, valuation)
    if gates["vetoes"]:
        decision = "FAIL"
    elif score is None or coverage < 50:
        decision = "N/A"
    elif score >= 70 and coverage >= 70:
        decision = "PASS"
    else:
        decision = "CAUTION"
    return {"score": score, "coverage_pct": coverage, "sub_scores": {item["name"]: item["score"] for item in details}, "decision_gate": decision, **gates, "caveat": "分数是规则化研究排序，不是收益预测或买卖指令"}
