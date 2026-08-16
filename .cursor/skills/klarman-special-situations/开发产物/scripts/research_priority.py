"""Deterministic research shortlist and independent risk-watch scoring for Q51.

The module deliberately sits beside underwriting.  Its scores prioritize work for
human research; they never promote an event to ``qualified_special_situation``.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
import re
from typing import Any, Iterable, Mapping

try:
    from .evidence import _json_safe
except ImportError:  # pragma: no cover - supports ``python scripts/...``
    from evidence import _json_safe


METHODOLOGY_ID = "research-priority-v1"
SHORTLIST_LIMIT = 5
RISK_LIMIT = 5
CATEGORY_CAP = 3
MINIMUM_SCORE = 60

_DISTRESS_TYPES = {"distress_event", "distress_turnaround_candidate"}
_REORG_TYPES = {
    "reorganization_event",
    "reorganization_candidate",
    "spin_off_event",
    "spin_off_candidate",
}
_PLACEMENT_TYPES = {"private_placement_supply_risk", "private_placement_unlock"}
_OPPORTUNITY_TYPES = _DISTRESS_TYPES | _REORG_TYPES
_REORG_WORDS = re.compile(r"重组|借壳|发行股份购买资产|吸收合并|私有化|要约收购", re.I)
_SPINOFF_WORDS = re.compile(r"分拆上市|分拆.*子公司|spin.?off", re.I)
_REDUCTION_WORDS = re.compile(r"减持|减仓|退出|reduc|sell", re.I)


def _date_token(value: Any) -> str | None:
    text = re.sub(r"\D", "", "" if value is None else str(value))[:8]
    if len(text) != 8:
        return None
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "pass", "present", "clean"}


def _symbol(value: Any) -> str:
    return str(value or "").replace(".SS", ".SH").strip()


def _event_date(payload: Mapping[str, Any], record: Mapping[str, Any], as_of: str) -> str | None:
    for key in ("event_date", "publish_date", "info_date", "announcement_date"):
        value = _date_token(payload.get(key))
        if value:
            return value
    lifecycle = payload.get("event_lifecycle")
    if isinstance(lifecycle, list):
        dates = [_date_token(item.get("date")) for item in lifecycle if isinstance(item, Mapping)]
        dates = [value for value in dates if value]
        if dates:
            return min(dates)
    for key in ("source_data_date", "actual_source_date"):
        value = _date_token(record.get(key))
        if value:
            return value
    return _date_token(payload.get("knowledge_cutoff")) or _date_token(as_of)


def _age_days(event_date: str | None, as_of: str) -> int | None:
    if not event_date or not _date_token(as_of):
        return None
    try:
        return (datetime.strptime(as_of, "%Y%m%d") - datetime.strptime(event_date, "%Y%m%d")).days
    except ValueError:
        return None


def _recency_points(age_days: int | None) -> int:
    if age_days is None or age_days < 0:
        return 0
    if age_days <= 30:
        return 10
    if age_days <= 90:
        return 8
    if age_days <= 180:
        return 5
    if age_days <= 365:
        return 2
    return 0


def _market_evidence(symbol: str, prices: Mapping[str, Mapping[str, Any]], histories: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    raw = prices.get(symbol) or {}
    close = _safe_float(raw.get("close"))
    trade_status = raw.get("trade_status")
    tradable = close is not None and close > 0 and trade_status in (None, 0, "0")
    amount = _safe_float(raw.get("amount"))
    volume = _safe_float(raw.get("volume"))
    avg_amount = _safe_float(raw.get("average_20d_amount"))
    avg_volume = _safe_float(raw.get("average_20d_volume"))
    if avg_amount is None or avg_amount <= 0:
        rows = histories.get(symbol) or []
        amounts = [_safe_float(row.get("amount")) for row in rows[-20:]]
        amounts = [value for value in amounts if value is not None and value > 0]
        avg_amount = sum(amounts) / len(amounts) if amounts else None
    if avg_volume is None or avg_volume <= 0:
        rows = histories.get(symbol) or []
        volumes = [_safe_float(row.get("volume")) for row in rows[-20:]]
        volumes = [value for value in volumes if value is not None and value > 0]
        avg_volume = sum(volumes) / len(volumes) if volumes else None
    return {
        "date": _date_token(raw.get("date")),
        "close": close,
        "trade_status": trade_status,
        "is_tradable": tradable,
        "amount": amount,
        "volume": volume,
        "average_20d_amount": avg_amount,
        "average_20d_volume": avg_volume,
        "liquidity_status": "present" if avg_amount is not None else "missing",
    }


def _audit_component(audit: Mapping[str, Any] | None) -> tuple[int, str]:
    if not audit:
        return 5, "missing"
    if _truth(audit.get("warning_flag")):
        return 0, "warning"
    if _truth(audit.get("substantive_opinion_available")) and str(audit.get("evidence_status")) == "present":
        return 20, "clean"
    return 5, "missing"


def _fundamental_values(fundamental: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return fundamental if isinstance(fundamental, Mapping) else {}


def _context_flags(
    symbol: str,
    context_frames: Mapping[str, Any] | None,
    contracts: Any,
    as_of: str,
) -> dict[str, bool]:
    flags = {"repurchase": False, "placard": False, "shareholder_reduction": False, "material_contract": False}
    for api_name, key in (("get_repurchase", "repurchase"), ("get_stock_equity_placard", "placard")):
        frame = (context_frames or {}).get(api_name)
        if frame is None or getattr(frame, "empty", True) or "symbol" not in frame:
            continue
        subset = frame[frame["symbol"].astype(str).str.replace(".SS", ".SH") == symbol]
        if not subset.empty:
            flags[key] = True
    frame = (context_frames or {}).get("get_stock_shareholder_change")
    if frame is not None and not getattr(frame, "empty", True) and "symbol" in frame:
        subset = frame[frame["symbol"].astype(str).str.replace(".SS", ".SH") == symbol]
        for _, row in subset.iterrows():
            text = " ".join(str(row.get(field) or "") for field in ("direction", "reason", "progress", "shareholder_type"))
            if _REDUCTION_WORDS.search(text):
                flags["shareholder_reduction"] = True
                break
    if contracts is not None and not getattr(contracts, "empty", True) and "symbol" in contracts:
        subset = contracts[contracts["symbol"].astype(str).str.replace(".SS", ".SH") == symbol]
        for _, row in subset.iterrows():
            date_value = _date_token(row.get("info_date")) or _date_token(row.get("date"))
            if date_value and date_value <= as_of:
                flags["material_contract"] = True
                break
    return flags


def _name_for_symbol(symbol: str, name_map: Mapping[str, str] | None) -> str:
    if not name_map:
        return ""
    matches = sorted(str(name) for name, mapped in name_map.items() if _symbol(mapped) == symbol)
    return matches[0] if matches else ""


def _category(payload: Mapping[str, Any], result_type: str) -> str:
    situation = str(payload.get("situation_type") or "").lower()
    if situation in {"distress", "distress_turnaround"} or result_type in _DISTRESS_TYPES:
        return "distress"
    if situation in {"spin_off", "spin-off"} or result_type.startswith("spin_off"):
        return "spin_off"
    return "reorganization"


def _missing_evidence(payload: Mapping[str, Any], market: Mapping[str, Any], fundamental: Mapping[str, Any], audit: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    gates = payload.get("klarman_gates")
    if isinstance(gates, Mapping):
        values.extend(str(item) for item in gates.get("missing_required", []) if item)
    if market.get("close") is None:
        values.append("current_market_price")
    if market.get("average_20d_amount") is None:
        values.append("average_daily_amount")
    if not fundamental or fundamental.get("double_check") == "insufficient_evidence":
        values.append("current_fundamentals")
    if not audit or audit.get("evidence_status") in {None, "missing", "limited"}:
        values.append("current_audit_opinion")
    return sorted(set(values))


def _actions(missing: Iterable[str], category: str) -> list[str]:
    labels = {
        "current_market_price": "补齐决策日前可见的收盘价与交易状态",
        "average_daily_amount": "补齐 20 日成交额并估算冲击成本",
        "current_fundamentals": "补齐最新公开财报并复核利润、现金流和负债",
        "current_audit_opinion": "补齐最新实质性审计意见并核对警示事项",
        "deal_terms": "补齐交易对价、先决条件、融资和终止条款",
        "conservative_value": "建立保守估值并写明关键假设",
        "failure_value": "建立失败情景价值与损失上限",
        "capital_structure": "核对债务、优先顺位、稀释和或有负债",
        "liquidity": "核对停复牌、成交额和退出流动性",
        "symbol_mapping": "补齐证券代码唯一映射",
        "security_access": "核对二级市场实际可获得的证券权利",
    }
    output = [labels[item] for item in missing if item in labels]
    if category in {"reorganization", "spin_off"}:
        output.append("按失败压力不低于 30% 的假设进行分散研究")
    return list(dict.fromkeys(output))[:6]


def _candidate_base(
    *,
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
    symbol: str,
    name_map: Mapping[str, str] | None,
    category: str,
    event_date: str,
    score: int,
    breakdown: Mapping[str, Any],
    thesis: str,
    positive_signals: list[str],
    risk_flags: list[str],
    missing: list[str],
    market: Mapping[str, Any],
    fundamental: Mapping[str, Any],
    audit: Mapping[str, Any],
    evidence_basis: str,
) -> dict[str, Any]:
    confidence = "中" if score >= 80 and len(missing) <= 3 else "低"
    if market.get("average_20d_amount") is None:
        confidence = "低"
    event_id = str(record.get("target_id") or payload.get("event_id") or "")
    return {
        "rank": None,
        "symbol": symbol,
        "stock_name": _name_for_symbol(symbol, name_map),
        "event_id": event_id,
        "situation_type": category,
        "event_date": event_date,
        "research_score": score,
        "score": score,
        "confidence_level": confidence,
        "score_breakdown": dict(breakdown),
        "thesis": thesis,
        "positive_signals": positive_signals,
        "risk_flags": risk_flags,
        "missing_core_evidence": missing,
        "next_research_actions": _actions(missing, category),
        "current_market_evidence": dict(market),
        "current_fundamental_evidence": dict(fundamental),
        "current_audit_evidence": dict(audit),
        "underwriting_status": str(record.get("result_value") or payload.get("underwriting_status") or "underwriting_incomplete"),
        "research_evidence_basis": evidence_basis,
        "not_trade_signal": True,
    }


def _distress_candidate(
    record: Mapping[str, Any],
    *,
    as_of: str,
    fundamentals: Mapping[str, Mapping[str, Any]],
    audits: Mapping[str, Mapping[str, Any]],
    prices: Mapping[str, Mapping[str, Any]],
    histories: Mapping[str, list[Mapping[str, Any]]],
    name_map: Mapping[str, str] | None,
    context_frames: Mapping[str, Any] | None,
    contracts: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
    symbol = _symbol(payload.get("symbol"))
    if not symbol:
        return None, "missing_symbol"
    event_date = _event_date(payload, record, as_of)
    age_days = _age_days(event_date, as_of)
    if event_date and event_date > as_of:
        return None, "future_event"
    market = _market_evidence(symbol, prices, histories)
    if market.get("close") is None:
        return None, "missing_current_price"
    fundamental = _fundamental_values(fundamentals.get(symbol))
    audit = audits.get(symbol) if isinstance(audits.get(symbol), Mapping) else {}
    context = _context_flags(symbol, context_frames, contracts, as_of)
    event_state = str(payload.get("event_state") or "")
    event_points = 30 if event_state == "distress_marker_removed" else 10 if event_state == "distress_marker_active" else 0
    fundamental_points = sum(10 for key in ("profit_positive", "profit_improving", "cash_flow_positive") if _truth(fundamental.get(key)))
    audit_points, audit_status = _audit_component(audit)
    market_points = 5 if market.get("is_tradable") else 0
    recency_points = _recency_points(age_days)
    context_points = 5 if context["repurchase"] or context["placard"] else 0
    if context["shareholder_reduction"]:
        context_points -= 5
    breakdown = {
        "event_state": event_points,
        "fundamentals": fundamental_points,
        "audit_quality": audit_points,
        "current_tradable_price": market_points,
        "event_recency": recency_points,
        "capital_behavior_context": context_points,
        "total": max(0, min(100, event_points + fundamental_points + audit_points + market_points + recency_points + context_points)),
    }
    score = int(breakdown["total"])
    missing = _missing_evidence(payload, market, fundamental, audit)
    positive = []
    if event_state == "distress_marker_removed":
        positive.append("风险警示已撤销或状态改善")
    if _truth(fundamental.get("profit_positive")):
        positive.append("最新利润为正")
    if _truth(fundamental.get("profit_improving")):
        positive.append("利润同比改善")
    if _truth(fundamental.get("cash_flow_positive")):
        positive.append("经营现金流为正")
    if audit_status == "clean":
        positive.append("最新审计意见无实质性警示")
    risks = []
    if event_state == "distress_marker_active":
        risks.append("风险警示仍生效")
    if fundamental.get("double_check") == "fail":
        risks.append("财务交叉核验失败")
    if fundamental.get("cash_flow_positive") is False:
        risks.append("经营现金流为负")
    if audit_status == "warning":
        risks.append("审计意见含警示")
    if context["shareholder_reduction"]:
        risks.append("存在股东减持背景")
    if not market.get("is_tradable"):
        risks.append("当前不可交易或停牌")
    candidate = _candidate_base(
        record=record,
        payload=payload,
        symbol=symbol,
        name_map=name_map,
        category="distress",
        event_date=event_date or as_of,
        score=score,
        breakdown=breakdown,
        thesis="风险警示状态与当前财务证据出现改善，进入困境反转研究队列；仍需完成回收价值和资本结构承保。",
        positive_signals=positive,
        risk_flags=risks,
        missing=missing,
        market=market,
        fundamental=fundamental,
        audit=audit,
        evidence_basis="live_latest_public_by_as_of",
    )
    return candidate, None if score >= MINIMUM_SCORE else "below_threshold"


def _reorg_candidate(
    record: Mapping[str, Any],
    *,
    as_of: str,
    fundamentals: Mapping[str, Mapping[str, Any]],
    audits: Mapping[str, Mapping[str, Any]],
    prices: Mapping[str, Mapping[str, Any]],
    histories: Mapping[str, list[Mapping[str, Any]]],
    name_map: Mapping[str, str] | None,
    context_frames: Mapping[str, Any] | None,
    contracts: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
    symbol = _symbol(payload.get("symbol"))
    mapping = str(payload.get("symbol_mapping") or "")
    if not symbol:
        return None, "unmapped_event"
    event_date = _event_date(payload, record, as_of)
    age_days = _age_days(event_date, as_of)
    if event_date and event_date > as_of:
        return None, "future_event"
    market = _market_evidence(symbol, prices, histories)
    if market.get("close") is None:
        return None, "missing_current_price"
    fundamental = _fundamental_values(fundamentals.get(symbol))
    audit = audits.get(symbol) if isinstance(audits.get(symbol), Mapping) else {}
    context = _context_flags(symbol, context_frames, contracts, as_of)
    situation = _category(payload, str(record.get("result_type") or ""))
    title = " ".join(str(payload.get(key) or "") for key in ("announcement_title", "announcement_content", "project_name", "contract_title"))
    # Award catalyst points only from explicit provenance. A symbol alone is
    # not proof of a unique text mapping, and a result type alone is not proof
    # that the event came from the CSRC approval feed.
    mapping_points = 10 if mapping == "unique_name_match" else 0
    csrc_points = 10 if (
        _truth(payload.get("csrc_event"))
        or str(payload.get("event_source") or "") == "get_stock_csrc_approval"
    ) else 0
    keyword_points = 10 if (_SPINOFF_WORDS.search(title) if situation == "spin_off" else _REORG_WORDS.search(title)) else 0
    fundamental_status = str(fundamental.get("double_check") or "insufficient_evidence")
    fundamental_points = 25 if fundamental_status == "pass" else 8 if fundamental_status == "insufficient_evidence" else 0
    audit_points, audit_status = _audit_component(audit)
    market_points = 5 if market.get("is_tradable") else 0
    recency_points = _recency_points(age_days)
    context_points = 0
    if context["material_contract"]:
        context_points += 5
    if context["repurchase"] or context["placard"]:
        context_points += 5
    if context["shareholder_reduction"]:
        context_points -= 5
    breakdown = {
        "symbol_mapping": mapping_points,
        "csrc_catalyst": csrc_points,
        "clear_reorg_or_spinoff_keyword": keyword_points,
        "current_fundamentals": fundamental_points,
        "audit_quality": audit_points,
        "current_tradable_price": market_points,
        "event_recency": recency_points,
        "context": context_points,
        "total": max(0, min(100, mapping_points + csrc_points + keyword_points + fundamental_points + audit_points + market_points + recency_points + context_points)),
    }
    score = int(breakdown["total"])
    missing = _missing_evidence(payload, market, fundamental, audit)
    positive = ["证监会批文或监管催化剂已出现"]
    if mapping_points:
        positive.append("证券代码已唯一映射")
    if keyword_points:
        positive.append("事件文本明确指向重组或分拆")
    if fundamental_status == "pass":
        positive.append("当前财务交叉核验通过")
    if audit_status == "clean":
        positive.append("当前审计意见无实质性警示")
    risks = ["失败压力不低于 30%，必须分散研究"]
    if fundamental_status == "fail":
        risks.append("当前财务交叉核验失败")
    if audit_status == "warning":
        risks.append("审计意见含警示")
    if not market.get("is_tradable"):
        risks.append("当前不可交易或停牌")
    if context["shareholder_reduction"]:
        risks.append("存在股东减持背景")
    candidate = _candidate_base(
        record=record,
        payload=payload,
        symbol=symbol,
        name_map=name_map,
        category=situation,
        event_date=event_date or as_of,
        score=score,
        breakdown=breakdown,
        thesis="监管催化剂已出现，当前财务与市场证据支持进入重组/分拆研究队列；交易条款、失败价值和估值仍未替代承保。",
        positive_signals=positive,
        risk_flags=risks,
        missing=missing,
        market=market,
        fundamental=fundamental,
        audit=audit,
        evidence_basis="live_latest_public_by_as_of",
    )
    return candidate, None if score >= MINIMUM_SCORE else "below_threshold"


def _placement_risk(
    record: Mapping[str, Any],
    *,
    as_of: str,
    prices: Mapping[str, Mapping[str, Any]],
    histories: Mapping[str, list[Mapping[str, Any]]],
    name_map: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
    symbol = _symbol(payload.get("symbol"))
    if not symbol:
        return None
    market = _market_evidence(symbol, prices, histories)
    unlock_rows = [item for item in payload.get("unlock_evidence", []) if isinstance(item, Mapping) and _date_token(item.get("relieve_date"))]
    unlock_rows.sort(key=lambda item: str(item.get("relieve_date")))
    nearest = unlock_rows[0] if unlock_rows else {}
    unlock_date = _date_token(nearest.get("relieve_date"))
    days = _age_days(as_of, unlock_date) if unlock_date else None
    if days is None:
        days = 999
    ratio = _safe_float(payload.get("unlock_overhang_ratio"))
    gain = _safe_float(payload.get("participant_unrealized_gain"))
    unlock_shares = _safe_float(payload.get("unlock_shares"))
    if unlock_shares is None:
        unlock_shares = sum(
            _safe_float(item.get("actual_relieve_shares"))
            or _safe_float(item.get("relieve_shares"))
            or 0.0
            for item in unlock_rows
        )
    close = _safe_float(market.get("close"))
    avg_amount = _safe_float(market.get("average_20d_amount"))
    absorption_days = unlock_shares * close / avg_amount if close and avg_amount and avg_amount > 0 else None
    overhang_points = min(40, max(0, ratio * 100 if ratio is not None else 0))
    gain_points = min(25, max(0, gain * 100 if gain is not None else 0))
    proximity_points = 20 if days <= 30 else 15 if days <= 60 else 10 if days <= 90 else 5 if days <= 180 else 0
    absorption_points = min(15, max(0, absorption_days / 20 * 15)) if absorption_days is not None else 0
    breakdown = {
        "unlock_overhang_ratio": round(overhang_points, 2),
        "participant_gain": round(gain_points, 2),
        "unlock_proximity": proximity_points,
        "liquidity_absorption": round(absorption_points, 2),
        "total": int(round(overhang_points + gain_points + proximity_points + absorption_points)),
    }
    missing = []
    if ratio is None:
        missing.append("unlock_overhang_ratio")
    if gain is None:
        missing.append("participant_unrealized_gain")
    if absorption_days is None:
        missing.append("average_daily_amount")
    if str(payload.get("unlock_match_confidence") or "") != "medium":
        missing.append("unlock_linkage")
    risk_flags = ["定增解禁可能形成供给冲击", "发行价是参与者历史成本，不是二级市场成本"]
    if absorption_days is not None and absorption_days > 10:
        risk_flags.append(f"按 20 日成交额估算需约 {absorption_days:.1f} 天消化")
    return {
        "rank": None,
        "symbol": symbol,
        "stock_name": _name_for_symbol(symbol, name_map),
        "event_id": str(record.get("target_id") or payload.get("event_id") or ""),
        "situation_type": "private_placement_supply_risk",
        "event_date": unlock_date or _date_token(payload.get("listed_date")) or as_of,
        "risk_score": breakdown["total"],
        "research_score": breakdown["total"],
        "score": breakdown["total"],
        "confidence_level": "中" if not missing else "低",
        "score_breakdown": breakdown,
        "thesis": "定增参与者浮盈与临近解禁叠加，优先观察潜在供给压力与成交额消化能力。",
        "positive_signals": [
            f"参与者浮盈约 {gain * 100:.1f}%" if gain is not None else "参与者浮盈待补证",
            f"解禁占流通盘约 {ratio * 100:.1f}%" if ratio is not None else "解禁占流通盘待补证",
        ],
        "risk_flags": risk_flags,
        "missing_core_evidence": sorted(set(missing)),
        "next_research_actions": [
            "核对解禁原因、参与者身份和解禁数量",
            "用 20 日成交额复核供给消化天数",
            "检查解禁日前后停牌、价格和成交额变化",
        ],
        "current_market_evidence": {**market, "unlock_absorption_days": absorption_days},
        "current_fundamental_evidence": payload.get("fundamental_double_check") or {},
        "current_audit_evidence": {},
        "underwriting_status": str(record.get("result_value") or "risk_watch"),
        "research_evidence_basis": "live_latest_public_by_as_of",
        "not_trade_signal": True,
    }


def _distress_risk(
    record: Mapping[str, Any],
    *,
    as_of: str,
    fundamentals: Mapping[str, Mapping[str, Any]],
    audits: Mapping[str, Mapping[str, Any]],
    prices: Mapping[str, Mapping[str, Any]],
    histories: Mapping[str, list[Mapping[str, Any]]],
    name_map: Mapping[str, str] | None,
    context_frames: Mapping[str, Any] | None,
    contracts: Any,
) -> dict[str, Any] | None:
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
    symbol = _symbol(payload.get("symbol"))
    if not symbol:
        return None
    fundamental = _fundamental_values(fundamentals.get(symbol))
    audit = audits.get(symbol) if isinstance(audits.get(symbol), Mapping) else {}
    context = _context_flags(symbol, context_frames, contracts, as_of)
    event_state = str(payload.get("event_state") or "")
    breakdown = {
        "active_distress_marker": 35 if event_state == "distress_marker_active" else 0,
        "audit_warning": 25 if _truth(audit.get("warning_flag")) else 0,
        "financial_check_failed": 20 if fundamental.get("double_check") == "fail" else 0,
        "negative_operating_cash_flow": 10 if fundamental.get("cash_flow_positive") is False else 0,
        "shareholder_reduction": 10 if context["shareholder_reduction"] else 0,
    }
    breakdown["total"] = min(100, sum(int(value) for value in breakdown.values()))
    if breakdown["total"] < 30:
        return None
    market = _market_evidence(symbol, prices, histories)
    event_date = _event_date(payload, record, as_of) or as_of
    risks = []
    if breakdown["active_distress_marker"]:
        risks.append("风险警示仍生效")
    if breakdown["audit_warning"]:
        risks.append("审计意见含警示")
    if breakdown["financial_check_failed"]:
        risks.append("财务交叉核验失败")
    if breakdown["negative_operating_cash_flow"]:
        risks.append("经营现金流为负")
    if breakdown["shareholder_reduction"]:
        risks.append("存在股东减持背景")
    missing = _missing_evidence(payload, market, fundamental, audit)
    return {
        "rank": None,
        "symbol": symbol,
        "stock_name": _name_for_symbol(symbol, name_map),
        "event_id": str(record.get("target_id") or payload.get("event_id") or ""),
        "situation_type": "distress",
        "event_date": event_date,
        "risk_score": breakdown["total"],
        "research_score": breakdown["total"],
        "score": breakdown["total"],
        "confidence_level": "中" if len(missing) <= 2 else "低",
        "score_breakdown": breakdown,
        "thesis": "困境状态、审计或财务核验出现风险信号，进入独立风险观察，不与研究机会混排。",
        "positive_signals": [],
        "risk_flags": risks,
        "missing_core_evidence": missing,
        "next_research_actions": _actions(missing, "distress"),
        "current_market_evidence": market,
        "current_fundamental_evidence": dict(fundamental),
        "current_audit_evidence": dict(audit),
        "underwriting_status": str(record.get("result_value") or payload.get("underwriting_status") or "underwriting_incomplete"),
        "research_evidence_basis": "live_latest_public_by_as_of",
        "not_trade_signal": True,
    }


def _sort_key(item: Mapping[str, Any]) -> tuple[int, int, str, str]:
    date_value = _date_token(item.get("event_date"))
    return (
        -int(item.get("score") or 0),
        -int(date_value) if date_value else 0,
        str(item.get("symbol") or ""),
        str(item.get("event_id") or ""),
    )


def build_research_digest(
    records: Iterable[Mapping[str, Any]],
    *,
    as_of: str,
    fundamentals: Mapping[str, Mapping[str, Any]] | None = None,
    audits: Mapping[str, Mapping[str, Any]] | None = None,
    prices: Mapping[str, Mapping[str, Any]] | None = None,
    trading_histories: Mapping[str, list[Mapping[str, Any]]] | None = None,
    name_map: Mapping[str, str] | None = None,
    context_frames: Mapping[str, Any] | None = None,
    contracts: Any = None,
) -> dict[str, Any]:
    fundamentals = fundamentals or {}
    audits = audits or {}
    prices = prices or {}
    trading_histories = trading_histories or {}
    records = list(records)
    exclusions: Counter[str] = Counter()
    opportunities: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    unmapped = 0
    for record in records:
        result_type = str(record.get("result_type") or "")
        payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
        if result_type in _REORG_TYPES and not _symbol(payload.get("symbol")):
            unmapped += 1
        if result_type in _DISTRESS_TYPES:
            candidate, reason = _distress_candidate(
                record,
                as_of=as_of,
                fundamentals=fundamentals,
                audits=audits,
                prices=prices,
                histories=trading_histories,
                name_map=name_map,
                context_frames=context_frames,
                contracts=contracts,
            )
            if candidate is not None:
                opportunities.append(candidate)
            elif reason:
                exclusions[reason] += 1
            risk = _distress_risk(
                record,
                as_of=as_of,
                fundamentals=fundamentals,
                audits=audits,
                prices=prices,
                histories=trading_histories,
                name_map=name_map,
                context_frames=context_frames,
                contracts=contracts,
            )
            if risk is not None:
                risks.append(risk)
        elif result_type in _REORG_TYPES:
            candidate, reason = _reorg_candidate(
                record,
                as_of=as_of,
                fundamentals=fundamentals,
                audits=audits,
                prices=prices,
                histories=trading_histories,
                name_map=name_map,
                context_frames=context_frames,
                contracts=contracts,
            )
            if candidate is not None:
                opportunities.append(candidate)
            elif reason:
                exclusions[reason] += 1
        elif result_type in _PLACEMENT_TYPES:
            risk = _placement_risk(
                record,
                as_of=as_of,
                prices=prices,
                histories=trading_histories,
                name_map=name_map,
            )
            if risk is not None:
                risks.append(risk)
        elif result_type not in {"coverage_gap", "scan_summary", "research_digest"}:
            exclusions["unsupported_event_type"] += 1

    opportunities.sort(key=_sort_key)
    shortlist: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    selected_symbols: set[str] = set()
    for item in opportunities:
        category = str(item.get("situation_type") or "unknown")
        if len(shortlist) >= SHORTLIST_LIMIT:
            exclusions["shortlist_limit"] += 1
            continue
        if category_counts[category] >= CATEGORY_CAP:
            exclusions["category_cap"] += 1
            continue
        if str(item.get("symbol") or "") in selected_symbols:
            exclusions["duplicate_symbol"] += 1
            continue
        if int(item.get("score") or 0) < MINIMUM_SCORE:
            exclusions["below_threshold"] += 1
            continue
        category_counts[category] += 1
        selected_symbols.add(str(item.get("symbol") or ""))
        item["rank"] = len(shortlist) + 1
        shortlist.append(item)
    risks.sort(key=_sort_key)
    risk_watchlist: list[dict[str, Any]] = []
    risk_symbols: set[str] = set()
    for item in risks:
        symbol = str(item.get("symbol") or "")
        if symbol in risk_symbols:
            continue
        risk_symbols.add(symbol)
        risk_watchlist.append(item)
        if len(risk_watchlist) >= RISK_LIMIT:
            break
    for index, item in enumerate(risk_watchlist, start=1):
        item["rank"] = index

    digest = {
        "methodology_id": METHODOLOGY_ID,
        "as_of_date": as_of,
        "evidence_time_basis": "live_latest_public_by_as_of",
        "historical_replay_time_basis": "event_time_point_in_time_only",
        "not_trade_signal": True,
        "shortlist_limit": SHORTLIST_LIMIT,
        "minimum_score": MINIMUM_SCORE,
        "category_cap": CATEGORY_CAP,
        "shortlist": shortlist,
        "risk_watchlist": risk_watchlist,
        "excluded_summary": {
            "opportunity_input_count": len(opportunities),
            "shortlist_count": len(shortlist),
            "risk_watch_count": len(risk_watchlist),
            "by_reason": dict(sorted(exclusions.items())),
        },
        "unmapped_event_count": unmapped,
        "score_rules": {
            "distress": "状态30 + 财务30 + 审计20 + 市场与时效15 + 资本行为5，最低60分",
            "reorganization_or_spinoff": "催化剂30 + 当前财务25 + 审计20 + 市场与时效15 + 上下文10，最低60分",
            "private_placement": "仅进入独立供给风险观察，不进入机会榜",
        },
    }
    return _json_safe(digest)


__all__ = ["build_research_digest", "METHODOLOGY_ID", "SHORTLIST_LIMIT", "RISK_LIMIT", "CATEGORY_CAP", "MINIMUM_SCORE"]
