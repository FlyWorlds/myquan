"""构建并去重特殊情形候选状态机。"""

from __future__ import annotations

try:
    from .core import (
        Any,
        DISTRESS_PATTERN,
        Mapping,
        PLACEMENT_UNLOCK_PATTERN,
        REORGANIZATION_PATTERN,
        SPINOFF_PATTERN,
        datetime,
        pd,
        re,
        timedelta,
    )
    from . import evidence as evidence
    from .evidence import (
        _first_column,
        _scalar,
        _first_value,
        _text,
        _row_text,
        _stable_id,
        _date_token,
        _max_date,
        _event_identity,
        _evidence_matrix,
        _json_safe,
        _attach_event_metadata,
        _record_dates,
        _assert_no_trade_directives,
        _stock_name_map,
        _map_text_to_symbol,
        _market_evidence,
        _latest_prices,
        _trading_state_evidence,
        _numeric,
        _fundamental_checks,
        _audit_evidence,
    )
    from .underwriting import apply_underwriting
except ImportError:  # 支持直接执行脚本
    from core import (
        Any,
        DISTRESS_PATTERN,
        Mapping,
        PLACEMENT_UNLOCK_PATTERN,
        REORGANIZATION_PATTERN,
        SPINOFF_PATTERN,
        datetime,
        pd,
        re,
        timedelta,
    )
    import evidence as evidence
    from evidence import (
        _first_column,
        _scalar,
        _first_value,
        _text,
        _row_text,
        _stable_id,
        _date_token,
        _max_date,
        _event_identity,
        _evidence_matrix,
        _json_safe,
        _attach_event_metadata,
        _record_dates,
        _assert_no_trade_directives,
        _stock_name_map,
        _map_text_to_symbol,
        _market_evidence,
        _latest_prices,
        _trading_state_evidence,
        _numeric,
        _fundamental_checks,
        _audit_evidence,
    )
    from underwriting import apply_underwriting
__all__ = ['_placement_candidates', '_regulatory_candidates', '_contract_candidates', 'attach_material_contract_context', 'attach_panda_non_core_context', '_distress_candidates', '_deduplicate']

PANDA_NON_CORE_CONTEXT_FIELDS = {
    "get_repurchase": (
        "date", "procedure", "purpose", "buy_back_start_date", "buy_back_end_date",
        "write_off_date", "buy_back_volume", "value_floor", "value_ceiling",
        "price_floor", "price_ceiling", "buy_back_percent", "buy_back_mode",
    ),
    "get_stock_equity_placard": (
        "info_date", "shareholder_name", "shareholder_type", "actual_controller",
        "begin_date", "end_date", "increase_num", "total_share_ratio",
        "average_price", "share_holding_ratio", "increase_plan",
    ),
    "get_stock_shareholder_change": (
        "info_date", "first_info_date", "progress", "begin_date", "end_date",
        "shareholder_name", "shareholder_type", "direction", "change_up_limit",
        "ratio_up_limit", "reason", "value_up_limit", "value_down_limit",
        "price_down_limit", "price_up_limit",
    ),
}

def _placement_candidates(
    placements: pd.DataFrame,
    restrictions: pd.DataFrame,
    prices: Mapping[str, Mapping[str, Any]],
    fundamentals: Mapping[str, Mapping[str, Any]],
    as_of: str,
    unlock_days: int,
    discount_threshold: float,
    float_shares: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if placements.empty:
        return candidates
    as_of_dt = datetime.strptime(as_of, "%Y%m%d")
    max_unlock = (as_of_dt + timedelta(days=unlock_days)).strftime("%Y%m%d")
    float_shares = float_shares or {}
    for _, row in placements.iterrows():
        symbol = _text(row.get("symbol")).replace(".SS", ".SH")
        issue_price = pd.to_numeric(pd.Series([row.get("issue_price")]), errors="coerce").iloc[0]
        price = prices.get(symbol)
        discount = None
        if price and pd.notna(issue_price) and float(price["close"]) > 0:
            discount = (float(price["close"]) - float(issue_price)) / float(price["close"])
        unlock = pd.DataFrame()
        if not restrictions.empty and "symbol" in restrictions:
            unlock = restrictions[restrictions["symbol"].astype(str).str.replace(".SS", ".SH") == symbol]
            if "relieve_reason" in unlock:
                unlock = unlock[
                    unlock["relieve_reason"].astype(str).str.contains(PLACEMENT_UNLOCK_PATTERN, na=False)
                ]
            if "relieve_date" in unlock:
                dates = unlock["relieve_date"].astype(str)
                unlock = unlock[(dates >= as_of) & (dates <= max_unlock)]
        listed_date = _date_token(row.get("listed_date"))
        unlock_records: list[dict[str, Any]] = []
        for _, item in unlock.iterrows():
            relieve_date = _date_token(item.get("relieve_date"))
            lockup_days = None
            if listed_date and relieve_date:
                lockup_days = (
                    datetime.strptime(relieve_date, "%Y%m%d")
                    - datetime.strptime(listed_date, "%Y%m%d")
                ).days
            chronology_ok = lockup_days is None or lockup_days >= 0
            plausible_lockup = lockup_days is not None and 150 <= lockup_days <= 1200
            link_confidence = (
                "medium"
                if listed_date and chronology_ok and plausible_lockup
                else "low"
            )
            unlock_records.append(
                {
                    "source_publish_date": _date_token(item.get("date")),
                    "relieve_date": relieve_date,
                    "shareholder": _scalar(item.get("shareholder")),
                    "shareholder_type": _scalar(item.get("shareholder_type")),
                    "relieve_shares": _numeric(item, ["relieve_shares"]),
                    "actual_relieve_shares": _numeric(item, ["actual_relieve_shares"]),
                    "relieve_reason": _scalar(item.get("relieve_reason")),
                    "days_from_placement_listing": lockup_days,
                    "chronology_ok": chronology_ok,
                    "plausible_lockup_window": plausible_lockup,
                    "link_confidence": link_confidence,
                }
            )
        unlock_records.sort(
            key=lambda item: (
                _text(item.get("relieve_date")),
                _text(item.get("shareholder")),
            )
        )
        linked_unlocks = [item for item in unlock_records if item["link_confidence"] == "medium"]
        link_confidence = "medium" if linked_unlocks else "low" if unlock_records else "none"
        participant_gain = None
        if price and pd.notna(issue_price) and float(issue_price) > 0:
            participant_gain = float(price["close"]) / float(issue_price) - 1
        fundamental = fundamentals.get(symbol, {"double_check": "insufficient_evidence"})
        if not (
            participant_gain is not None
            and participant_gain > discount_threshold
            and bool(unlock_records)
        ):
            continue
        evidence_status = "risk_watch"
        unlock_shares = sum(
            float(item.get("actual_relieve_shares") or item.get("relieve_shares") or 0)
            for item in unlock_records
        )
        float_share_count = float_shares.get(symbol)
        unlock_overhang_ratio = (
            unlock_shares / float_share_count
            if float_share_count and float_share_count > 0
            else None
        )
        anchor = _first_value(
            row.get("announcement_date"), row.get("listed_date"), row.get("approval_date")
        )
        event_id, revision_id = _event_identity(
            "private_placement_unlock",
            symbol,
            [row.get("issue_type"), anchor],
            [
                row.get("announcement_date"),
                row.get("approval_date"),
                row.get("listed_date"),
                row.get("issue_status"),
                row.get("issued_shares"),
                row.get("issue_price"),
                unlock_records,
            ],
        )
        lifecycle = [
            {"stage": stage, "date": date_value}
            for stage, value in (
                ("announced", row.get("announcement_date")),
                ("approved", row.get("approval_date")),
                ("listed", row.get("listed_date")),
            )
            if (date_value := _date_token(value))
        ]
        lifecycle.extend(
            {"stage": "unlock_scheduled", "date": item["relieve_date"]}
            for item in unlock_records
            if item.get("relieve_date")
        )
        event_state = (
            "unlock_imminent"
            if unlock_records
            else "listed"
            if listed_date
            else "approved"
            if _date_token(row.get("approval_date"))
            else "announced"
        )
        completeness = _evidence_matrix(
            {
                "event_anchor": (True, bool(_date_token(anchor)), "Panda 定增日期"),
                "market_price": (True, price is not None, "截止日当日或之前的 Panda 收盘价"),
                "unlock_linkage": (
                    True,
                    link_confidence == "medium",
                    "证券代码、解禁原因、日期窗口、时序与锁定期合理性",
                ),
                "fundamentals": (
                    True,
                    fundamental.get("double_check") != "insufficient_evidence",
                    "净利润与经营现金流交叉核验",
                ),
            }
        )
        payload = {
            "symbol": symbol,
            "situation_type": "private_placement_unlock",
            "evidence_status": evidence_status,
            "discovery_status": "risk_watch",
            "underwriting_status": "not_applicable",
            "access_assumption": "secondary_market_investor",
            "announcement_date": row.get("announcement_date"),
            "approval_date": row.get("approval_date"),
            "listed_date": row.get("listed_date"),
            "issue_status": row.get("issue_status"),
            "issue_price": None if pd.isna(issue_price) else float(issue_price),
            "market_price": price,
            "issue_discount_to_market": discount,
            "participant_unrealized_gain": participant_gain,
            "placement_gain_alert_threshold": discount_threshold,
            "unlock_window_days": unlock_days,
            "unlock_evidence": unlock_records,
            "unlock_match_confidence": link_confidence,
            "unlock_shares": unlock_shares,
            "float_shares": float_share_count,
            "unlock_overhang_ratio": unlock_overhang_ratio,
            "unlock_linkage_limit": (
                "Panda 限售股记录不提供定增交易标识，因此关联置信度不能标记为高。"
            ),
            "fundamental_double_check": fundamental,
            "risk_note": (
                "发行价是定增参与者的历史成本，不是二级市场买方可获得的套利价格；解禁属于供给风险。"
            ),
            "deal_terms": {},
            "valuation": {
                "conservative_value": None,
                "discount_to_conservative_value": None,
            },
            "downside_case": {
                "break_value": None,
                "permanent_loss_pct": None,
            },
            "klarman_gates": {
                "matrix": {},
                "missing_required": [],
                "not_applicable_reason": "secondary_market_supply_risk_only",
            },
            "risk_budget_inputs": {
                "worst_case_loss_pct": None,
                "liquidity_bucket": None,
                "dependency_tags": ["placement_unlock", "supply_overhang"],
                "diversification_required": False,
            },
        }
        _attach_event_metadata(
            payload,
            event_id=event_id,
            revision_id=revision_id,
            event_state=event_state,
            lifecycle=lifecycle,
            completeness=completeness,
        )
        actual_source_date = _max_date(
            row.get("announcement_date"),
            row.get("approval_date"),
            price.get("date") if price else None,
            *(item.get("source_publish_date") for item in unlock_records),
            fallback=as_of,
        )
        payload["knowledge_cutoff"] = actual_source_date
        payload["evidence_available_dates"] = sorted(
            {
                value
                for value in [
                    _date_token(anchor),
                    price.get("date") if price else None,
                    *(item.get("source_publish_date") for item in unlock_records),
                ]
                if value
            }
        )
        candidates.append(
            {
                "target_id": event_id,
                "result_type": "private_placement_supply_risk",
                "result_value": evidence_status,
                "payload": payload,
                **_record_dates(
                    source_data_date=str(price.get("date") if price else actual_source_date),
                    actual_source_date=actual_source_date,
                    completeness=completeness,
                ),
            }
        )
    return candidates

def _regulatory_candidates(
    approvals: pd.DataFrame,
    name_map: Mapping[str, str],
    fundamentals: Mapping[str, Mapping[str, Any]],
    as_of: str,
    trading_histories: Mapping[str, list[dict[str, Any]]] | None = None,
    allowed_symbols: set[str] | None = None,
    minimum_margin_of_safety: float | None = None,
    failure_probability_stress: float | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    trading_histories = trading_histories or {}
    for _, row in approvals.iterrows():
        text = _row_text(row, ["announcement_title", "announcement_content"])
        situation = (
            "spin_off" if SPINOFF_PATTERN.search(text) else "reorganization" if REORGANIZATION_PATTERN.search(text) else None
        )
        if situation is None:
            continue
        symbol, mapping_status = _map_text_to_symbol(text, name_map)
        if allowed_symbols is not None and symbol not in allowed_symbols:
            continue
        fundamental = fundamentals.get(symbol or "", {"double_check": "insufficient_evidence"})
        event_date = _date_token(row.get("publish_date")) or as_of
        if str(fundamental.get("available_date") or "") > event_date:
            fundamental = {"double_check": "insufficient_evidence"}
        trading = _trading_state_evidence(
            symbol, event_date, trading_histories, as_of
        )
        valuation_ready = (
            situation != "spin_off"
            or bool(symbol)
            and any(
                _scalar(row.get(field)) is not None
                for field in ("transaction_amount", "valuation", "consideration")
            )
        )
        evidence_status = "underwriting_incomplete" if symbol else "insufficient_evidence"
        native_anchor = _first_value(
            row.get("announcement_number"), row.get("announcement_title")
        )
        event_id, revision_id = _event_identity(
            situation,
            symbol,
            ["csrc_approval", native_anchor],
            [
                row.get("publish_date"),
                row.get("announcement_level"),
                row.get("announcement_category"),
                row.get("announcement_content"),
                mapping_status,
            ],
        )
        lifecycle = [{"stage": "regulatory_catalyst_published", "date": event_date}]
        lifecycle.extend(
            {"stage": "trading_suspended", "date": value}
            for value in trading["suspension_dates"]
        )
        lifecycle.extend(
            {"stage": "trading_resumed", "date": value}
            for value in trading["resumption_dates"]
        )
        event_state = (
            "resumed_after_suspension"
            if trading["resumption_dates"]
            else "trading_suspended"
            if trading["suspension_dates"]
            else "regulatory_catalyst_published"
        )
        completeness = _evidence_matrix(
            {
                "event_anchor": (True, bool(native_anchor), "证监会批文编号或标题"),
                "symbol_mapping": (
                    True,
                    mapping_status == "unique_name_match",
                    "Panda 公司名称唯一映射",
                ),
                "fundamentals": (
                    True,
                    fundamental.get("double_check") != "insufficient_evidence",
                    "净利润与经营现金流交叉核验",
                ),
                "trading_state": (
                    situation == "reorganization",
                    trading["evidence_status"] == "present",
                    "催化剂日期前后的 Panda 日线交易状态",
                ),
                "valuation_inputs": (
                    situation == "spin_off",
                    valuation_ready,
                    "可识别主体与交易估值输入",
                ),
            }
        )
        payload = {
            "symbol": symbol,
            "situation_type": situation,
            "event_source": "get_stock_csrc_approval",
            "csrc_event": True,
            "evidence_status": evidence_status,
            "discovery_status": "event_lead",
            "access_assumption": "secondary_market_equity",
            "symbol_mapping": mapping_status,
            "publish_date": row.get("publish_date"),
            "publish_institution": row.get("publish_institution"),
            "announcement_category": row.get("announcement_category"),
            "announcement_level": row.get("announcement_level"),
            "announcement_title": row.get("announcement_title"),
            "announcement_number": row.get("announcement_number"),
            "announcement_link": row.get("announcement_link"),
            "attachment_link": row.get("attachment_link"),
            "fundamental_double_check": fundamental,
            "trading_state_evidence": trading,
            "valuation_ready": valuation_ready if situation == "spin_off" else None,
            "valuation_missing_inputs": (
                []
                if situation != "spin_off" or valuation_ready
                else ["transaction_valuation", "separable_subsidiary_value"]
            ),
            "risk_note": (
                "监管文件是催化剂信号，不能证明交易一定完成。"
            ),
        }
        underwriting = apply_underwriting(
            {
                "symbol": symbol,
                "situation_type": situation,
                "market_price": None,
                "deal_terms": {
                    "consideration_value": _first_value(
                        row.get("consideration"), row.get("transaction_amount")
                    ),
                    "conditions_verified": False,
                    "financing_verified": False,
                    "expected_close_date": None,
                },
                "valuation": {},
                "downside_case": {},
                "capital_structure": {"verified": False},
                "legal_accounting": {"verified": False},
                "liquidity": {"verified": False},
                "catalyst": {"verified": bool(native_anchor)},
                "knowledge_cutoff": event_date,
            },
            minimum_margin_of_safety=minimum_margin_of_safety,
            failure_probability_stress=failure_probability_stress,
        )
        payload.update(underwriting)
        if evidence_status == "insufficient_evidence":
            payload["underwriting_status"] = "underwriting_incomplete"
        _attach_event_metadata(
            payload,
            event_id=event_id,
            revision_id=revision_id,
            event_state=event_state,
            lifecycle=lifecycle,
            completeness=completeness,
        )
        actual_source_date = event_date
        payload["knowledge_cutoff"] = event_date
        payload["evidence_available_dates"] = [event_date]
        candidates.append(
            {
                "target_id": event_id,
                "result_type": f"{situation}_event",
                "result_value": (
                    evidence_status
                    if evidence_status == "insufficient_evidence"
                    else payload["underwriting_status"]
                ),
                "payload": payload,
                **_record_dates(
                    source_data_date=event_date,
                    actual_source_date=actual_source_date,
                    completeness=completeness,
                ),
            }
        )
    return candidates

def _contract_candidates(
    contracts: pd.DataFrame,
    fundamentals: Mapping[str, Mapping[str, Any]],
    as_of: str,
    trading_histories: Mapping[str, list[dict[str, Any]]] | None = None,
    minimum_margin_of_safety: float | None = None,
    failure_probability_stress: float | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    trading_histories = trading_histories or {}
    for _, row in contracts.iterrows():
        text = _row_text(row, ["project_name", "contract_title", "contract_party_a", "contract_party_b"])
        situation = (
            "spin_off" if SPINOFF_PATTERN.search(text) else "reorganization" if REORGANIZATION_PATTERN.search(text) else None
        )
        if situation is None:
            continue
        symbol = _text(row.get("symbol")).replace(".SS", ".SH")
        fundamental = fundamentals.get(symbol, {"double_check": "insufficient_evidence"})
        event_date = _date_token(row.get("info_date")) or as_of
        if str(fundamental.get("available_date") or "") > event_date:
            fundamental = {"double_check": "insufficient_evidence"}
        trading = _trading_state_evidence(
            symbol, event_date, trading_histories, as_of
        )
        valuation_ready = (
            situation != "spin_off"
            or bool(symbol)
            and any(
                _numeric(row, [field]) is not None
                for field in ("max_contract_amount", "min_contract_amount")
            )
        )
        evidence_status = "underwriting_incomplete"
        native_anchor = _first_value(
            row.get("info_id"), row.get("contract_title"), row.get("project_name")
        )
        event_id, revision_id = _event_identity(
            situation,
            symbol,
            ["material_contract", native_anchor],
            [
                row.get("info_date"),
                row.get("project_progress"),
                row.get("max_contract_amount"),
                row.get("min_contract_amount"),
                row.get("contract_party_a"),
                row.get("contract_party_b"),
            ],
        )
        lifecycle = [{"stage": "contract_disclosed", "date": event_date}]
        if _scalar(row.get("project_progress")) is not None:
            lifecycle.append(
                {
                    "stage": "project_progress_reported",
                    "date": event_date,
                    "value": _scalar(row.get("project_progress")),
                }
            )
        lifecycle.extend(
            {"stage": "trading_suspended", "date": value}
            for value in trading["suspension_dates"]
        )
        lifecycle.extend(
            {"stage": "trading_resumed", "date": value}
            for value in trading["resumption_dates"]
        )
        event_state = (
            "resumed_after_suspension"
            if trading["resumption_dates"]
            else "trading_suspended"
            if trading["suspension_dates"]
            else "contract_disclosed"
        )
        completeness = _evidence_matrix(
            {
                "event_anchor": (True, bool(native_anchor), "Panda 重大合同标识或标题"),
                "symbol_mapping": (True, bool(symbol), "合同原生证券代码"),
                "fundamentals": (
                    True,
                    fundamental.get("double_check") != "insufficient_evidence",
                    "净利润与经营现金流交叉核验",
                ),
                "trading_state": (
                    situation == "reorganization",
                    trading["evidence_status"] == "present",
                    "披露日前后的 Panda 日线交易状态",
                ),
                "valuation_inputs": (
                    situation == "spin_off",
                    valuation_ready,
                    "合同金额可作为有限估值输入",
                ),
            }
        )
        payload = {
            "symbol": symbol,
            "situation_type": situation,
            "evidence_status": evidence_status,
            "discovery_status": "event_lead",
            "access_assumption": "secondary_market_equity",
            "info_date": row.get("info_date"),
            "info_id": row.get("info_id"),
            "project_progress": row.get("project_progress"),
            "project_name": row.get("project_name"),
            "contract_title": row.get("contract_title"),
            "contract_party_a": row.get("contract_party_a"),
            "contract_party_b": row.get("contract_party_b"),
            "max_contract_amount": row.get("max_contract_amount"),
            "min_contract_amount": row.get("min_contract_amount"),
            "currency": row.get("currency"),
            "fundamental_double_check": fundamental,
            "trading_state_evidence": trading,
            "valuation_ready": valuation_ready if situation == "spin_off" else None,
            "valuation_missing_inputs": (
                []
                if situation != "spin_off" or valuation_ready
                else ["transaction_valuation", "separable_subsidiary_value"]
            ),
            "risk_note": "合同元数据无法确定交易对价或交割条件。",
        }
        payload.update(
            apply_underwriting(
                {
                    "symbol": symbol,
                    "situation_type": situation,
                    "market_price": None,
                    "deal_terms": {"contract_amount": _first_value(
                        row.get("max_contract_amount"), row.get("min_contract_amount")
                    )},
                    "valuation": {},
                    "downside_case": {},
                    "capital_structure": {"verified": False},
                    "legal_accounting": {"verified": False},
                    "liquidity": {"verified": False},
                    "catalyst": {"verified": bool(native_anchor)},
                    "knowledge_cutoff": event_date,
                },
                minimum_margin_of_safety=minimum_margin_of_safety,
                failure_probability_stress=failure_probability_stress,
            )
        )
        _attach_event_metadata(
            payload,
            event_id=event_id,
            revision_id=revision_id,
            event_state=event_state,
            lifecycle=lifecycle,
            completeness=completeness,
        )
        actual_source_date = event_date
        payload["knowledge_cutoff"] = event_date
        payload["evidence_available_dates"] = [event_date]
        candidates.append(
            {
                "target_id": event_id,
                "result_type": f"{situation}_event",
                "result_value": payload["underwriting_status"],
                "payload": payload,
                **_record_dates(
                    source_data_date=event_date,
                    actual_source_date=actual_source_date,
                    completeness=completeness,
                ),
            }
        )
    return candidates


def attach_material_contract_context(
    records: list[dict[str, Any]], contracts: pd.DataFrame, as_of: str
) -> None:
    """Attach exact-symbol contract rows as non-core context without promotion."""
    if contracts.empty:
        return
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for _, row in contracts.iterrows():
        symbol = _text(row.get("symbol")).replace(".SS", ".SH")
        info_date = _date_token(row.get("info_date"))
        text = _row_text(
            row,
            ["project_name", "contract_title", "contract_party_a", "contract_party_b"],
        )
        if not symbol or not info_date or info_date > as_of:
            continue
        if not (REORGANIZATION_PATTERN.search(text) or SPINOFF_PATTERN.search(text)):
            continue
        by_symbol.setdefault(symbol, []).append(
            {
                "info_date": info_date,
                "info_id": _scalar(row.get("info_id")),
                "project_name": _scalar(row.get("project_name")),
                "contract_title": _scalar(row.get("contract_title")),
                "project_progress": _scalar(row.get("project_progress")),
                "linkage": "exact_symbol_and_keyword_only",
                "evidence_role": "non_core_context",
            }
        )
    for record in records:
        if record.get("result_type") not in {"reorganization_event", "spin_off_event"}:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        matches = sorted(
            by_symbol.get(str(payload.get("symbol") or ""), []),
            key=lambda item: str(item["info_date"]),
            reverse=True,
        )
        if matches:
            payload["material_contract_context"] = matches[:10]
            payload["material_contract_context_note"] = (
                "重大合同仅按证券代码与关键词关联，不证明交易条款、估值或交割条件。"
            )


def attach_panda_non_core_context(
    records: list[dict[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    as_of: str,
) -> None:
    """Attach latest documented Panda context without creating or promoting events."""
    indexed: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for api_name, frame in frames.items():
        allowed_fields = PANDA_NON_CORE_CONTEXT_FIELDS.get(api_name)
        if not allowed_fields or frame.empty or "symbol" not in frame:
            continue
        for _, row in frame.iterrows():
            symbol = _text(row.get("symbol")).replace(".SS", ".SH")
            available_date = _date_token(
                _first_value(
                    row.get("info_date"),
                    row.get("date"),
                    row.get("announcement_date"),
                    row.get("publish_date"),
                )
            )
            if not symbol or not available_date or available_date > as_of:
                continue
            item: dict[str, Any] = {
                "source_api": api_name,
                "available_date": available_date,
                "evidence_role": "non_core_context",
            }
            for field in allowed_fields:
                value = _scalar(row.get(field))
                if value is not None:
                    item[field] = _json_safe(value)
            indexed.setdefault(api_name, {}).setdefault(symbol, []).append(item)

    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        symbol = str(payload.get("symbol") or "")
        if not symbol:
            continue
        context: dict[str, list[dict[str, Any]]] = {}
        for api_name in PANDA_NON_CORE_CONTEXT_FIELDS:
            rows = indexed.get(api_name, {}).get(symbol, [])
            if rows:
                context[api_name] = sorted(
                    rows,
                    key=lambda item: str(item["available_date"]),
                    reverse=True,
                )[:10]
        if context:
            payload["panda_non_core_context"] = context
            payload["panda_non_core_context_note"] = (
                "回购、举牌和股东增减持仅补充资本行为背景，不证明交易条款、保守价值或失败价值，也不得晋级候选。"
            )

def _distress_candidates(
    status_changes: pd.DataFrame,
    fundamentals: Mapping[str, Mapping[str, Any]],
    as_of: str,
    audits: Mapping[str, Mapping[str, Any]] | None = None,
    minimum_margin_of_safety: float | None = None,
    failure_probability_stress: float | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    audits = audits or {}
    if status_changes.empty:
        return candidates
    symbol_column = _first_column(status_changes, ["symbol", "stock_symbol"])
    if symbol_column is None:
        return candidates
    text_fields = [
        column
        for column in ["status", "type", "change_type", "change_reason", "name", "description"]
        if column in status_changes
    ]
    for _, row in status_changes.iterrows():
        text = _row_text(row, text_fields)
        if not DISTRESS_PATTERN.search(text):
            continue
        symbol = _text(row.get(symbol_column)).replace(".SS", ".SH")
        fundamental = fundamentals.get(symbol, {"double_check": "insufficient_evidence"})
        audit = audits.get(symbol, {"evidence_status": "missing", "warning_flag": None})
        audit_present = audit.get("evidence_status") == "present"
        evidence_status = "underwriting_incomplete"
        event_date = next(
            (row.get(column) for column in ["date", "change_date", "start_date", "info_date"] if column in row.index),
            as_of,
        )
        event_date = _date_token(event_date) or as_of
        if str(fundamental.get("available_date") or "") > event_date:
            fundamental = {"double_check": "insufficient_evidence"}
        native_type = _first_value(row.get("type"), row.get("change_type"), text)
        event_id, revision_id = _event_identity(
            "distress_turnaround",
            symbol,
            [event_date, native_type],
            [row.get(column) for column in text_fields] + [audit],
        )
        reversal_event = bool(re.search(r"撤销|消除|恢复", text))
        event_state = "distress_marker_removed" if reversal_event else "distress_marker_active"
        lifecycle = [
            {
                "stage": event_state,
                "date": event_date,
                "description": text,
            }
        ]
        if audit.get("date"):
            lifecycle.append(
                {
                    "stage": "audit_opinion_published",
                    "date": audit["date"],
                    "opinion": audit.get("opinion"),
                }
            )
        completeness = _evidence_matrix(
            {
                "status_event": (True, bool(text), "Panda 股票状态变更记录"),
                "fundamentals": (
                    True,
                    fundamental.get("double_check") != "insufficient_evidence",
                    "净利润与经营现金流交叉核验",
                ),
                "audit_opinion": (
                    True,
                    audit_present,
                    "最新实质性 Panda 审计意见",
                ),
                "capital_structure_and_recovery": (
                    False,
                    False,
                    "允许使用的 Panda 接口未提供该信息",
                ),
            }
        )
        payload = {
            "symbol": symbol,
            "situation_type": "distress_turnaround",
            "evidence_status": evidence_status,
            "discovery_status": "event_lead",
            "access_assumption": "secondary_market_equity",
            "status_event": {column: row.get(column) for column in text_fields},
            "event_date": event_date,
            "fundamental_double_check": fundamental,
            "audit_evidence": audit,
            "risk_note": (
                "仅凭 ST 状态无法确定回收价值、资本清偿顺位或永久损失风险。"
            ),
        }
        payload.update(
            apply_underwriting(
                {
                    "symbol": symbol,
                    "situation_type": "distress_turnaround",
                    "market_price": None,
                    "deal_terms": {},
                    "valuation": {},
                    "downside_case": {},
                    "capital_structure": {"verified": False},
                    "legal_accounting": {
                        "verified": audit_present and not audit.get("warning_flag")
                    },
                    "liquidity": {"verified": False},
                    "catalyst": {"verified": bool(text)},
                    "knowledge_cutoff": event_date,
                },
                minimum_margin_of_safety=minimum_margin_of_safety,
                failure_probability_stress=failure_probability_stress,
            )
        )
        _attach_event_metadata(
            payload,
            event_id=event_id,
            revision_id=revision_id,
            event_state=event_state,
            lifecycle=lifecycle,
            completeness=completeness,
        )
        actual_source_date = _max_date(event_date, audit.get("date"), fallback=as_of)
        payload["knowledge_cutoff"] = actual_source_date
        payload["evidence_available_dates"] = sorted(
            {value for value in [event_date, audit.get("date")] if value}
        )
        candidates.append(
            {
                "target_id": event_id,
                "result_type": "distress_event",
                "result_value": payload["underwriting_status"],
                "payload": payload,
                **_record_dates(
                    source_data_date=event_date,
                    actual_source_date=actual_source_date,
                    completeness=completeness,
                ),
            }
        )
    return candidates

def _deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (str(record["target_id"]), str(record["result_type"]))
        previous = output.get(key)
        if previous is None or str(record.get("actual_source_date", "")) >= str(
            previous.get("actual_source_date", "")
        ):
            selected, other = record, previous
        else:
            selected, other = previous, record
        revision_ids = set(
            selected.get("payload", {}).get("observed_revision_ids", [])
        )
        revision_id = selected.get("payload", {}).get("event_revision_id")
        if revision_id:
            revision_ids.add(str(revision_id))
        if other:
            other_revision = other.get("payload", {}).get("event_revision_id")
            if other_revision:
                revision_ids.add(str(other_revision))
        if revision_ids:
            selected["payload"]["observed_revision_ids"] = sorted(revision_ids)
        output[key] = selected
    return list(output.values())
