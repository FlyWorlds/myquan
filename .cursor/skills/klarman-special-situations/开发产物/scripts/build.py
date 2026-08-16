"""稳定的卡拉曼构建编排与命令行入口。"""

from __future__ import annotations

from contextvars import ContextVar

try:
    from .core import (
        Any,
        BUILD_ID,
        BUILD_NAME,
        DATA_VERSION,
        InputValidationError,
        Mapping,
        PandaDataError,
        Path,
        build_production_frame,
        clear_process_credentials,
        clear_checkpointing,
        configure_checkpointing,
        configure_from_environment,
        datetime,
        fetch,
        inspect_production,
        sdk_version,
        timedelta,
        write_production,
    )
    from . import validation as validation
    from .validation import (
        validate_input,
        validate_config,
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
        _float_share_map,
        _fundamental_checks,
        _audit_evidence,
    )
    from . import candidates as candidates
    from .candidates import (
        _placement_candidates,
        _regulatory_candidates,
        _contract_candidates,
        attach_material_contract_context,
        attach_panda_non_core_context,
        _distress_candidates,
        _deduplicate,
    )
    from .point_in_time import filter_publications, visible_unlocks
    from .capabilities import (
        build_coverage_gap_records,
        configure_capability_retries,
        evidence_with_capability,
        fetch_with_capability,
    )
    from .policy import ResearchPolicy, default_policy, load_policy
    from .evidence_model import atom_dict, compile_evidence
    from .evidence_provider import (
        bundle_evidence,
        bundle_matches,
        panda_risk_atoms,
        provider_from_config,
    )
    from .underwriting import apply_underwriting
    from .research_priority import build_research_digest
    from .run_manifest import RunManifest
except ImportError:  # 支持直接执行脚本
    from core import (
        Any,
        BUILD_ID,
        BUILD_NAME,
        DATA_VERSION,
        InputValidationError,
        Mapping,
        PandaDataError,
        Path,
        build_production_frame,
        clear_process_credentials,
        clear_checkpointing,
        configure_checkpointing,
        configure_from_environment,
        datetime,
        fetch,
        inspect_production,
        sdk_version,
        timedelta,
        write_production,
    )
    import validation as validation
    from validation import (
        validate_input,
        validate_config,
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
        _float_share_map,
        _fundamental_checks,
        _audit_evidence,
    )
    import candidates as candidates
    from candidates import (
        _placement_candidates,
        _regulatory_candidates,
        _contract_candidates,
        attach_material_contract_context,
        attach_panda_non_core_context,
        _distress_candidates,
        _deduplicate,
    )
    from point_in_time import filter_publications, visible_unlocks
    from capabilities import (
        build_coverage_gap_records,
        configure_capability_retries,
        evidence_with_capability,
        fetch_with_capability,
    )
    from policy import ResearchPolicy, default_policy, load_policy
    from evidence_model import atom_dict, compile_evidence
    from evidence_provider import bundle_evidence, bundle_matches, panda_risk_atoms, provider_from_config
    from underwriting import apply_underwriting
    from research_priority import build_research_digest
    from run_manifest import RunManifest


_ACTIVE_MANIFEST: ContextVar[RunManifest | None] = ContextVar(
    "klarman_active_manifest", default=None
)


def _run_impl(input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_input(input_data)
    config = dict(config or {})
    if "placement_discount_threshold" in config:
        raise InputValidationError(
            "placement_discount_threshold 已移除；请使用 placement_gain_alert_threshold，且不得将发行价差解释为安全边际"
        )
    validate_config(config)
    progress_callback = config.get("progress_callback")

    def progress(stage: str, **metadata: Any) -> None:
        if progress_callback is not None:
            progress_callback(stage, metadata)

    as_of = str(input_data["as_of_date"])
    start = str(
        input_data.get("start_date")
        or (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
    )
    symbols = sorted(set(input_data.get("symbols") or []))
    if config.get("materialize") and symbols:
        if not config.get("allow_partial_materialization", False):
            raise InputValidationError(
                "定向 symbols 扫描不得写入生产库；如需诊断落盘，请显式设置 allow_partial_materialization=True 并使用独立 output_path"
            )
        if not config.get("output_path"):
            raise InputValidationError(
                "定向扫描诊断落盘必须提供独立 output_path，禁止写入默认生产库"
            )
    max_api_attempts = int(config.get("max_api_attempts", 2))
    configure_capability_retries(max_api_attempts)
    default_operations = Path(__file__).resolve().parents[1] / "validation" / "operations"
    if config.get("manifest_dir") is not None:
        manifest_dir = Path(config["manifest_dir"])
    elif config.get("materialize") and not config.get("output_path"):
        manifest_dir = default_operations
    elif config.get("materialize") and config.get("output_path"):
        manifest_dir = Path(config["output_path"]).resolve().parent / "operations"
    else:
        manifest_dir = None
    manifest = (
        RunManifest(manifest_dir, build_id=BUILD_ID, as_of_date=as_of, start_date=start)
        if manifest_dir is not None
        else None
    )
    _ACTIVE_MANIFEST.set(manifest)
    checkpoint_dir = config.get("checkpoint_dir")
    if checkpoint_dir is None and manifest_dir is not None:
        checkpoint_dir = manifest_dir / "checkpoints"
    if checkpoint_dir is not None:
        scope_token = "all" if not symbols else "symbols-" + str(len(symbols))
        configure_checkpointing(
            Path(checkpoint_dir) / f"{start}-{as_of}-{scope_token}",
            batch_size=int(config.get("checkpoint_batch_size", 50)),
        )
    symbol_arg: list[str] | None = symbols or None
    unlock_days = int(config.get("unlock_window_days", 90))
    gain_threshold = float(config.get("placement_gain_alert_threshold", 0.20))
    selected_policy = config.get("policy")
    if selected_policy is not None and not isinstance(selected_policy, ResearchPolicy):
        raise InputValidationError("policy 必须是 ResearchPolicy")
    policy = selected_policy or load_policy(config.get("policy_path"))
    policy_overrides: dict[str, float] = {}
    if config.get("minimum_margin_of_safety") is not None:
        policy_overrides["minimum_margin_of_safety"] = float(config["minimum_margin_of_safety"])
    if config.get("failure_probability_stress") is not None:
        policy_overrides["failure_probability_stress"] = float(config["failure_probability_stress"])
    if config.get("placement_gain_alert_threshold") is not None:
        policy_overrides["placement_gain_alert_threshold"] = float(config["placement_gain_alert_threshold"])
    policy = policy.with_overrides(**policy_overrides) if policy_overrides else policy
    minimum_margin = policy.minimum_margin_of_safety
    failure_stress = policy.failure_probability_stress
    if unlock_days <= 0:
        raise InputValidationError("解禁窗口天数必须为正数")
    if not 0 < gain_threshold < 10:
        raise InputValidationError("定增参与者浮盈预警阈值必须位于 0 与 10 之间")
    if minimum_margin is not None and not 0 <= minimum_margin <= 1:
        raise InputValidationError("安全边际门槛必须位于 0 与 1 之间")
    if failure_stress is not None and not 0 <= failure_stress <= 1:
        raise InputValidationError("失败压力概率必须位于 0 与 1 之间")
    capabilities: dict[str, dict[str, Any]] = {}

    def checkpoint(stage: str, **metadata: Any) -> None:
        if manifest is not None:
            manifest.stage(stage, metadata)
        progress(stage, **metadata)

    checkpoint("scan_started", as_of_date=as_of, start_date=start, symbol_count=len(symbols))
    placements = fetch_with_capability(
        capabilities, fetch,
        "get_stock_private_placement",
        symbol=symbol_arg,
        start_date=start,
        end_date=as_of,
    )
    checkpoint("private_placement_loaded", row_count=len(placements))
    restrictions = fetch_with_capability(
        capabilities, fetch,
        "get_restricted_list",
        symbol=symbol_arg,
        start_date=start,
        end_date=as_of,
        market="cn",
    )
    checkpoint("restricted_list_loaded", row_count=len(restrictions))
    placements = filter_publications(placements, as_of)
    restrictions = visible_unlocks(restrictions, as_of, unlock_days)
    approvals = fetch_with_capability(
        capabilities, fetch, "get_stock_csrc_approval", start_date=start, end_date=as_of
    )
    checkpoint("csrc_approval_loaded", row_count=len(approvals))
    contracts = fetch_with_capability(
        capabilities, fetch,
        "get_stock_material_contract",
        symbol=symbol_arg,
        start_date=start,
        end_date=as_of,
    )
    checkpoint("material_contract_loaded", row_count=len(contracts))
    status_changes = fetch_with_capability(
        capabilities, fetch,
        "get_stock_status_change",
        symbol=symbol_arg,
        start_date=start,
        end_date=as_of,
    )
    checkpoint("status_change_loaded", row_count=len(status_changes))
    detail = fetch_with_capability(
        capabilities, fetch, "get_stock_detail", symbol=symbol_arg or "", status=1
    )
    checkpoint("stock_detail_loaded", row_count=len(detail))
    name_map = _stock_name_map(detail)

    event_symbols = set(symbols)
    for frame in (placements, contracts, status_changes):
        column = _first_column(frame, ["symbol", "stock_symbol"])
        if column:
            event_symbols.update(
                str(value).replace(".SS", ".SH")
                for value in frame[column].dropna().astype(str)
            )
    for _, row in approvals.iterrows():
        text = _row_text(row, ["announcement_title", "announcement_content"])
        mapped_symbol, mapping_status = _map_text_to_symbol(text, name_map)
        if (
            mapped_symbol
            and mapping_status == "unique_name_match"
            and (not symbols or mapped_symbol in symbols)
        ):
            event_symbols.add(mapped_symbol)
    placement_symbol_column = _first_column(placements, ["symbol", "stock_symbol"])
    share_float_symbols = sorted({
        str(value).replace(".SS", ".SH")
        for value in placements[placement_symbol_column].dropna().astype(str)
    }) if placement_symbol_column else []
    share_float = (
        fetch_with_capability(
            capabilities,
            fetch,
            "get_share_float",
            symbol=share_float_symbols,
            start_date=start,
            end_date=as_of,
        )
        if share_float_symbols
        else detail.iloc[0:0].copy()
    )
    if not share_float_symbols:
        capabilities["get_share_float"] = {
            "status": "not_required",
            "row_count": 0,
            "attempts": 0,
        }
    checkpoint(
        "share_float_loaded",
        row_count=len(share_float),
        placement_symbol_count=len(share_float_symbols),
        event_symbol_count=len(event_symbols),
    )
    float_shares = _float_share_map(share_float)
    risk_frames: dict[str, Any] = {}
    context_frames: dict[str, Any] = {}
    if event_symbols:
        for risk_api in (
            "get_stock_pledge",
            "get_stock_litigation_arbitration",
            "get_cumu_guarantee",
            "get_stock_equity_illegal",
        ):
            risk_frames[risk_api] = fetch_with_capability(
                capabilities,
                fetch,
                risk_api,
                symbol=sorted(event_symbols),
                start_date=start,
                end_date=as_of,
            )
        for context_api in (
            "get_repurchase",
            "get_stock_equity_placard",
            "get_stock_shareholder_change",
        ):
            context_frames[context_api] = fetch_with_capability(
                capabilities,
                fetch,
                context_api,
                symbol=sorted(event_symbols),
                start_date=start,
                end_date=as_of,
            )
    checkpoint(
        "non_core_context_loaded",
        api_count=len(context_frames),
        row_count=sum(len(frame) for frame in context_frames.values()),
    )
    market = evidence_with_capability(
        capabilities,
        "get_stock_daily",
        _market_evidence,
        sorted(event_symbols),
        start,
        as_of,
    )
    prices, trading_histories = market if market else ({}, {})
    checkpoint("stock_daily_loaded", price_count=len(prices), history_count=len(trading_histories))
    fundamentals = evidence_with_capability(
        capabilities,
        "get_fina_reports",
        _fundamental_checks,
        sorted(event_symbols),
        as_of,
    )
    checkpoint("financial_reports_loaded", symbol_count=len(fundamentals))
    audits = evidence_with_capability(
        capabilities,
        "get_audit_opinion",
        _audit_evidence,
        sorted(event_symbols),
        as_of,
    )

    checkpoint("audit_opinion_loaded", symbol_count=len(audits))
    records = _placement_candidates(
        placements,
        restrictions,
        prices,
        fundamentals,
        as_of,
        unlock_days,
        gain_threshold,
        float_shares,
    )
    records.extend(
        _regulatory_candidates(
            approvals,
            name_map,
            fundamentals,
            as_of,
            trading_histories,
            set(symbols) if symbols else None,
            minimum_margin,
            failure_stress,
        )
    )
    # 重大合同只能补充已识别交易，不能独立创建或晋级特殊情况候选。
    attach_material_contract_context(records, contracts, as_of)
    records.extend(
        _distress_candidates(
            status_changes,
            fundamentals,
            as_of,
            audits,
            minimum_margin,
            failure_stress,
        )
    )
    attach_panda_non_core_context(records, context_frames, as_of)
    records.extend(build_coverage_gap_records(capabilities, as_of))
    provider = provider_from_config(config)
    if provider is not None:
        bundles = provider.load(as_of_date=as_of)
        for record in records:
            payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
            if record.get("result_type") not in {"reorganization_event", "spin_off_event", "distress_event"}:
                continue
            matches = [bundle for bundle in bundles if bundle_matches(bundle, payload, str(record["target_id"]))]
            if not matches:
                continue
            bundle = matches[0]
            facts, compiled = bundle_evidence(bundle, as_of_date=as_of)
            facts.setdefault("symbol", payload.get("symbol"))
            facts.setdefault("situation_type", payload.get("situation_type"))
            combined_atoms = list(compiled["atoms"]) + panda_risk_atoms(
                str(facts.get("symbol") or ""), risk_frames, as_of
            )
            compiled = compile_evidence(combined_atoms, as_of_date=as_of)
            situation = str(facts.get("situation_type") or payload.get("situation_type") or "")
            if situation == "distress_turnaround":
                situation = "distress"
            underwriting = apply_underwriting(
                facts,
                situation_type=situation,
                policy=policy,
                compiled_evidence=compiled,
            )
            payload.update(underwriting)
            payload["event_family_id"] = str(record["target_id"])
            payload["revision_id"] = payload.get("event_revision_id")
            payload["policy_id"] = policy.policy_id
            payload["evidence_available_dates"] = [atom.available_date for atom in compiled["atoms"]]
            resolution_atom = next(
                (atom for atom in compiled["atoms"] if atom.field_name == "resolution_date" and atom.core),
                None,
            )
            if resolution_atom is not None:
                payload["resolution_date"] = str(resolution_atom.value)
            payload["panda_risk_evidence"] = [
                {"field_name": atom.field_name, "source_record_id": atom.source_record_id, "content_hash": atom.content_hash}
                for atom in combined_atoms
                if atom.field_name.startswith("risk.")
            ]
            record["result_value"] = underwriting["underwriting_status"]
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
            record["payload"] = payload
        # Keep the V7 envelope stable even when a discovery has no official
        # evidence bundle yet; missing values remain explicit and non-qualifying.
        payload.setdefault("policy_id", policy.policy_id)
        payload.setdefault("evidence_manifest", {"atom_count": 0, "atom_ids": [], "source_records": [], "content_hashes": []})
        payload.setdefault("revision_id", payload.get("event_revision_id"))
        payload.setdefault("qualification_reason", "no_direct_evidence" if record.get("result_value") != "qualified_special_situation" else "all_required_gates_passed")
        payload.setdefault("validation_eligibility", "eligible" if record.get("result_value") == "qualified_special_situation" else "not_eligible")
        payload.setdefault("access_assumption", "secondary_market_equity")
        payload.setdefault("knowledge_cutoff", record.get("actual_source_date") or record.get("source_data_date") or as_of)
        payload.setdefault(
            "scan_scope",
            {"type": "symbols", "symbols": symbols}
            if symbols
            else {"type": "all_a_share"},
        )
        symbol = str(payload.get("symbol") or "")
        if symbol and risk_frames:
            payload.setdefault(
                "risk_evidence_atoms",
                [atom_dict(atom) for atom in panda_risk_atoms(symbol, risk_frames, as_of)],
            )
    records = _deduplicate(records)
    if not records:
        completeness = _evidence_matrix(
            {
                "scan_execution": (True, True, "全部已配置 Panda 扫描均已完成"),
                "qualifying_event": (False, False, "没有事件满足证据规则"),
            }
        )
        event_id, revision_id = _event_identity(
            "scan_summary", None, [start, as_of], ["no_candidates"]
        )
        payload = {
            "event_count": 0,
            "start_date": start,
            "as_of_date": as_of,
            "message": "没有可观察事件；这是有效的扫描结果。",
            "discovery_status": "no_events",
            "underwriting_status": "not_applicable",
            "access_assumption": "secondary_market_equity",
            "knowledge_cutoff": as_of,
            "klarman_gates": {"matrix": {}, "missing_required": []},
            "deal_terms": {},
            "valuation": {},
            "downside_case": {},
            "risk_budget_inputs": {},
            "policy_id": policy.policy_id,
            "evidence_manifest": {"atom_count": 0, "atom_ids": [], "source_records": [], "content_hashes": []},
            "revision_id": revision_id,
            "qualification_reason": "no_events",
            "validation_eligibility": "not_applicable",
            "scan_scope": (
                {"type": "symbols", "symbols": symbols}
                if symbols
                else {"type": "all_a_share"}
            ),
        }
        _attach_event_metadata(
            payload,
            event_id=event_id,
            revision_id=revision_id,
            event_state="scan_complete",
            lifecycle=[{"stage": "scan_completed", "date": as_of}],
            completeness=completeness,
        )
        records = [
            {
                "target_id": "special_situations_universe",
                "result_type": "scan_summary",
                "result_value": "no_events",
                "payload": payload,
                **_record_dates(
                    source_data_date=as_of,
                    actual_source_date=as_of,
                    completeness=completeness,
                ),
            }
        ]
    research_digest = build_research_digest(
        records,
        as_of=as_of,
        fundamentals=fundamentals,
        audits=audits,
        prices=prices,
        trading_histories=trading_histories,
        name_map=name_map,
        context_frames=context_frames,
        contracts=contracts,
    )
    records.append(
        {
            "target_id": "research_digest",
            "result_type": "research_digest",
            "result_value": (
                "available"
                if research_digest.get("shortlist") or research_digest.get("risk_watchlist")
                else "no_high_priority_candidates"
            ),
            "payload": research_digest,
            "source_data_date": as_of,
            "actual_source_date": as_of,
            "coverage_status": "partial" if any(
                item.get("status") == "unavailable" for item in capabilities.values()
            ) else "complete",
        }
    )
    _assert_no_trade_directives(records)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["result_type"]] = counts.get(record["result_type"], 0) + 1
    output: dict[str, Any] = {
        "build_id": BUILD_ID,
        "build_name": BUILD_NAME,
        "data_version": DATA_VERSION,
        "as_of_date": as_of,
        "status": "ok",
        "scan_scope": (
            {"type": "symbols", "symbols": symbols}
            if symbols
            else {"type": "all_a_share"}
        ),
        "source": {
            "provider": "panda_data",
            "sdk_version": sdk_version(),
            "capabilities": capabilities,
            "apis": [
                "get_stock_private_placement",
                "get_restricted_list",
                "get_stock_csrc_approval",
                "get_stock_material_contract",
                "get_stock_status_change",
                "get_stock_daily",
                "get_fina_reports",
                "get_audit_opinion",
                "get_stock_detail",
                "get_share_float",
                "get_stock_pledge",
                "get_stock_litigation_arbitration",
                "get_cumu_guarantee",
                "get_stock_equity_illegal",
                "get_repurchase",
                "get_stock_equity_placard",
                "get_stock_shareholder_change",
            ],
        },
        "summary": {
            "total": len(records),
            "by_type": counts,
            "coverage": {
                status: sum(record.get("coverage_status") == status for record in records)
                for status in ("complete", "partial", "insufficient")
            },
        },
        "research_digest": research_digest,
        "records": records,
        "disclaimer": "仅用于事件研究、证据复核与下行风险分析。",
    }
    if config.get("materialize"):
        output_path = Path(
            config.get(
                "output_path",
                Path(__file__).resolve().parents[1] / "生产产物" / "数据库.parquet",
            )
        )
        frame = build_production_frame(
            build_id=BUILD_ID,
            build_name=BUILD_NAME,
            trade_date=as_of,
            records=records,
            data_version=DATA_VERSION,
        )
        output["production_path"] = str(write_production(frame, output_path))
        checkpoint("production_written", row_count=len(frame), output_path=str(output_path))
    checkpoint("scan_completed", record_count=len(records))
    if manifest is not None:
        manifest.finish(status="completed", metadata={"record_count": len(records), "coverage_gaps": [name for name, item in capabilities.items() if item["status"] == "unavailable"]})
    if manifest is not None:
        output["run_manifest_path"] = str(manifest.path)
    return output


def run(input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Execute one isolated BUILD run and always close operational state."""
    token = _ACTIVE_MANIFEST.set(None)
    try:
        return _run_impl(input_data, config)
    except Exception as exc:
        manifest = _ACTIVE_MANIFEST.get()
        if manifest is not None and manifest.data.get("status") == "running":
            manifest.finish(
                status="failed",
                metadata={"error_type": type(exc).__name__},
            )
        raise
    finally:
        clear_checkpointing()
        _ACTIVE_MANIFEST.reset(token)

def main() -> None:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description=BUILD_NAME)
    parser.add_argument("--as-of", dest="as_of_date")
    parser.add_argument("--start", dest="start_date", default=None)
    parser.add_argument("--symbols", dest="symbols", default=None,
                        help="Comma-separated symbol list")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--allow-partial-materialization", action="store_true")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--policy-path", default=None)
    parser.add_argument("--check-production", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    default_production = Path(__file__).resolve().parents[1] / "生产产物" / "数据库.parquet"
    if args.check_production:
        target = Path(args.output_path) if args.output_path else default_production
        print(_json.dumps(inspect_production(target, expected_data_version=DATA_VERSION), ensure_ascii=False, indent=2))
        return
    if not args.as_of_date:
        parser.print_help()
        return

    input_data: dict = {"as_of_date": args.as_of_date}
    if args.start_date:
        input_data["start_date"] = args.start_date
    if args.symbols:
        input_data["symbols"] = [s.strip() for s in args.symbols.split(",") if s.strip()]

    config = {
        key: value
        for key, value in {
            "materialize": args.materialize,
            "output_path": args.output_path,
            "allow_partial_materialization": args.allow_partial_materialization,
            "evidence_dir": args.evidence_dir,
            "policy_path": args.policy_path,
            "progress_callback": (
                (lambda stage, metadata: print(
                    _json.dumps({"stage": stage, **metadata}, ensure_ascii=False),
                    file=__import__("sys").stderr,
                    flush=True,
                ))
                if args.progress
                else None
            ),
        }.items()
        if value not in (None, False)
    }
    try:
        configure_from_environment(clear=True)
        result = run(input_data, config)
        print(_json.dumps(result, ensure_ascii=False, default=str, indent=2))
    finally:
        clear_process_credentials()


if __name__ == "__main__":
    main()
