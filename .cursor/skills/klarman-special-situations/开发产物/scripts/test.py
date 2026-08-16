from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import build
import demo_html
import panda_adapter
import production_dashboard
import production_job
import validate_build
from panda_adapter import (
    build_production_frame,
    clear_process_credentials,
    configure_from_environment,
    configure_process_credentials,
    configure_checkpointing,
    clear_checkpointing,
    fetch,
    get_api,
    inspect_production,
    write_production,
)
from capabilities import fetch_with_capability
from evidence_queue import review_directory
from operations import health_report
from point_in_time import filter_publications
from replay import build_replay
from research_priority import build_research_digest
from run_manifest import RunManifest


class KlarmanBuildTests(unittest.TestCase):
    def test_strict_build_delivery_validator_passes(self) -> None:
        report = validate_build.validate()
        self.assertEqual(report["status"], "current")
        self.assertTrue(report["development"]["synchronized"])
        self.assertEqual(report["production"]["status"], "current")

    def test_sdk_version_accepts_importable_panda_data_distribution_name(self) -> None:
        with patch.object(
            panda_adapter.importlib.metadata,
            "version",
            side_effect=lambda name: "0.0.12" if name == "panda_data" else (_ for _ in ()).throw(
                panda_adapter.importlib.metadata.PackageNotFoundError(name)
            ),
        ):
            self.assertEqual(panda_adapter.sdk_version(), "0.0.12")

    def test_research_digest_is_deterministic_and_separate_from_supply_risk(self) -> None:
        records = [
            {
                "target_id": "distress-b",
                "result_type": "distress_event",
                "result_value": "underwriting_incomplete",
                "payload": {
                    "symbol": "000002.SZ",
                    "situation_type": "distress_turnaround",
                    "event_date": "20260701",
                    "event_state": "distress_marker_removed",
                    "klarman_gates": {"missing_required": ["conservative_value"]},
                },
            },
            {
                "target_id": "distress-a",
                "result_type": "distress_event",
                "result_value": "underwriting_incomplete",
                "payload": {
                    "symbol": "000001.SZ",
                    "situation_type": "distress_turnaround",
                    "event_date": "20260701",
                    "event_state": "distress_marker_removed",
                },
            },
            {
                "target_id": "placement-a",
                "result_type": "private_placement_supply_risk",
                "result_value": "risk_watch",
                "payload": {
                    "symbol": "000003.SZ",
                    "unlock_evidence": [{"relieve_date": "20260730", "actual_relieve_shares": 500}],
                    "unlock_overhang_ratio": 0.2,
                    "participant_unrealized_gain": 0.3,
                    "unlock_match_confidence": "medium",
                    "underwriting_status": "not_applicable",
                },
            },
        ]
        fundamentals = {
            symbol: {
                "double_check": "pass",
                "profit_positive": True,
                "profit_improving": True,
                "cash_flow_positive": True,
            }
            for symbol in ("000001.SZ", "000002.SZ")
        }
        audits = {
            symbol: {
                "evidence_status": "present",
                "substantive_opinion_available": True,
                "warning_flag": False,
            }
            for symbol in ("000001.SZ", "000002.SZ")
        }
        prices = {
            symbol: {"date": "20260724", "close": 10.0, "trade_status": 0, "average_20d_amount": 1000.0}
            for symbol in ("000001.SZ", "000002.SZ", "000003.SZ")
        }
        first = build_research_digest(
            records,
            as_of="20260724",
            fundamentals=fundamentals,
            audits=audits,
            prices=prices,
            trading_histories={},
        )
        second = build_research_digest(
            list(reversed(records)),
            as_of="20260724",
            fundamentals=fundamentals,
            audits=audits,
            prices=prices,
            trading_histories={},
        )
        self.assertEqual(first, second)
        self.assertEqual([item["symbol"] for item in first["shortlist"]], ["000001.SZ", "000002.SZ"])
        self.assertTrue(all(item["not_trade_signal"] for item in first["shortlist"]))
        self.assertFalse(any(item["situation_type"] == "private_placement_supply_risk" for item in first["shortlist"]))
        self.assertEqual(first["risk_watchlist"][0]["symbol"], "000003.SZ")
        self.assertEqual(first["risk_watchlist"][0]["current_market_evidence"]["unlock_absorption_days"], 5.0)

    def test_research_score_requires_explicit_mapping_and_csrc_provenance(self) -> None:
        records = [
            {
                "target_id": "reorg-without-provenance",
                "result_type": "reorganization_candidate",
                "result_value": "underwriting_incomplete",
                "payload": {
                    "symbol": "000001.SZ",
                    "symbol_mapping": "ambiguous_name_match",
                    "announcement_title": "重大资产重组",
                    "event_date": "20260701",
                },
            },
            {
                "target_id": "reorg-with-provenance",
                "result_type": "reorganization_event",
                "result_value": "underwriting_incomplete",
                "payload": {
                    "symbol": "000002.SZ",
                    "symbol_mapping": "unique_name_match",
                    "csrc_event": True,
                    "announcement_title": "重大资产重组",
                    "event_date": "20260701",
                },
            },
        ]
        fundamentals = {
            symbol: {"double_check": "pass"}
            for symbol in ("000001.SZ", "000002.SZ")
        }
        audits = {
            symbol: {
                "evidence_status": "present",
                "substantive_opinion_available": True,
                "warning_flag": False,
            }
            for symbol in ("000001.SZ", "000002.SZ")
        }
        prices = {
            symbol: {
                "date": "20260724",
                "close": 10.0,
                "trade_status": 0,
                "average_20d_amount": 1000.0,
            }
            for symbol in ("000001.SZ", "000002.SZ")
        }
        digest = build_research_digest(
            records,
            as_of="20260724",
            fundamentals=fundamentals,
            audits=audits,
            prices=prices,
        )
        cards = {item["event_id"]: item for item in digest["shortlist"]}
        self.assertEqual(cards["reorg-without-provenance"]["score_breakdown"]["symbol_mapping"], 0)
        self.assertEqual(cards["reorg-without-provenance"]["score_breakdown"]["csrc_catalyst"], 0)
        self.assertEqual(cards["reorg-with-provenance"]["score_breakdown"]["symbol_mapping"], 10)
        self.assertEqual(cards["reorg-with-provenance"]["score_breakdown"]["csrc_catalyst"], 10)

    def test_research_digest_caps_categories_and_excludes_missing_price(self) -> None:
        records = []
        fundamentals = {}
        audits = {}
        prices = {}
        for index in range(5):
            symbol = f"0000{index + 1:02d}.SZ"
            records.append(
                {
                    "target_id": f"e-{index}",
                    "result_type": "distress_event",
                    "result_value": "underwriting_incomplete",
                    "payload": {
                        "symbol": symbol,
                        "situation_type": "distress_turnaround",
                        "event_date": "20260701",
                        "event_state": "distress_marker_removed",
                    },
                }
            )
            fundamentals[symbol] = {
                "double_check": "pass",
                "profit_positive": True,
                "profit_improving": True,
                "cash_flow_positive": True,
            }
            audits[symbol] = {
                "evidence_status": "present",
                "substantive_opinion_available": True,
                "warning_flag": False,
            }
            if index < 4:
                prices[symbol] = {"date": "20260724", "close": 10.0, "trade_status": 0, "average_20d_amount": 1000.0}
        digest = build_research_digest(
            records,
            as_of="20260724",
            fundamentals=fundamentals,
            audits=audits,
            prices=prices,
            trading_histories={},
        )
        self.assertLessEqual(len(digest["shortlist"]), 3)
        self.assertEqual(digest["excluded_summary"]["by_reason"].get("missing_current_price"), 1)
        self.assertLessEqual(len(digest["shortlist"]), 5)

    def test_capability_retry_classifies_transient_failure(self) -> None:
        calls = 0

        def flaky(_name: str, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise build.PandaDataError("network timeout")
            return pd.DataFrame({"x": [1]})

        capabilities = {}
        frame = fetch_with_capability(capabilities, flaky, "test_api", max_attempts=2)
        self.assertEqual(len(frame), 1)
        self.assertEqual(capabilities["test_api"]["attempts"], 2)

    def test_safe_adapter_hint_remains_transient_upstream(self) -> None:
        calls = 0

        def wrapped(_name: str, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise build.PandaDataError("test_api failed (TimeoutError): transient_transport")
            return pd.DataFrame({"x": [1]})

        capabilities = {}
        fetch_with_capability(capabilities, wrapped, "test_api", max_attempts=2)
        self.assertEqual(capabilities["test_api"]["attempts"], 2)

    def test_run_manifest_is_atomic_and_has_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = RunManifest(directory, build_id="Q51", as_of_date="20260724", start_date="20250724")
            manifest.stage("stock_daily_loaded", {"row_count": 10})
            manifest.finish(status="completed")
            data = json.loads(manifest.path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "completed")
            self.assertNotIn("password", json.dumps(data).lower())
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_failed_run_closes_manifest_and_checkpoint_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_dir = Path(directory) / "operations"
            with patch.object(
                build, "fetch", side_effect=panda_adapter.PandaAuthenticationError("auth refused")
            ):
                with self.assertRaises(panda_adapter.PandaAuthenticationError):
                    build.run(
                        {"as_of_date": "20260724"},
                        {"manifest_dir": manifest_dir, "checkpoint_dir": Path(directory) / "checkpoints"},
                    )
            paths = list(manifest_dir.glob("*.json"))
            self.assertEqual(len(paths), 1)
            data = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "failed")
            self.assertEqual(data["error_type"], "PandaAuthenticationError")
            self.assertIsNone(panda_adapter._CHECKPOINT_DIR)

    def test_checkpoint_second_run_uses_cached_shards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls: list[tuple[str, ...]] = []

            def fake_fetch(_name: str, **kwargs):
                batch = tuple(kwargs["symbol"])
                calls.append(batch)
                return pd.DataFrame({"symbol": list(batch), "value": range(len(batch))})

            configure_checkpointing(directory, batch_size=2)
            try:
                with patch.object(panda_adapter, "_fetch_once", side_effect=fake_fetch):
                    first = fetch("get_stock_daily", symbol=["000001.SZ", "000002.SZ", "000003.SZ"])
                    second = fetch("get_stock_daily", symbol=["000001.SZ", "000002.SZ", "000003.SZ"])
            finally:
                clear_checkpointing()
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(first), 3)
            pd.testing.assert_frame_equal(first, second)

    def test_checkpoint_normalizes_mixed_nan_string_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = 0

            def fake_fetch(_name: str, **_kwargs):
                nonlocal calls
                calls += 1
                return pd.DataFrame(
                    {
                        "symbol": ["000001.SZ", "000002.SZ"],
                        "buy_back_percent": [1.2, "NaN"],
                    }
                )

            configure_checkpointing(directory, batch_size=50)
            try:
                with patch.object(panda_adapter, "_fetch_once", side_effect=fake_fetch):
                    first = fetch("get_repurchase", symbol=["000001.SZ", "000002.SZ"])
                    second = fetch("get_repurchase", symbol=["000001.SZ", "000002.SZ"])
            finally:
                clear_checkpointing()
            self.assertEqual(calls, 1)
            self.assertEqual(first.loc[0, "buy_back_percent"], 1.2)
            self.assertTrue(pd.isna(first.loc[1, "buy_back_percent"]))
            pd.testing.assert_frame_equal(first, second)

    def test_share_float_uses_resumable_per_symbol_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls: list[object] = []

            def fake_fetch(_name: str, **kwargs):
                symbol = kwargs["symbol"]
                calls.append(symbol)
                return pd.DataFrame({"symbol": [symbol], "circulation_a": [1000.0]})

            configure_checkpointing(directory, batch_size=50)
            try:
                with patch.object(panda_adapter, "_fetch_once", side_effect=fake_fetch):
                    first = fetch("get_share_float", symbol=["000001.SZ", "000002.SZ"])
                    second = fetch("get_share_float", symbol=["000001.SZ", "000002.SZ"])
            finally:
                clear_checkpointing()
            self.assertEqual(calls, ["000001.SZ", "000002.SZ"])
            self.assertEqual(first["symbol"].tolist(), ["000001.SZ", "000002.SZ"])
            pd.testing.assert_frame_equal(first, second)

    def test_latest_document_api_names_resolve_on_current_sdk(self) -> None:
        self.assertEqual(get_api("get_stock_equity_illegal").__name__, "get_equity_illegal")
        self.assertEqual(get_api("get_stock_equity_placard").__name__, "get_equity_placard")

    def test_latest_share_float_field_is_supported(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["000001.SZ", "000001.SZ"],
                "date": ["20260723", "20260724"],
                "circulation_a": [1000.0, 1200.0],
            }
        )
        self.assertEqual(build._float_share_map(frame)["000001.SZ"], 1200.0)

    def test_publication_filter_falls_back_from_empty_date_column(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["002230.SZ", "002281.SZ"],
                "date": [None, None],
                "announcement_date": ["20250822", "20260725"],
            }
        )
        visible = filter_publications(frame, "20260724")
        self.assertEqual(visible["symbol"].tolist(), ["002230.SZ"])

    def test_evidence_queue_fail_closes_placeholder_templates(self) -> None:
        report = review_directory(
            Path(build.__file__).resolve().parents[1] / "references" / "evidence_templates",
            as_of_date="20260724",
        )
        self.assertGreater(report["bundle_count"], 0)
        self.assertTrue(all(row["status"] != "ready_for_underwriting" for row in report["rows"]))
        self.assertTrue(all(row.get("reason") == "invalid_content_hash" for row in report["rows"]))

    def test_replay_right_censors_non_eligible_events(self) -> None:
        records = [{
            "target_id": "event-a", "result_type": "distress_event",
            "result_value": "underwriting_incomplete",
            "source_data_date": "20260724", "actual_source_date": "20260724",
            "payload": {"symbol": "000001.SZ", "situation_type": "distress", "knowledge_cutoff": "20260720", "validation_eligibility": "not_eligible"},
        }]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "production.parquet"
            output = Path(directory) / "replay.parquet"
            build_production_frame(build_id="Q51", build_name="test", trade_date="20260724", records=records, data_version="7.3.0").to_parquet(source, index=False)
            result = build_replay(source, data_version="7.3.0", output_path=output)
            replay = pd.read_parquet(output)
            self.assertEqual(result["eligible_count"], 0)
            self.assertEqual(replay.iloc[0]["outcome_status"], "not_eligible")

    def test_health_report_and_dashboard_fail_closed_smoke(self) -> None:
        records = [{
            "target_id": "event-a", "result_type": "distress_event",
            "result_value": "underwriting_incomplete",
            "source_data_date": "20260724", "actual_source_date": "20260724",
            "payload": {
                "symbol": "000001.SZ", "situation_type": "distress",
                "knowledge_cutoff": "20260724", "validation_eligibility": "not_eligible",
                "scan_scope": {"type": "all_a_share"},
                "klarman_gates": {"missing_required": ["failure_value"]},
            },
        }]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production.parquet"
            operations = root / "operations"
            dashboard = root / "dashboard.html"
            build_production_frame(
                build_id="Q51", build_name="test", trade_date="20260724",
                records=records, data_version="7.3.0",
            ).to_parquet(production, index=False)
            report = health_report(
                production, data_version="7.3.0", manifest_dir=operations,
                output_path=operations / "health.json",
            )
            output = production_dashboard.build(
                dashboard, production_path=production, operations_path=operations
            )
            self.assertEqual(report["status"], "attention")
            self.assertTrue((operations / "health.json").exists())
            self.assertTrue(output.exists())
            body = output.read_text(encoding="utf-8")
            self.assertIn("P0", body)
            self.assertIn("承保证据不完整", body)
            self.assertIn("相关接口说明", body)
            self.assertIn("get_stock_private_placement", body)
            self.assertIn("定增解禁供给风险", body)
            self.assertNotIn(">underwriting_incomplete<", body)

    def test_dashboard_places_research_digest_before_audit_sections(self) -> None:
        digest = {
            "methodology_id": "research-priority-v1",
            "as_of_date": "20260724",
            "shortlist": [{
                "rank": 1,
                "symbol": "000001.SZ",
                "stock_name": "测试股份",
                "event_id": "event-1",
                "situation_type": "distress",
                "event_date": "20260720",
                "score": 80,
                "score_breakdown": {"event_state": 30, "total": 80},
                "thesis": "测试研究卡",
                "positive_signals": ["利润改善"],
                "risk_flags": ["需补证"],
                "missing_core_evidence": ["conservative_value"],
                "next_research_actions": ["补齐保守估值"],
                "underwriting_status": "underwriting_incomplete",
                "not_trade_signal": True,
            }],
            "risk_watchlist": [],
            "excluded_summary": {"by_reason": {}},
            "unmapped_event_count": 0,
            "not_trade_signal": True,
        }
        records = [{
            "target_id": "research_digest", "result_type": "research_digest", "result_value": "available",
            "source_data_date": "20260724", "actual_source_date": "20260724", "payload": digest,
        }]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production.parquet"
            operations = root / "operations"
            dashboard = root / "dashboard.html"
            build_production_frame(
                build_id="Q51", build_name="test", trade_date="20260724",
                records=records, data_version="7.4.0",
            ).to_parquet(production, index=False)
            output = production_dashboard.build(
                dashboard, production_path=production, operations_path=operations
            )
            body = output.read_text(encoding="utf-8")
            self.assertLess(body.index("今日研究候选"), body.index("相关接口说明"))
            self.assertIn("评分贡献", body)
            self.assertIn("测试股份", body)
            self.assertIn("不是交易信号", body)

    def test_demo_html_reads_digest_offline_and_keeps_non_trade_boundary(self) -> None:
        digest = {
            "as_of_date": "20260724",
            "not_trade_signal": True,
            "evidence_time_basis": "live_latest_public_by_as_of",
            "historical_replay_time_basis": "event_time_point_in_time_only",
            "unmapped_event_count": 2,
            "excluded_summary": {
                "opportunity_input_count": 8,
                "by_reason": {"unmapped_event": 2},
            },
            "shortlist": [{
                "rank": 1,
                "symbol": "000001.SZ",
                "stock_name": "测试股份",
                "event_id": "event-1",
                "situation_type": "distress",
                "event_date": "20260720",
                "score": 80,
                "score_breakdown": {"event_state": 30, "total": 80},
                "thesis": "测试研究卡",
                "positive_signals": ["利润改善"],
                "risk_flags": ["需补证"],
                "missing_core_evidence": ["conservative_value"],
                "next_research_actions": ["补齐保守估值"],
                "current_market_evidence": {"date": "20260724", "close": 10.0},
                "underwriting_status": "underwriting_incomplete",
                "not_trade_signal": True,
            }],
            "risk_watchlist": [],
        }
        records = [{
            "target_id": "research_digest", "result_type": "research_digest", "result_value": "available",
            "source_data_date": "20260724", "actual_source_date": "20260724", "payload": digest,
        }]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production.parquet"
            output = root / "skill_demo.html"
            build_production_frame(
                build_id="Q51", build_name="test", trade_date="20260724",
                records=records, data_version="7.4.0",
            ).to_parquet(production, index=False)
            result = demo_html.build(output, production_path=production, include_screenshot=False)
            body = result.read_text(encoding="utf-8")
            self.assertTrue(result.exists())
            self.assertIn("测试股份", body)
            self.assertIn("not_trade_signal=true", body)
            self.assertIn("只读取已有生产 Parquet", body)
            self.assertIn("get_stock_private_placement", body)
            self.assertNotIn("PANDA_DATA_PASSWORD", body)

    def test_demo_html_resolves_portable_delivery_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "skill-klarman-special-situations"
            script_path = package_root / "开发产物" / "scripts" / "demo_html.py"
            script_path.parent.mkdir(parents=True)
            (package_root / "生产产物").mkdir()
            self.assertEqual(demo_html._resolve_root(script_path), package_root)

    def test_production_job_writes_safe_failure_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            production_job, "run", side_effect=RuntimeError("server text must not persist")
        ):
            operations = Path(directory) / "operations"
            with self.assertRaises(RuntimeError):
                production_job.execute(
                    as_of_date="20260724", operations_dir=operations,
                    production_path=Path(directory) / "production.parquet",
                    dashboard_path=Path(directory) / "dashboard.html",
                )
            record = json.loads((operations / "job_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["error_type"], "RuntimeError")
            self.assertNotIn("server text", json.dumps(record))
    def test_v7_module_boundaries_keep_stable_entrypoint(self) -> None:
        self.assertEqual(build.DATA_VERSION, "7.4.0")
        self.assertEqual(build.BUILD_NAME, "塞思·克拉曼特殊情况研究")
        self.assertIs(build._audit_evidence, build.evidence._audit_evidence)
        self.assertIs(build._placement_candidates, build.candidates._placement_candidates)
        source = Path(build.__file__).read_text(encoding="utf-8")
        self.assertIn("provider_from_config", source)
        self.assertIn("apply_underwriting", source)

    def test_validate_input_rejects_external_announcements(self) -> None:
        with self.assertRaises(build.InputValidationError):
            build.validate_input({"as_of_date": "20260714", "announcements": []})

    def test_validate_input_rejects_noncanonical_a_share_symbols(self) -> None:
        with self.assertRaises(build.InputValidationError):
            build.validate_input({"as_of_date": "20260714", "symbols": ["000001"]})
        build.validate_input(
            {"as_of_date": "20260714", "symbols": ["000001.SZ", "688001.SH", "430001.BJ"]}
        )

    def test_targeted_scan_cannot_overwrite_default_production(self) -> None:
        with self.assertRaises(build.InputValidationError):
            build.run(
                {"as_of_date": "20260714", "symbols": ["000001.SZ"]},
                {"materialize": True},
            )
        with self.assertRaises(build.InputValidationError):
            build.run(
                {"as_of_date": "20260714", "symbols": ["000001.SZ"]},
                {"materialize": True, "allow_partial_materialization": True},
            )

    def test_unique_name_mapping(self) -> None:
        symbol, status = build._map_text_to_symbol(
            "证监会同意测试股份重大资产重组",
            {"测试股份": "000001.SZ", "另一公司": "000002.SZ"},
        )
        self.assertEqual(symbol, "000001.SZ")
        self.assertEqual(status, "unique_name_match")

    def test_fundamental_checks_use_panda_fields_and_latest_publication(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "quarter": "2024q4",
                    "date": "20250330",
                    "is_n_income_attr_p": 80.0,
                    "cfs_net_cash_operating": 90.0,
                },
                {
                    "symbol": "000001.SZ",
                    "quarter": "2025q4",
                    "date": "20260330",
                    "is_n_income_attr_p": 100.0,
                    "cfs_net_cash_operating": 110.0,
                },
                {
                    "symbol": "000001.SZ",
                    "quarter": "2025q4",
                    "date": "20260430",
                    "is_n_income_attr_p": 120.0,
                    "cfs_net_cash_operating": 130.0,
                },
            ]
        )
        with patch.object(build.evidence, "fetch", return_value=frame):
            result = build._fundamental_checks(["000001.SZ"], "20260714")
        evidence = result["000001.SZ"]
        self.assertEqual(evidence["net_profit"], 120.0)
        self.assertEqual(evidence["previous_net_profit"], 80.0)
        self.assertEqual(evidence["operating_cash_flow"], 130.0)
        self.assertEqual(evidence["double_check"], "pass")
        self.assertEqual(evidence["available_date"], "20260430")

    def test_market_evidence_includes_amount_volume_and_20_day_averages(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["000001.SZ", "000001.SZ"],
                "date": ["20260723", "20260724"],
                "close": [9.0, 10.0],
                "trade_status": [0, 0],
                "amount": [100.0, 300.0],
                "volume": [10.0, 30.0],
            }
        )
        with patch.object(build.evidence, "fetch", return_value=frame) as mocked:
            prices, histories = build.evidence._market_evidence(["000001.SZ"], "20260701", "20260724")
        self.assertEqual(mocked.call_args.kwargs["fields"], ["symbol", "date", "close", "trade_status", "amount", "volume"])
        self.assertEqual(prices["000001.SZ"]["amount"], 300.0)
        self.assertEqual(prices["000001.SZ"]["average_20d_amount"], 200.0)
        self.assertEqual(histories["000001.SZ"][-1]["volume"], 30.0)

    def test_placement_gap_and_unlock_is_supply_risk_not_arbitrage(self) -> None:
        placements = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "announcement_date": "20260101",
                    "approval_date": "20260201",
                    "listed_date": "20260301",
                    "issue_status": "实施完成",
                    "issue_price": 7.0,
                }
            ]
        )
        restrictions = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "relieve_date": "20260801",
                    "relieve_reason": "定向增发机构配售股份",
                    "shareholder": "测试机构",
                    "actual_relieve_shares": 1000,
                }
            ]
        )
        records = build._placement_candidates(
            placements,
            restrictions,
            {"000001.SZ": {"date": "20260714", "close": 10.0}},
            {"000001.SZ": {"double_check": "pass"}},
            "20260714",
            90,
            0.20,
            {"000001.SZ": 10_000},
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["result_type"], "private_placement_supply_risk")
        self.assertEqual(records[0]["result_value"], "risk_watch")
        self.assertAlmostEqual(
            records[0]["payload"]["participant_unrealized_gain"], 10 / 7 - 1
        )
        self.assertEqual(records[0]["payload"]["discovery_status"], "risk_watch")
        self.assertEqual(records[0]["payload"]["underwriting_status"], "not_applicable")
        self.assertEqual(records[0]["payload"]["unlock_overhang_ratio"], 0.1)
        self.assertEqual(records[0]["payload"]["unlock_match_confidence"], "medium")
        self.assertEqual(records[0]["payload"]["event_state"], "unlock_imminent")

    def test_placement_weak_timing_linkage_needs_review(self) -> None:
        placements = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "announcement_date": "20260601",
                    "listed_date": "20260701",
                    "issue_type": "非公开发行",
                    "issue_price": 7.0,
                }
            ]
        )
        restrictions = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "date": "20260710",
                    "relieve_date": "20260801",
                    "relieve_reason": "定向增发机构配售股份",
                }
            ]
        )
        records = build._placement_candidates(
            placements,
            restrictions,
            {"000001.SZ": {"date": "20260714", "close": 10.0}},
            {"000001.SZ": {"double_check": "pass"}},
            "20260714",
            90,
            0.20,
        )
        self.assertEqual(records[0]["result_value"], "risk_watch")
        self.assertEqual(records[0]["payload"]["unlock_match_confidence"], "low")
        self.assertIn(
            "unlock_linkage",
            records[0]["payload"]["evidence_completeness"]["missing_required"],
        )

    def test_event_payload_normalizes_nan_before_json_materialization(self) -> None:
        placements = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "announcement_date": "20260101",
                    "approval_date": float("nan"),
                    "listed_date": "20260301",
                    "issue_status": float("nan"),
                    "issue_price": 7.0,
                }
            ]
        )
        restrictions = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "date": "20260701",
                    "relieve_date": "20260801",
                    "relieve_reason": "定向增发机构配售股份",
                }
            ]
        )
        records = build._placement_candidates(
            placements,
            restrictions,
            {"000001.SZ": {"date": "20260714", "close": 10.0}},
            {"000001.SZ": {"double_check": "pass"}},
            "20260714",
            90,
            0.20,
        )
        frame = build_production_frame(
            build_id="Q51",
            build_name="test",
            trade_date="20260714",
            records=records,
            data_version="2.0.0",
        )
        self.assertIsNone(json.loads(frame.iloc[0]["result_json"])["approval_date"])

    def test_event_id_is_stable_while_revision_id_changes(self) -> None:
        event_a, revision_a = build._event_identity(
            "reorganization", "000001.SZ", ["csrc", "X-1"], ["draft"]
        )
        event_b, revision_b = build._event_identity(
            "reorganization", "000001.SZ", ["csrc", "X-1"], ["approved"]
        )
        self.assertEqual(event_a, event_b)
        self.assertNotEqual(revision_a, revision_b)

    def test_regulatory_ambiguity_needs_review(self) -> None:
        approvals = pd.DataFrame(
            [
                {
                    "publish_date": "20260701",
                    "announcement_title": "甲公司与乙公司重大资产重组",
                    "announcement_content": "",
                    "announcement_number": "X",
                }
            ]
        )
        records = build._regulatory_candidates(
            approvals,
            {"甲公司": "000001.SZ", "乙公司": "000002.SZ"},
            {},
            "20260714",
        )
        self.assertEqual(records[0]["result_value"], "insufficient_evidence")
        self.assertEqual(records[0]["payload"]["symbol_mapping"], "ambiguous_name_match")

    def test_reorganization_includes_suspend_resume_lifecycle(self) -> None:
        approvals = pd.DataFrame(
            [
                {
                    "publish_date": "20260701",
                    "announcement_title": "证监会同意测试股份重大资产重组",
                    "announcement_content": "",
                    "announcement_number": "X-1",
                }
            ]
        )
        histories = {
            "000001.SZ": [
                {"date": "20260630", "trade_status": 0},
                {"date": "20260701", "trade_status": 1},
                {"date": "20260702", "trade_status": 0},
            ]
        }
        records = build._regulatory_candidates(
            approvals,
            {"测试股份": "000001.SZ"},
            {"000001.SZ": {"double_check": "pass"}},
            "20260714",
            histories,
        )
        payload = records[0]["payload"]
        self.assertEqual(records[0]["result_type"], "reorganization_event")
        self.assertEqual(records[0]["result_value"], "underwriting_incomplete")
        self.assertEqual(payload["event_source"], "get_stock_csrc_approval")
        self.assertTrue(payload["csrc_event"])
        self.assertEqual(payload["discovery_status"], "event_lead")
        self.assertEqual(payload["underwriting_status"], "underwriting_incomplete")
        self.assertIn("deal_terms", payload["klarman_gates"]["missing_required"])
        self.assertEqual(payload["event_state"], "resumed_after_suspension")
        self.assertEqual(payload["trading_state_evidence"]["resumption_dates"], ["20260702"])
        self.assertIn("event_revision_id", payload)

    def test_spinoff_requires_valuation_inputs(self) -> None:
        approvals = pd.DataFrame(
            [
                {
                    "publish_date": "20260701",
                    "announcement_title": "测试股份分拆子公司上市",
                    "announcement_content": "",
                    "announcement_number": "S-1",
                }
            ]
        )
        records = build._regulatory_candidates(
            approvals,
            {"测试股份": "000001.SZ"},
            {"000001.SZ": {"double_check": "pass"}},
            "20260714",
        )
        payload = records[0]["payload"]
        self.assertEqual(records[0]["result_value"], "underwriting_incomplete")
        self.assertFalse(payload["valuation_ready"])
        self.assertIn(
            "valuation_inputs", payload["evidence_completeness"]["missing_required"]
        )

    def test_material_contract_is_non_core_context_and_never_promotes(self) -> None:
        records = [
            {
                "target_id": "event-reorganization:test",
                "result_type": "reorganization_event",
                "result_value": "underwriting_incomplete",
                "payload": {"symbol": "000001.SZ", "underwriting_status": "underwriting_incomplete"},
            }
        ]
        contracts = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "info_date": "20260701",
                    "info_id": "C-1",
                    "contract_title": "重大资产重组相关合同",
                    "project_name": "测试项目",
                    "max_contract_amount": 1_000_000_000,
                }
            ]
        )
        build.candidates.attach_material_contract_context(records, contracts, "20260714")
        self.assertEqual(records[0]["result_value"], "underwriting_incomplete")
        context = records[0]["payload"]["material_contract_context"][0]
        self.assertEqual(context["evidence_role"], "non_core_context")
        self.assertNotIn("max_contract_amount", context)

    def test_latest_panda_context_is_non_core_and_point_in_time(self) -> None:
        records = [{
            "target_id": "event-a",
            "result_type": "distress_event",
            "result_value": "underwriting_incomplete",
            "payload": {"symbol": "000001.SZ", "underwriting_status": "underwriting_incomplete"},
        }]
        frames = {
            "get_repurchase": pd.DataFrame([
                {"symbol": "000001.SZ", "date": "20260701", "procedure": "实施完成", "buy_back_percent": 1.2},
                {"symbol": "000001.SZ", "date": "20260720", "procedure": "未来记录", "buy_back_percent": 2.0},
            ]),
            "get_stock_equity_placard": pd.DataFrame([
                {"symbol": "000001.SZ", "info_date": "20260630", "shareholder_name": "测试股东", "total_share_ratio": 5.1},
            ]),
        }
        build.candidates.attach_panda_non_core_context(records, frames, "20260714")
        self.assertEqual(records[0]["result_value"], "underwriting_incomplete")
        context = records[0]["payload"]["panda_non_core_context"]
        self.assertEqual(context["get_repurchase"][0]["procedure"], "实施完成")
        self.assertEqual(context["get_stock_equity_placard"][0]["evidence_role"], "non_core_context")
        self.assertNotIn("未来记录", json.dumps(context, ensure_ascii=False))

    def test_distress_candidate_includes_clean_audit_evidence(self) -> None:
        status_changes = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "date": "20260701",
                    "type": "撤销*ST",
                    "description": "退市风险警示已经消除",
                    "name": "*ST测试",
                }
            ]
        )
        audits = {
            "000001.SZ": {
                "date": "20260315",
                "quarter": "2025q4",
                "opinion": "unqualified_opinion",
                "evidence_status": "present",
                "warning_flag": False,
            }
        }
        records = build._distress_candidates(
            status_changes,
            {"000001.SZ": {"double_check": "pass"}},
            "20260714",
            audits,
        )
        payload = records[0]["payload"]
        self.assertEqual(records[0]["result_type"], "distress_event")
        self.assertEqual(records[0]["result_value"], "underwriting_incomplete")
        self.assertEqual(payload["event_state"], "distress_marker_removed")
        self.assertEqual(payload["audit_evidence"]["opinion"], "unqualified_opinion")
        self.assertIn(
            "capital_structure", payload["klarman_gates"]["missing_required"]
        )

    def test_unqualified_audit_is_not_misclassified_as_warning(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "quarter": "2025q4",
                    "date": "20260315",
                    "audit_type": "financial_statements",
                    "agency": "测试事务所",
                    "opinion": "unqualified_opinion",
                }
            ]
        )
        with patch.object(build.evidence, "fetch", return_value=frame):
            evidence = build._audit_evidence(["000001.SZ"], "20260714")
        self.assertFalse(evidence["000001.SZ"]["warning_flag"])
        self.assertEqual(evidence["000001.SZ"]["evidence_status"], "present")

    def test_audit_evidence_requests_symbols_in_bounded_batches(self) -> None:
        calls: list[list[str]] = []

        def bounded_fetch(_name: str, **kwargs):
            calls.append(list(kwargs["symbol"]))
            return pd.DataFrame()

        symbols = [f"{index:06d}.SZ" for index in range(45)]
        with patch.object(build.evidence, "fetch", side_effect=bounded_fetch):
            build._audit_evidence(symbols, "20260714")

        self.assertEqual(len(calls), 3)
        self.assertTrue(all(len(batch) <= 20 for batch in calls))

    def test_latest_audit_warning_cannot_be_hidden_by_clean_parallel_report(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "quarter": "2025q4",
                    "date": "20260315",
                    "audit_type": "financial_statements",
                    "opinion": "unqualified_opinion",
                },
                {
                    "symbol": "000001.SZ",
                    "quarter": "2025q4",
                    "date": "20260315",
                    "audit_type": "internal_control",
                    "opinion": "qualified_opinion",
                },
            ]
        )
        with patch.object(build.evidence, "fetch", return_value=frame):
            evidence = build._audit_evidence(["000001.SZ"], "20260714")
        self.assertTrue(evidence["000001.SZ"]["warning_flag"])
        self.assertEqual(len(evidence["000001.SZ"]["latest_observations"]), 2)

    def test_trade_directive_language_is_rejected(self) -> None:
        with self.assertRaises(build.PandaDataError):
            build._assert_no_trade_directives(
                [{"payload": {"conclusion": "建议买入"}}]
            )
        build._assert_no_trade_directives(
            [{"payload": {"conclusion": "证据需要法律与估值复核。"}}]
        )

    def test_no_events_produces_valid_summary_parquet(self) -> None:
        empty = pd.DataFrame()

        def fake_fetch(name: str, **kwargs):
            if name == "get_stock_detail":
                return pd.DataFrame({"symbol": [], "name": []})
            return empty

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.parquet"
            with patch.object(build, "fetch", side_effect=fake_fetch), patch.object(
                build, "sdk_version", return_value="0.0.12"
            ):
                result = build.run(
                    {"as_of_date": "20260714"},
                    {"materialize": True, "output_path": output},
                )
            frame = pd.read_parquet(output)
            self.assertEqual(result["summary"]["total"], 2)
            self.assertIn("research_digest", result["summary"]["by_type"])
            summary_row = frame.loc[frame["result_type"] == "scan_summary"].iloc[0]
            self.assertEqual(summary_row["result_value"], "no_events")
            self.assertEqual(summary_row["schema_version"], "2.0.0")
            self.assertEqual(summary_row["data_version"], "7.4.0")
            self.assertEqual(len(frame.columns), 14)
            payload = json.loads(summary_row["result_json"])
            self.assertIn("event_revision_id", payload)
            self.assertIn("evidence_completeness", payload)
            digest_row = frame.loc[frame["result_type"] == "research_digest"].iloc[0]
            digest_payload = json.loads(digest_row["result_json"])
            self.assertEqual(digest_payload["methodology_id"], "research-priority-v1")
            self.assertTrue(digest_payload["not_trade_signal"])

    def test_production_upsert_is_idempotent_and_keeps_history(self) -> None:
        records = [
            {
                "target_id": "X",
                "result_type": "event",
                "result_value": "candidate",
                "source_data_date": "20260714",
                "payload": {"revision": 1},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.parquet"
            write_production(
                build_production_frame(
                    build_id="X", build_name="X", trade_date="20260714",
                    records=records, data_version="2.0.0",
                ),
                output,
            )
            records[0]["payload"] = {"revision": 2}
            write_production(
                build_production_frame(
                    build_id="X", build_name="X", trade_date="20260714",
                    records=records, data_version="2.0.0",
                ),
                output,
            )
            write_production(
                build_production_frame(
                    build_id="X", build_name="X", trade_date="20260715",
                    records=records, data_version="2.0.0",
                ),
                output,
            )
            frame = pd.read_parquet(output)
        self.assertEqual(len(frame), 2)
        latest = frame[frame["trade_date"] == "20260714"].iloc[0]
        self.assertEqual(json.loads(latest["result_json"])["revision"], 2)

    def test_production_replaces_entire_same_day_build_partition(self) -> None:
        old_records = [
            {
                "target_id": "old-gap",
                "result_type": "coverage_gap",
                "result_value": "insufficient_evidence",
                "source_data_date": "20260724",
                "actual_source_date": "20260724",
                "payload": {"api": "recovered_api"},
            },
            {
                "target_id": "event-a",
                "result_type": "distress_event",
                "result_value": "underwriting_incomplete",
                "source_data_date": "20260724",
                "actual_source_date": "20260724",
                "payload": {"revision": 1},
            },
        ]
        new_records = [
            {
                "target_id": "event-a",
                "result_type": "distress_event",
                "result_value": "underwriting_incomplete",
                "source_data_date": "20260724",
                "actual_source_date": "20260724",
                "payload": {"revision": 2},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.parquet"
            write_production(
                build_production_frame(
                    build_id="Q51", build_name="test", trade_date="20260724",
                    records=old_records, data_version="7.3.0",
                ),
                output,
            )
            write_production(
                build_production_frame(
                    build_id="Q51", build_name="test", trade_date="20260724",
                    records=new_records, data_version="7.3.0",
                ),
                output,
            )
            frame = pd.read_parquet(output)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["target_id"], "event-a")
        self.assertEqual(json.loads(frame.iloc[0]["result_json"])["revision"], 2)

    def test_process_credentials_do_not_mutate_environment(self) -> None:
        before = dict(os.environ)
        configure_process_credentials("test-user", "test-password")
        try:
            self.assertEqual(dict(os.environ), before)
        finally:
            clear_process_credentials()

    def test_environment_credentials_are_consumed_and_cleared(self) -> None:
        with patch.dict(
            os.environ,
            {"PANDA_DATA_USERNAME": "test-user", "PANDA_DATA_PASSWORD": "test-password"},
            clear=False,
        ):
            configure_from_environment(clear=True)
            self.assertNotIn("PANDA_DATA_USERNAME", os.environ)
            self.assertNotIn("PANDA_DATA_PASSWORD", os.environ)
        clear_process_credentials()

    def test_production_inspection_detects_stale_and_current_versions(self) -> None:
        records = [
            {
                "target_id": "X",
                "result_type": "scan_summary",
                "result_value": "no_events",
                "source_data_date": "20260714",
                "actual_source_date": "20260714",
                "payload": {},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.parquet"
            write_production(
                build_production_frame(
                    build_id="Q51",
                    build_name="test",
                    trade_date="20260714",
                    records=records,
                    data_version="7.0.0",
                ),
                output,
            )
            stale = inspect_production(output, expected_data_version="7.3.0")
            self.assertEqual(stale["status"], "stale_artifact")
            write_production(
                build_production_frame(
                    build_id="Q51",
                    build_name="test",
                    trade_date="20260715",
                    records=records,
                    data_version="7.3.0",
                ),
                output,
            )
            current = inspect_production(output, expected_data_version="7.3.0")
            self.assertEqual(current["status"], "partial_artifact")

    def test_production_inspection_requires_full_market_scope(self) -> None:
        records = [
            {
                "target_id": "special_situations_universe",
                "result_type": "scan_summary",
                "result_value": "no_events",
                "source_data_date": "20260715",
                "actual_source_date": "20260715",
                "payload": {"scan_scope": {"type": "all_a_share"}},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.parquet"
            write_production(
                build_production_frame(
                    build_id="Q51",
                    build_name="test",
                    trade_date="20260715",
                    records=records,
                    data_version="7.3.0",
                ),
                output,
            )
            current = inspect_production(output, expected_data_version="7.3.0")
            self.assertEqual(current["status"], "current")

    def test_progress_callback_reports_completed_scan(self) -> None:
        stages: list[str] = []

        def fake_fetch(name: str, **kwargs):
            if name == "get_stock_detail":
                return pd.DataFrame({"symbol": [], "name": []})
            return pd.DataFrame()

        with patch.object(build, "fetch", side_effect=fake_fetch), patch.object(
            build, "sdk_version", return_value="0.0.12"
        ):
            build.run(
                {"as_of_date": "20260714"},
                {"progress_callback": lambda stage, _metadata: stages.append(stage)},
            )
        self.assertEqual(stages[0], "scan_started")
        self.assertEqual(stages[-1], "scan_completed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
