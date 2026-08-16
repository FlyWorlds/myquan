"""Continuous Buffett-style scoring for point-in-time Panda Data payloads.

Financial thresholds are score anchors, not universal rejection gates. Structural
N/A fields (notably bank gross margin) are excluded and remaining weights are
renormalized. Ordinary missing data is disclosed and receives a coverage penalty.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import math


SCORE_VERSION = "soft-five-dimension-v1"


@dataclass(frozen=True)
class DimScore:
    name: str
    label: str
    value: float | None
    score: float | None
    base_weight: float
    effective_weight: float
    applicable: bool = True
    note: str = ""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _linear(value: Any, low: float, high: float) -> float | None:
    number = _finite(value)
    if number is None:
        return None
    return max(0.0, min(100.0, (number - low) / (high - low) * 100.0))


def _declining(value: Any, best: float, worst: float) -> float | None:
    number = _finite(value)
    if number is None:
        return None
    return max(0.0, min(100.0, (worst - number) / (worst - best) * 100.0))


def _gross_margin_score(mean: Any, std: Any) -> float | None:
    base = _linear(mean, 10.0, 50.0)
    volatility = _finite(std)
    if base is None or volatility is None:
        return None
    return max(0.0, base - 3.0 * volatility)


def _bank_dimensions(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use bank economics while preserving the user's five-dimension layout."""
    roe = metrics.get("roe_mean_pct")
    roa = metrics.get("roa_median_pct")
    roa_floor = metrics.get("roa_floor_pct")
    pb = metrics.get("pb")
    pe = metrics.get("current_pe")
    safety_parts = [score for score in (_linear(roa_floor, 0.4, 1.0), _declining(pb, 0.6, 1.8)) if score is not None]
    return [
        {"name": "roe", "label": "10 年 ROE 均值", "value": roe, "score": _linear(roe, 5.0, 18.0), "weight": 0.30, "note": "银行资本回报"},
        {"name": "gross_margin", "label": "毛利率+稳定性", "value": None, "score": None, "weight": 0.25, "applicable": False, "note": "银行毛利率 N/A；不填中性分"},
        {"name": "capex", "label": "资本效率（银行替代）", "value": roa, "score": _linear(roa, 0.4, 1.2), "weight": 0.15, "note": "银行以 10 年 ROA 中位数替代 CapEx/净利润"},
        {"name": "safety", "label": "安全边际（银行替代）", "value": roa_floor, "score": sum(safety_parts) / len(safety_parts) if safety_parts else None, "weight": 0.15, "note": "ROA 下限与 PB 组合"},
        {"name": "pe", "label": "当前 PE", "value": pe, "score": _declining(pe, 5.0, 20.0), "weight": 0.15, "note": "银行估值区间 5-20 倍"},
    ]


def _ordinary_dimensions(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    gross_mean = metrics.get("gross_margin_mean_5y_pct")
    gross_std = metrics.get("gross_margin_std_5y_pct_points")
    return [
        {"name": "roe", "label": "10 年 ROE 均值", "value": metrics.get("roe_mean_pct"), "score": _linear(metrics.get("roe_mean_pct"), 5.0, 18.0), "weight": 0.30, "note": "5%=0 分，18%=100 分"},
        {"name": "gross_margin", "label": "5 年毛利率+稳定性", "value": gross_mean, "score": _gross_margin_score(gross_mean, gross_std), "weight": 0.25, "note": "10%-50% 线性；标准差每 1pp 扣 3 分"},
        {"name": "capex", "label": "5 年 CapEx/净利润", "value": metrics.get("capex_to_profit_5y"), "score": _declining(metrics.get("capex_to_profit_5y"), 0.10, 0.60), "weight": 0.15, "note": "10%=100 分，60%=0 分"},
        {"name": "safety", "label": "5 年营业利润率", "value": metrics.get("operating_margin_mean_5y_pct"), "score": _linear(metrics.get("operating_margin_mean_5y_pct"), 2.0, 25.0), "weight": 0.15, "note": "2%=0 分，25%=100 分"},
        {"name": "pe", "label": "当前 PE", "value": metrics.get("current_pe"), "score": _declining(metrics.get("current_pe"), 10.0, 40.0), "weight": 0.15, "note": "10 倍=100 分，40 倍=0 分"},
    ]


def score_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics") or {}
    is_bank = payload.get("special_case") == "bank_roa"
    raw_dimensions = _bank_dimensions(metrics) if is_bank else _ordinary_dimensions(metrics)
    applicable_weight = sum(float(dim["weight"]) for dim in raw_dimensions if dim.get("applicable", True))
    observed_weight = sum(
        float(dim["weight"])
        for dim in raw_dimensions
        if dim.get("applicable", True) and dim.get("score") is not None
    )
    raw_score = (
        sum(float(dim["score"]) * float(dim["weight"]) for dim in raw_dimensions if dim.get("score") is not None)
        / observed_weight
        if observed_weight else 0.0
    )
    coverage_ratio = observed_weight / applicable_weight if applicable_weight else 0.0
    # Missing ordinary evidence cannot receive a free neutral score. A complete
    # company keeps 100% of its score; missing evidence reduces it by up to 30%.
    coverage_multiplier = 0.70 + 0.30 * coverage_ratio
    total_score = raw_score * coverage_multiplier

    dimensions: list[DimScore] = []
    for dim in raw_dimensions:
        applicable = bool(dim.get("applicable", True))
        effective = float(dim["weight"]) / applicable_weight if applicable and applicable_weight else 0.0
        dimensions.append(
            DimScore(
                name=str(dim["name"]),
                label=str(dim["label"]),
                value=_finite(dim.get("value")),
                score=_finite(dim.get("score")),
                base_weight=float(dim["weight"]),
                effective_weight=effective,
                applicable=applicable,
                note=str(dim.get("note", "")),
            )
        )

    return {
        "symbol": str(payload.get("target_id", "")),
        "industry": payload.get("industry"),
        "is_bank": is_bank,
        "special_case": payload.get("special_case"),
        "total_score": round(total_score, 4),
        "raw_available_score": round(raw_score, 4),
        "coverage_ratio": round(coverage_ratio, 4),
        "coverage_multiplier": round(coverage_multiplier, 4),
        "soft_eligible": observed_weight >= 0.60 and coverage_ratio >= 0.60,
        "score_version": SCORE_VERSION,
        "dimensions": [asdict(dim) for dim in dimensions],
        "metrics": dict(metrics),
    }


def score_payloads(payloads: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_payload(payload) for payload in payloads]
    return sorted(
        scored,
        key=lambda row: (
            not row["soft_eligible"],
            -float(row["total_score"]),
            -float(row["coverage_ratio"]),
            str(row["symbol"]),
        ),
    )
