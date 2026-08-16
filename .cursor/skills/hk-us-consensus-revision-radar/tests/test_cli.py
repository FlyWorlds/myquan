import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from scripts.auth_session import AuthenticationError, CredentialError, Credentials, SessionGrant
from scripts.analysis import build_consensus_states, build_rankings, compute_metrics
from scripts.event_context import EVENT_APIS
from scripts.run_report import (
    WorkflowOptions, _ProgressRelay, _build_login_window_command, _handle_parent_event,
    _event_scope_symbols, _launch_login_window, _market_payload, _quality_warnings, _run_login_helper,
    _progress_status_reporter, _validate_options,
    build_parser, main, run_workflow,
)


class FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeAuthManager:
    def __init__(self):
        self._auth_lock = FakeLock()
        self._auth_state = SimpleNamespace()
        self.save_auth_state = lambda *args, **kwargs: None

    def clear_auth(self):
        return None


class FakePanda:
    def __init__(self, fail_auth=False):
        self.auth_manager = FakeAuthManager()
        self.events = []
        self.event_symbols = []
        self.fail_auth = fail_auth

    def init_token(self, username, password):
        self.events.append("auth")
        if self.fail_auth:
            raise RuntimeError("rejected")
        self.auth_manager.save_auth_state(username, password, "base", "session", 10)

    def _ncycl(self, symbol, fields):
        self.events.append("data")
        return pd.DataFrame([{
            "symbol": symbol[0], "indicator": "TP", "mean": 110.0,
            "currency": "HKD" if str(symbol[0]).endswith(".HK") else "USD",
            "std": 11.0, "estimates_num": 8, "mean_1month": 100.0,
        }])

    def _rec(self, symbol, fields):
        self.events.append("data")
        return pd.DataFrame([{
            "symbol": symbol[0], "mean": 2.0, "mean_1month": 2.2,
            "strong_buy_num": 3, "buy_num": 2, "hold": 2,
            "sell_num": 1, "strong_sell_num": 0, "recommendations_num": 8,
        }])

    def _daily(self, symbol, start_date, end_date, fields):
        self.events.append("data")
        return pd.DataFrame([{
            "symbol": symbol[0], "date": end_date, "close": 100.0,
            "volume": 1000, "name": "Sample",
        }])

    def _detail(self, symbol, fields, status=None):
        self.events.append("data")
        return pd.DataFrame([
            {"symbol": item, "name": f"Name {item}", "local_name": f"Name {item}",
             "status": 1, "rcs_asset_category_name": r"Equity\Ordinary Share"}
            for item in symbol
        ])

    get_hk_detail = _detail
    get_us_detail = _detail

    get_stock_ncycl_consensus = _ncycl
    get_stock_recommendation_consensus = _rec
    get_hk_daily = _daily
    get_stock_ncycl_estimate = _ncycl
    get_stock_recommendation_estimate = _rec
    get_us_daily = _daily

    def _event(self, symbol, fields, start_date, end_date):
        self.events.append("event")
        self.event_symbols.extend(symbol)
        return pd.DataFrame([{
            "symbol": symbol[0], "info_date": start_date,
            "publish_date": start_date, "start_date": end_date,
            "end_date": end_date, "excute_date": end_date,
            "event_type": "Example", "event": "Example event",
        }])

    get_stock_dividend_event = _event
    get_stock_market_event = _event
    get_stock_meeting_event = _event
    get_stock_financial_event = _event
    get_stock_ir_event = _event
    get_stock_dividend_activity = _event
    get_stock_market_activity = _event
    get_stock_meeting_activity = _event
    get_stock_financial_activity = _event
    get_stock_ir_activity = _event


class CliWorkflowTests(unittest.TestCase):
    def test_login_helper_only_verifies_credentials(self):
        grant = SessionGrant(
            access_token="short-lived-token",
            username="research-user",
            base_url="http://pandadata.example",
            expires_in_seconds=3600,
        )
        session = SimpleNamespace(grant=grant, close=lambda: None)
        relay = SimpleNamespace(
            progress=lambda message: setattr(relay, "progress_message", message),
            authenticated_session=lambda value: setattr(relay, "received", value),
            auth_failure=lambda: None,
            error=lambda message: setattr(relay, "error_message", message),
        )
        fake_panda = SimpleNamespace()
        with (
            patch.dict("sys.modules", {"panda_data": fake_panda}),
            patch("scripts.run_report.resolve_credentials", return_value=Credentials("research-user", "local-secret")),
            patch("scripts.run_report.authenticate", return_value=session),
            patch("scripts.run_report.run_workflow") as workflow,
        ):
            result = _run_login_helper(relay)

        self.assertEqual(result, 0)
        self.assertIs(relay.received, grant)
        self.assertEqual(relay.progress_message, "PandaData 登录成功，正在启动报告任务...")
        workflow.assert_not_called()

    def test_progress_relay_echoes_authentication_status_to_terminal(self):
        relay = _ProgressRelay("127.0.0.1", 43210, "token")
        stream = io.StringIO()
        with (
            patch.object(_ProgressRelay, "_send"),
            patch("scripts.run_report.sys.stderr", stream),
        ):
            relay.progress("账号和密码已接收，正在登录 PandaData...")
            relay.auth_failure()

        message = stream.getvalue()
        self.assertIn("账号和密码已接收，正在登录 PandaData...", message)
        self.assertIn("PandaData 登录失败，请重新输入账号和密码。", message)

    def test_progress_relay_preserves_safe_authentication_category(self):
        relay = _ProgressRelay("127.0.0.1", 43210, "token")
        stream = io.StringIO()

        with (
            patch.object(_ProgressRelay, "_send"),
            patch("scripts.run_report.sys.stderr", stream),
        ):
            relay.auth_failure("PandaData login failed: request rejected by the service (HTTP 401).")

        self.assertIn("HTTP 401", stream.getvalue())

    def test_interactive_auth_failure_reprompts_password_and_retries(self):
        first_credentials = Credentials("research-user", "wrong-secret")
        second_credentials = Credentials("research-user", "correct-secret")
        relay = SimpleNamespace(
            progress=lambda message: None,
            auth_failure=lambda: None,
            error=lambda message: None,
            complete=lambda output, warnings: None,
        )
        with (
            patch.dict("sys.modules", {"panda_data": SimpleNamespace()}),
            patch("scripts.run_report._ProgressRelay", return_value=relay),
            patch("scripts.run_report.resolve_credentials",
                  side_effect=[first_credentials, second_credentials]) as resolver,
            patch("scripts.run_report.run_workflow",
                  side_effect=[AuthenticationError("rejected"), Path("output/report.html")]) as workflow,
        ):
            result = main([
                "--interactive-login", "--market", "hk",
                "--progress-host", "127.0.0.1",
                "--progress-port", "43210",
                "--progress-token", "token",
            ])

        self.assertEqual(result, 0)
        self.assertEqual(resolver.call_count, 2)
        self.assertEqual(workflow.call_count, 2)
    def test_market_payload_overview_uses_eligible_rows(self):
        frame = pd.DataFrame([
            {
                "market": "hk", "symbol": "ELIGIBLE", "tp_mean": 110.0,
                "tp_mean_1month": 100.0, "estimates_num": 8,
            },
            {
                "market": "hk", "symbol": "LOW", "tp_mean": 120.0,
                "tp_mean_1month": 100.0, "estimates_num": 3,
            },
        ])
        metrics = compute_metrics(frame, "1month")
        payload = _market_payload(
            metrics,
            min_analysts=5,
            limit=20,
            diagnostics={},
            revision_threshold=0.01,
        )
        self.assertEqual(payload["overview"]["eligible_rows"], 1)
        self.assertEqual(payload["overview"]["upgrade_rows"], 1)
        self.assertEqual(payload["overview"]["downgrade_rows"], 0)

    def test_cli_exposes_separate_recommendation_coverage_threshold(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args([]).min_recommendations, 5)
        self.assertEqual(
            parser.parse_args(["--min-recommendations", "9"]).min_recommendations,
            9,
        )

    def test_cli_exposes_event_window_and_disable_switch(self):
        defaults = build_parser().parse_args([])

        self.assertEqual(defaults.event_past_days, 30)
        self.assertEqual(defaults.event_future_days, 30)
        self.assertEqual(defaults.event_discovery_days, 730)
        self.assertFalse(defaults.no_events)

    def test_event_option_validation_rejects_invalid_ranges(self):
        with self.assertRaisesRegex(ValueError, "event_past_days"):
            _validate_options(WorkflowOptions(event_past_days=-1))
        with self.assertRaisesRegex(ValueError, "event_future_days"):
            _validate_options(WorkflowOptions(event_future_days=366))
        with self.assertRaisesRegex(ValueError, "event_discovery_days"):
            _validate_options(
                WorkflowOptions(event_past_days=30, event_discovery_days=29)
            )

    def test_event_scope_uses_all_rankings_and_explicit_symbols_only(self):
        market_payload = {
            "rows": [{"symbol": "ROWS-ONLY"}],
            "rankings": {
                "upgrades": [{"symbol": "DUPLICATE"}, {"symbol": "UPGRADE"}],
                "downgrades": [{"symbol": "DOWNGRADE"}],
                "high_dispersion": [{"symbol": "DISPERSION"}],
                "rating_changes": [{"symbol": "RATING-ONLY"}],
                "price_consensus_divergence": [{"symbol": "DUPLICATE"}],
            },
        }

        symbols = _event_scope_symbols(
            market_payload, ["EXPLICIT", "DUPLICATE", "  EXPLICIT  "]
        )

        self.assertEqual(
            symbols,
            [
                "DISPERSION", "DOWNGRADE", "DUPLICATE", "EXPLICIT",
                "RATING-ONLY", "UPGRADE",
            ],
        )

    def test_workflow_adds_events_only_after_rankings_and_uses_explicit_scope(self):
        panda = FakePanda()
        captures = []
        original_market_payload = _market_payload
        sequence = []

        def capture_market_payload(*args, **kwargs):
            sequence.append("rankings")
            return original_market_payload(*args, **kwargs)

        def capture_report(payload, destination):
            captures.append(payload)
            return destination

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("scripts.run_report._market_payload", side_effect=capture_market_payload),
            patch("scripts.run_report.render_report", side_effect=capture_report),
        ):
            run_workflow(
                WorkflowOptions(
                    markets=["hk"],
                    symbols={"hk": ["0700.HK", "EXPLICIT"]},
                    output_dir=Path(temp_dir),
                ),
                panda,
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
            )

        market = captures[0]["markets"]["hk"]
        self.assertIn("events", market)
        self.assertIn("event_context", market)
        self.assertEqual(sequence, ["rankings"])
        self.assertIn("0700.HK", panda.event_symbols)
        self.assertIn("EXPLICIT", panda.event_symbols)
        self.assertIn("event", panda.events)

    def test_disabled_events_skip_endpoints_and_leave_rankings_unchanged(self):
        captures = []

        def capture_report(payload, destination):
            captures.append(payload)
            return destination

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.run_report.render_report", side_effect=capture_report,
        ):
            run_workflow(
                WorkflowOptions(
                    markets=["hk"], symbols={"hk": ["0700.HK"]},
                    output_dir=Path(temp_dir),
                ),
                FakePanda(),
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
            )
            run_workflow(
                WorkflowOptions(
                    markets=["hk"], symbols={"hk": ["0700.HK"]},
                    include_events=False, output_dir=Path(temp_dir),
                ),
                FakePanda(),
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
            )

        enabled = captures[0]["markets"]["hk"]
        disabled = captures[2]["markets"]["hk"]
        self.assertEqual(
            json.dumps(enabled["rankings"], ensure_ascii=False, sort_keys=True),
            json.dumps(disabled["rankings"], ensure_ascii=False, sort_keys=True),
        )
        self.assertEqual(
            json.dumps(enabled["rows"], ensure_ascii=False, sort_keys=True),
            json.dumps(disabled["rows"], ensure_ascii=False, sort_keys=True),
        )
        self.assertEqual(disabled["events"], [])
        self.assertEqual(disabled["event_context"]["status"], "disabled")
        self.assertFalse(any(
            item["interface"] in {
                interface for interface, _ in EVENT_APIS["hk"].values()
            }
            for item in disabled["source_interfaces"]
        ))

    def test_event_endpoint_failures_do_not_block_report_or_leak_credentials(self):
        panda = FakePanda()
        for interface, _ in EVENT_APIS["hk"].values():
            setattr(
                panda, interface,
                lambda **kwargs: (_ for _ in ()).throw(RuntimeError("local-secret")),
            )
        captures = []
        warnings = []
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.run_report.render_report",
            side_effect=lambda payload, destination: captures.append(payload) or destination,
        ):
            run_workflow(
                WorkflowOptions(
                    markets=["hk"], symbols={"hk": ["0700.HK"]},
                    include_events=False, output_dir=Path(temp_dir),
                ),
                FakePanda(),
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
            )
            output = run_workflow(
                WorkflowOptions(
                    markets=["hk"], symbols={"hk": ["0700.HK"]},
                    output_dir=Path(temp_dir),
                ),
                panda,
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
                quality_warnings=warnings,
            )

        baseline = captures[0]["markets"]["hk"]
        market = captures[2]["markets"]["hk"]
        self.assertEqual(output.suffix, ".html")
        self.assertEqual(market["event_context"]["status"], "unavailable")
        self.assertEqual(
            json.dumps(baseline["rankings"], ensure_ascii=False, sort_keys=True),
            json.dumps(market["rankings"], ensure_ascii=False, sort_keys=True),
        )
        self.assertTrue(any("event context" in warning for warning in warnings))
        self.assertNotIn("local-secret", "\n".join(warnings))

    def test_rendered_html_omits_sensitive_event_error_text(self):
        panda = FakePanda()
        for interface, _ in EVENT_APIS["hk"].values():
            setattr(
                panda, interface,
                lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("Authorization: Bearer demo-token password=hunter2")
                ),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = run_workflow(
                WorkflowOptions(
                    markets=["hk"],
                    symbols={"hk": ["0700.HK"]},
                    output_dir=Path(temp_dir),
                ),
                panda,
                {
                    "PANDADATA_USERNAME": "1" * 11,
                    "PANDADATA_PASSWORD": "example-only",
                },
            )
            html = output.read_text(encoding="utf-8").lower()

        self.assertNotIn("authorization", html)
        self.assertNotIn("bearer", html)
        self.assertNotIn("demo-token", html)
        self.assertNotIn("hunter2", html)

    def test_market_payload_reports_separate_target_and_rating_thresholds(self):
        frame = pd.DataFrame([
            {"market": "hk", "symbol": "0700.HK", "tp_mean": 110.0,
             "tp_mean_1month": 100.0, "estimates_num": 8,
             "rec_mean": 2.0, "rec_mean_1month": 2.2,
             "recommendations_num": 4},
        ])
        payload = _market_payload(
            compute_metrics(frame), min_analysts=5, min_recommendations=7,
            limit=20, diagnostics={}, revision_threshold=0.01,
        )
        self.assertEqual(payload["overview"]["min_analysts"], 5)
        self.assertEqual(payload["overview"]["min_recommendations"], 7)
        self.assertEqual(payload["quality"]["rating_eligible_rows"], 0)

    def test_market_payload_exposes_time_evidence_and_eligibility_funnels(self):
        frame = pd.DataFrame([{
            "market": "hk", "symbol": "0700.HK", "universe_eligible": True,
            "tp_mean": 110.0, "tp_mean_1month": 100.0,
            "estimates_num": 8, "estimates_num_1month": 7,
            "rec_mean": 2.0, "rec_mean_1month": 2.2,
            "recommendations_num": 8,
        }])
        diagnostics = {
            "consensus_retrieved_at": "2026-07-20 15:00:00 +0800",
            "consensus_as_of": None,
            "historical_snapshot_label": "1month",
            "historical_snapshot_as_of": None,
        }
        payload = _market_payload(
            compute_metrics(frame), min_analysts=5, min_recommendations=5,
            limit=20, diagnostics=diagnostics, revision_threshold=0.01,
        )

        self.assertEqual(payload["diagnostics"], diagnostics)
        self.assertEqual(
            payload["eligibility_funnels"]["target_revision"][-1]["count"], 1,
        )
        self.assertEqual(payload["eligibility_funnels"]["rating"][-1]["count"], 1)
        self.assertEqual(
            payload["eligibility_funnels"]["target_revision"][-1]["key"],
            "revision_eligible",
        )
        self.assertEqual(
            payload["eligibility_funnels"]["rating"][-1]["key"],
            "rating_eligible",
        )
        self.assertEqual(payload["overview"]["revision_eligible_rows"], 1)

    def test_market_payload_injects_states_and_trajectory_matrix_without_changing_rankings(self):
        frame = pd.DataFrame([
            {
                "market": "hk", "name": "Alpha", "symbol": "0001.HK",
                "industry_group": "Technology", "universe_eligible": True,
                "tp_mean": 120.0, "tp_mean_week": 110.0,
                "tp_mean_1month": 100.0, "tp_mean_3month": 90.0,
                "tp_mean_6month": 80.0, "tp_mean_12month": 70.0,
                "rec_mean": 1.8, "rec_mean_week": 2.0,
                "rec_mean_1month": 2.1, "rec_mean_3month": 2.2,
                "rec_mean_6month": 2.3, "rec_mean_12month": 2.4,
                "tp_std": 12.0, "estimates_num": 8,
                "included_estimates_num": 7, "recommendations_num": 9,
            },
            {
                "market": "hk", "name": "Excluded", "symbol": "0002.HK",
                "industry_group": "Other", "universe_eligible": False,
                "tp_mean": 100.0, "tp_mean_week": 100.0,
                "tp_mean_1month": 100.0, "estimates_num": 8,
            },
        ])
        metrics = compute_metrics(frame, "week", revision_threshold=0.01)
        expected_rankings = {
            key: json.loads(value.to_json(orient="records", date_format="iso"))
            for key, value in build_rankings(
                metrics, min_analysts=5, min_recommendations=5, limit=20,
            )["hk"].items()
            if key in {
                "upgrades", "downgrades", "high_dispersion", "rating_changes",
                "price_consensus_divergence",
            }
        }

        with patch(
            "scripts.run_report.build_consensus_states",
            wraps=build_consensus_states,
        ) as states_builder:
            payload = _market_payload(
                metrics, min_analysts=5, min_recommendations=5, limit=20,
                diagnostics={}, revision_threshold=0.01,
            )

        self.assertEqual(states_builder.call_args.kwargs["horizon"], "week")
        self.assertEqual(payload["rankings"], expected_rankings)
        self.assertEqual([row["symbol"] for row in payload["trajectory_matrix"]], ["0001.HK"])
        matrix_row = payload["trajectory_matrix"][0]
        self.assertEqual(matrix_row["target_price_trajectory"][0]["horizon"], "week")
        self.assertEqual(matrix_row["target_price_trajectory"][0]["current"], 120.0)
        self.assertEqual(matrix_row["rating_trajectory"][0]["historical"], 2.0)
        self.assertEqual(matrix_row["target_price_trajectory"][0]["direction"], "positive")
        self.assertIn("consensus_states", matrix_row)
        self.assertIn("dispersion_p75", matrix_row)
        self.assertIn("dispersion_sample_count", matrix_row)
        row = next(row for row in payload["rows"] if row["symbol"] == "0001.HK")
        self.assertEqual(row["consensus_states"], matrix_row["consensus_states"])
        self.assertEqual(row["dispersion_p75"], matrix_row["dispersion_p75"])
        self.assertEqual(row["dispersion_sample_count"], matrix_row["dispersion_sample_count"])

    def test_market_payload_marks_nonfinite_revision_values_and_directions_unavailable(self):
        frame = pd.DataFrame([{
            "market": "hk", "name": "Invalid", "symbol": "INVALID.HK",
            "universe_eligible": True,
            "tp_mean": float("inf"), "tp_mean_week": 100.0,
            "tp_mean_1month": 100.0, "tp_mean_3month": 100.0,
            "rec_mean": float("-inf"), "rec_mean_week": 2.0,
            "rec_mean_1month": 2.0, "rec_mean_3month": 2.0,
            "estimates_num": 8, "recommendations_num": 8,
        }])
        metrics = compute_metrics(frame, "1month")
        baseline_rankings = {
            key: json.loads(value.to_json(orient="records", date_format="iso"))
            for key, value in build_rankings(
                metrics, min_analysts=5, min_recommendations=5, limit=20,
            )["hk"].items()
            if key in {
                "upgrades", "downgrades", "high_dispersion", "rating_changes",
                "price_consensus_divergence",
            }
        }

        payload = _market_payload(
            metrics, min_analysts=5,
            min_recommendations=5, limit=20, diagnostics={},
            revision_threshold=0.01,
        )

        self.assertEqual(payload["rankings"], baseline_rankings)
        row = payload["rows"][0]
        self.assertIsNone(row["tp_revision"])
        self.assertEqual(row["revision_direction"], "unavailable")
        self.assertIsNone(row["rating_change"])
        self.assertEqual(row["rating_direction"], "unavailable")
        matrix = payload["trajectory_matrix"][0]
        for trajectory in (
            matrix["target_price_trajectory"], matrix["rating_trajectory"],
        ):
            for evidence in trajectory:
                self.assertIsNone(evidence["current"])
                self.assertIsNone(evidence["change"])
                self.assertEqual(evidence["direction"], "unavailable")
        self.assertEqual(row["consensus_states"], [])
    def test_non_tty_missing_credentials_stops_before_launching_login_window(self):
        with (
            patch("scripts.run_report.resolve_credentials",
                  side_effect=CredentialError("missing")),
            patch("scripts.run_report._launch_login_window") as launcher,
            patch("scripts.run_report.sys.stdin.isatty", return_value=False),
            patch("scripts.run_report.sys.stderr.isatty", return_value=False),
            patch("scripts.run_report.sys.stderr", new_callable=io.StringIO) as stream,
        ):
            result = main(["--market", "both"])

        self.assertEqual(result, 1)
        launcher.assert_not_called()
        self.assertIn("PANDADATA_USERNAME", stream.getvalue())
        self.assertIn("desktop", stream.getvalue().lower())

    def test_non_tty_missing_credentials_launches_when_desktop_window_requested(self):
        credentials = Credentials("research-user", "local-secret")
        with (
            patch.dict("sys.modules", {"panda_data": SimpleNamespace()}),
            patch("scripts.run_report.resolve_credentials",
                  side_effect=CredentialError("missing")),
            patch("scripts.run_report._launch_login_window", return_value=credentials) as launcher,
            patch("scripts.run_report.run_workflow", return_value=Path("output/report.html")),
            patch("scripts.run_report.sys.stdin.isatty", return_value=False),
            patch("scripts.run_report.sys.stderr.isatty", return_value=False),
        ):
            result = main(["--market", "both", "--desktop-login-window"])

        self.assertEqual(result, 0)
        launcher.assert_called_once()
        self.assertEqual(
            launcher.call_args.args[0],
            ["--market", "both", "--desktop-login-window"],
        )
        self.assertTrue(callable(launcher.call_args.kwargs["progress_callback"]))

    def test_parser_accepts_progress_file_for_external_run_monitoring(self):
        args = build_parser().parse_args(["--progress-file", "output/run-status.json"])

        self.assertEqual(args.progress_file, "output/run-status.json")

    def test_progress_status_reporter_writes_latest_safe_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "run-status.json"
            reporter = _progress_status_reporter(destination)

            reporter("正在获取 HK 数据（1/2）...")

            status = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(status["message"], "正在获取 HK 数据（1/2）...")
        self.assertIn("updated_at", status)

    def test_main_forwards_workflow_progress_to_external_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "run-status.json"
            credentials = Credentials("research-user", "local-secret")

            def workflow(*_args, **kwargs):
                kwargs["progress_callback"]("HK 数据获取完成，正在分析...")
                return Path("output/report.html")

            with (
                patch.dict("sys.modules", {"panda_data": SimpleNamespace()}),
                patch("scripts.run_report.resolve_credentials", return_value=credentials),
                patch("scripts.run_report.run_workflow", side_effect=workflow),
            ):
                result = main(["--market", "hk", "--progress-file", str(destination)])

            status = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(status["message"], "HK 数据获取完成，正在分析...")

    def test_main_writes_failure_status_to_external_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "run-status.json"
            credentials = Credentials("research-user", "local-secret")

            with (
                patch.dict("sys.modules", {"panda_data": SimpleNamespace()}),
                patch("scripts.run_report.resolve_credentials", return_value=credentials),
                patch("scripts.run_report.run_workflow", side_effect=RuntimeError("service unavailable")),
            ):
                result = main(["--market", "hk", "--progress-file", str(destination)])

            status = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(result, 1)
        self.assertEqual(status["message"], "报告生成失败，请查看本地终端。")

    def test_parser_exposes_desktop_login_window_flag(self):
        self.assertTrue(build_parser().parse_args(["--desktop-login-window"]).desktop_login_window)

    def test_no_login_window_keeps_noninteractive_failure(self):
        with (
            patch("scripts.run_report.resolve_credentials",
                  side_effect=CredentialError("missing")),
            patch("scripts.run_report._launch_login_window") as launcher,
            patch("scripts.run_report.sys.stdin.isatty", return_value=False),
            patch("scripts.run_report.sys.stderr.isatty", return_value=False),
        ):
            result = main(["--no-login-window"])

        self.assertEqual(result, 1)
        launcher.assert_not_called()

    def test_windows_login_window_requests_normal_foreground_console(self):
        with patch("scripts.run_report.sys.platform", "win32"):
            command, kwargs = _build_login_window_command(
                [], Path("skill"), "python.exe", "127.0.0.1", 43210, "token",
            )

        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("-WindowStyle", command)
        self.assertIn("Normal", command)
        self.assertIn('--interactive-login', command[-1])
        self.assertIn('--no-login-window', command[-1])
        self.assertIn('--login-helper', command[-1])
        self.assertIn('--progress-token', command[-1])
        self.assertTrue(kwargs['creationflags'])

    def test_macos_login_window_activates_terminal(self):
        with patch("scripts.run_report.sys.platform", "darwin"):
            command, _ = _build_login_window_command(
                [], Path("skill"), "python3", "127.0.0.1", 43210, "token",
            )

        self.assertEqual(command[0], "osascript")
        self.assertIn('tell application "Terminal" to activate', command[-1])
        self.assertIn('Terminal', command[-1])
        self.assertIn('--interactive-login', command[-1])
        self.assertIn('--no-login-window', command[-1])
        self.assertIn('--login-helper', command[-1])
        self.assertIn('--progress-token', command[-1])

    def test_login_window_reports_child_exit_before_relay(self):
        exited = SimpleNamespace(poll=lambda: 17)
        with (
            patch("scripts.run_report._build_login_window_command", return_value=(["helper"], {})),
            patch("scripts.run_report.subprocess.Popen", return_value=exited),
            patch("scripts.run_report.sys.stderr", new_callable=io.StringIO) as stream,
        ):
            self.assertEqual(_launch_login_window(["--market", "hk"]), 17)
        self.assertIn("login helper exited", stream.getvalue().lower())

    def test_login_window_hides_oserror_details(self):
        with (
            patch("scripts.run_report._build_login_window_command", return_value=(["helper"], {})),
            patch(
                "scripts.run_report.subprocess.Popen",
                side_effect=OSError("sensitive child command"),
            ),
            patch("scripts.run_report.sys.stderr", new_callable=io.StringIO) as stream,
        ):
            self.assertEqual(_launch_login_window(["--market", "hk"]), 1)

        self.assertIn("Unable to launch PandaData login window.", stream.getvalue())
        self.assertNotIn("sensitive child command", stream.getvalue())

    def test_quality_warnings_disclose_pandadata_gaps(self):
        warnings = _quality_warnings(
            {
                "us": {
                    "quality": {
                        "missing_name": 3,
                        "missing_price": 4,
                        "missing_history": 5,
                        "missing_recommendation": 6,
                        "missing_coverage": 7,
                    },
                    "diagnostics": {
                        "price_match_rate": 0.8,
                        "price_fallback_used": True,
                    },
                }
            }
        )
        message = "\n".join(warnings)
        self.assertIn("US", message)
        self.assertIn("price match rate", message)
        self.assertIn("missing target-price history", message)
        self.assertIn("missing analyst coverage", message)
        self.assertIn("missing recommendation data", message)
    def test_main_resolves_credentials_without_terminal_prompt(self):
        credentials = Credentials("research-user", "local-secret")
        fake_panda = SimpleNamespace()
        with (
            patch.dict("sys.modules", {"panda_data": fake_panda}),
            patch("scripts.run_report.sys.stdin.isatty", return_value=True),
            patch("scripts.run_report.sys.stderr.isatty", return_value=True),
            patch("scripts.run_report.resolve_credentials", return_value=credentials) as resolver,
            patch("scripts.run_report.run_workflow", return_value=Path("output/report.html")) as workflow,
        ):
            result = main(["--market", "hk", "--symbols", "0700.HK"])

        self.assertEqual(result, 0)
        resolver.assert_called_once()
        self.assertFalse(resolver.call_args.kwargs["interactive"])
        self.assertIs(workflow.call_args.kwargs["credentials"], credentials)

    def test_main_reports_pandadata_connection_failure(self):
        credentials = Credentials('research-user', 'local-secret')
        stream = __import__('io').StringIO()
        with (
            patch.dict('sys.modules', {'panda_data': FakePanda(fail_auth=True)}),
            patch('scripts.run_report.sys.stdin.isatty', return_value=True),
            patch('scripts.run_report.sys.stderr', stream),
            patch('scripts.run_report.resolve_credentials', return_value=credentials),
        ):
            result = main(['--market', 'hk'])

        self.assertEqual(result, 1)
        self.assertIn('PandaData 连接失败', stream.getvalue())
    def test_missing_credentials_prevents_any_data_call(self):
        panda = FakePanda()
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(CredentialError):
                run_workflow(
                    WorkflowOptions(markets=["hk"], symbols={"hk": ["0700.HK"]},
                                    output_dir=Path(temp_dir)),
                    panda,
                    {},
                )
            self.assertEqual(panda.events, [])
            self.assertEqual(list(Path(temp_dir).glob("*.html")), [])

    def test_authentication_failure_creates_no_report(self):
        panda = FakePanda(fail_auth=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(RuntimeError):
                run_workflow(
                    WorkflowOptions(markets=["hk"], symbols={"hk": ["0700.HK"]},
                                    output_dir=Path(temp_dir)),
                    panda,
                    {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
                )
            self.assertEqual(panda.events, ["auth"])
            self.assertEqual(list(Path(temp_dir).glob("*.html")), [])

    def test_run_workflow_emits_connection_and_report_progress(self):
        panda = FakePanda()
        progress = []
        with tempfile.TemporaryDirectory() as temp_dir:
            run_workflow(
                WorkflowOptions(
                    markets=['hk'],
                    symbols={'hk': ['0700.HK']},
                    output_dir=Path(temp_dir),
                ),
                panda,
                {'PANDADATA_USERNAME': '1' * 11,
                 'PANDADATA_PASSWORD': 'example-only'},
                progress_callback=progress.append,
            )

        message = '\n'.join(progress)
        self.assertIn('PandaData 连接成功', message)
        self.assertIn('正在获取 HK 数据', message)
        self.assertIn('HK 数据获取完成，正在分析', message)
        self.assertIn('正在写入报告', message)
        self.assertIn('报告已生成', message)

    def test_run_workflow_reports_each_event_phase_in_main_process(self):
        progress = []
        with tempfile.TemporaryDirectory() as temp_dir:
            run_workflow(
                WorkflowOptions(
                    markets=["hk"], symbols={"hk": ["0700.HK"]},
                    output_dir=Path(temp_dir),
                ),
                FakePanda(),
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
                progress_callback=progress.append,
            )

        message = "\n".join(progress)
        self.assertIn("PandaData", message)
        self.assertIn("HK event context: dividend 1/5", message)
        self.assertIn("HK event context: ir 5/5", message)
        self.assertIn("HK event collection complete", message)
        self.assertIn("正在写入报告", message)
        self.assertIn("报告已生成", message)

    def test_main_reports_connection_start_after_credentials(self):
        credentials = Credentials('research-user', 'local-secret')
        stream = __import__('io').StringIO()
        with (
            patch.dict('sys.modules', {'panda_data': SimpleNamespace()}),
            patch('scripts.run_report.sys.stdin.isatty', return_value=True),
            patch('scripts.run_report.sys.stderr.isatty', return_value=True),
            patch('scripts.run_report.sys.stderr', stream),
            patch('scripts.run_report.resolve_credentials', return_value=credentials),
            patch('scripts.run_report.run_workflow', return_value=Path('output/report.html')),
        ):
            result = main(['--market', 'hk'])

        self.assertEqual(result, 0)
        self.assertIn('PandaData', stream.getvalue())
    def test_success_authenticates_first_and_writes_timestamp_plus_latest(self):
        panda = FakePanda()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_workflow(
                WorkflowOptions(
                    markets=["hk", "us"],
                    symbols={"hk": ["0700.HK"], "us": ["AAPL"]},
                    output_dir=Path(temp_dir),
                ),
                panda,
                {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
            )
            self.assertEqual(panda.events[0], "auth")
            self.assertTrue(result.exists())
            self.assertTrue((Path(temp_dir) / "latest.html").exists())
            self.assertIn("0700.HK", result.read_text(encoding="utf-8"))
            html = result.read_text(encoding="utf-8")
            self.assertIn("AAPL", html)
            self.assertIn("price_fallback_used", html)
            self.assertIn("revision_threshold", html)

    def test_invalid_horizon_is_rejected_before_data(self):
        panda = FakePanda()
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                run_workflow(
                    WorkflowOptions(markets=["hk"], horizon="2month",
                                    output_dir=Path(temp_dir)),
                    panda,
                    {"PANDADATA_USERNAME": "1" * 11, "PANDADATA_PASSWORD": "example-only"},
                )
            self.assertEqual(panda.events, [])


    def test_invalid_revision_threshold_is_rejected_before_data(self):
        for threshold in (-0.01, 1.01):
            panda = FakePanda()
            with tempfile.TemporaryDirectory() as temp_dir:
                with self.assertRaises(ValueError):
                    run_workflow(
                        WorkflowOptions(
                            markets=["hk"],
                            revision_threshold=threshold,
                            output_dir=Path(temp_dir),
                        ),
                        panda,
                        {"PANDADATA_USERNAME": "1" * 11,
                         "PANDADATA_PASSWORD": "example-only"},
                    )
                self.assertEqual(panda.events, [])

    def test_invalid_recommendation_threshold_is_rejected_before_data(self):
        panda = FakePanda()
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                run_workflow(
                    WorkflowOptions(
                        markets=["hk"], min_recommendations=0,
                        output_dir=Path(temp_dir),
                    ),
                    panda,
                    {"PANDADATA_USERNAME": "1" * 11,
                     "PANDADATA_PASSWORD": "example-only"},
                )
        self.assertEqual(panda.events, [])
    def test_main_launches_login_window_when_terminal_is_interactive(self):
        grant = SessionGrant(
            access_token="short-lived-token",
            username="research-user",
            base_url="http://pandadata.example",
            expires_in_seconds=3600,
        )
        fake_panda = SimpleNamespace()
        with (
            patch.dict("sys.modules", {"panda_data": fake_panda}),
            patch("scripts.run_report.resolve_credentials",
                  side_effect=CredentialError("missing")),
            patch("scripts.run_report._launch_login_window", return_value=grant) as launcher,
            patch("scripts.run_report.run_workflow", return_value=Path("output/report.html")) as workflow,
            patch("scripts.run_report.sys.stdin.isatty", return_value=True),
            patch("scripts.run_report.sys.stderr.isatty", return_value=True),
        ):
            result = main(["--market", "hk"])
        self.assertEqual(result, 0)
        launcher.assert_called_once()
        self.assertEqual(launcher.call_args.args[0], ["--market", "hk"])
        self.assertTrue(callable(launcher.call_args.kwargs["progress_callback"]))
        self.assertIs(workflow.call_args.kwargs["session_grant"], grant)
        self.assertIsNone(workflow.call_args.kwargs["credentials"])

    def test_parent_event_returns_verified_session_without_report_result(self):
        event = {
            "token": "token",
            "kind": "authenticated_session",
            "access_token": "short-lived-token",
            "username": "research-user",
            "base_url": "http://pandadata.example",
            "expires_in_seconds": 3600,
        }
        result = _handle_parent_event(event, "token")
        self.assertEqual(
            result,
            SessionGrant(
                access_token="short-lived-token",
                username="research-user",
                base_url="http://pandadata.example",
                expires_in_seconds=3600,
            ),
        )

    def test_parent_event_forwards_authenticated_session_progress_to_monitor(self):
        messages = []
        event = {
            "token": "token",
            "kind": "authenticated_session",
            "access_token": "short-lived-token",
            "username": "research-user",
            "base_url": "http://pandadata.example",
            "expires_in_seconds": 3600,
        }

        _handle_parent_event(event, "token", progress_callback=messages.append)

        self.assertIn("主进程将复用已验证会话", "\n".join(messages))
if __name__ == "__main__":
    unittest.main()
