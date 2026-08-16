import unittest
from unittest.mock import patch

import pandas as pd

import scripts.event_context as event_context
from scripts.auth_session import AuthenticationError
from scripts.event_context import (
    EVENT_COLUMNS,
    normalize_event_frame,
    resolve_event_reference_date,
)


class RecordingPandaData:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def endpoint(*, symbol, fields, start_date, end_date):
            self.calls.append({
                "method": name,
                "symbol": symbol,
                "fields": fields,
                "start_date": start_date,
                "end_date": end_date,
            })
            return pd.DataFrame()

        return endpoint


class ScenarioPandaData(RecordingPandaData):
    def __init__(self, responses=None, errors=None):
        super().__init__()
        self.responses = responses or {}
        self.errors = errors or {}

    def __getattr__(self, name):
        def endpoint(*, symbol, fields, start_date, end_date):
            self.calls.append({
                "method": name,
                "symbol": symbol,
                "fields": fields,
                "start_date": start_date,
                "end_date": end_date,
            })
            response = self.responses.get(name, pd.DataFrame())
            if isinstance(response, list):
                response = response.pop(0)
            error = self.errors.get(name)
            if isinstance(error, list):
                error = error.pop(0)
            if error:
                raise error
            return response.copy() if isinstance(response, pd.DataFrame) else response

        return endpoint


class MissingFinancialInterfacePandaData(RecordingPandaData):
    def __getattr__(self, name):
        if name == "get_stock_financial_activity":
            raise AttributeError("financial endpoint is unavailable")
        return super().__getattr__(name)


class AuthenticationOnFinancialLookupPandaData(RecordingPandaData):
    def __getattr__(self, name):
        if name == "get_stock_financial_activity":
            raise AuthenticationError("expired during endpoint lookup")
        return super().__getattr__(name)


class HttpStatusError(RuntimeError):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class EventContextTests(unittest.TestCase):
    def test_reference_date_prefers_latest_valid_core_price_date(self):
        metrics = pd.DataFrame([
            {
                "symbol": "CORE",
                "universe_eligible": True,
                "price_valid": True,
                "close": 10.0,
                "price_date": "20260717",
            },
            {
                "symbol": "BROKEN_CORE",
                "universe_eligible": True,
                "price_valid": False,
                "close": 0.0,
                "price_date": "20260720",
            },
            {
                "symbol": "ETF",
                "universe_eligible": False,
                "price_valid": True,
                "close": 12.0,
                "price_date": "20260719",
            },
        ])
        self.assertEqual(resolve_event_reference_date(metrics), "20260717")

    def test_reference_date_falls_back_to_positive_close_without_price_valid_column(self):
        metrics = pd.DataFrame([
            {
                "symbol": "CORE",
                "universe_eligible": True,
                "close": 0.0,
                "price_date": "20260720",
            },
            {
                "symbol": "ETF",
                "universe_eligible": False,
                "close": 12.0,
                "price_date": "20260718",
            },
        ])
        self.assertEqual(resolve_event_reference_date(metrics), "20260718")

    def test_reference_date_does_not_use_generation_time(self):
        self.assertIsNone(resolve_event_reference_date(pd.DataFrame([
            {"universe_eligible": True, "close": 0.0, "price_date": "invalid"},
        ])))

    def test_event_columns_are_stable_and_ordered(self):
        self.assertEqual(
            EVENT_COLUMNS,
            (
                "market", "symbol", "category", "event_type", "title",
                "publish_date", "start_date", "end_date", "is_estimated",
                "fiscal_quarter", "source_interfaces", "validation_status",
                "duplicate_count", "time_status",
            ),
        )

    def test_normalizes_standard_and_dividend_fields_without_inventing_estimate(self):
        standard, _ = normalize_event_frame(
            pd.DataFrame([{
                "symbol": "AAPL", "info_date": "20260701",
                "start_date": "20260720", "end_date": "20260720",
                "is_estimated": 1, "event_type": "EarningsReleases",
                "fiscal_quarter": "2026q3", "event": "Q3 earnings release",
            }]),
            market="us", category="financial",
            interface="get_stock_financial_activity",
            requested_symbols={"AAPL"}, reference_date="20260720",
            past_days=30, future_days=30,
        )
        self.assertEqual(list(standard.columns), list(EVENT_COLUMNS))
        self.assertEqual(standard.iloc[0]["publish_date"], "20260701")
        self.assertEqual(standard.iloc[0]["time_status"], "today")
        self.assertTrue(standard.iloc[0]["is_estimated"])
        self.assertEqual(
            standard.iloc[0]["source_interfaces"],
            ["get_stock_financial_activity"],
        )

        dividend, _ = normalize_event_frame(
            pd.DataFrame([{
                "symbol": "AAPL", "publish_date": "20260701",
                "excute_date": "20260725", "event_type": "ExDividends",
                "event": "Cash dividend",
            }]),
            market="us", category="dividend",
            interface="get_stock_dividend_activity",
            requested_symbols={"AAPL"}, reference_date="20260720",
            past_days=30, future_days=30,
        )
        self.assertEqual(dividend.iloc[0]["start_date"], "20260725")
        self.assertEqual(dividend.iloc[0]["end_date"], "20260725")
        self.assertTrue(pd.isna(dividend.iloc[0]["is_estimated"]))

    def test_classifies_inclusive_display_boundaries_and_ongoing_events(self):
        frame, counters = normalize_event_frame(
            pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260620", "end_date": "20260620", "event": "past boundary"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event": "today"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260719", "end_date": "20260721", "event": "ongoing"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260819", "end_date": "20260819", "event": "future boundary"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260619", "end_date": "20260619", "event": "outside past"},
            ]),
            market="us", category="financial", interface="financial_interface",
            requested_symbols={"AAPL"}, reference_date="20260720",
            past_days=30, future_days=30,
        )
        self.assertEqual(counters["input_rows"], 5)
        self.assertEqual(counters["display_rows"], 4)
        self.assertEqual(counters["outside_display_window_rows"], 1)
        statuses = dict(zip(frame["title"], frame["time_status"]))
        self.assertEqual(statuses["past boundary"], "recent")
        self.assertEqual(statuses["today"], "today")
        self.assertEqual(statuses["ongoing"], "ongoing")
        self.assertEqual(statuses["future boundary"], "upcoming")
        self.assertNotIn("outside past", statuses)

    def test_keeps_invalid_rows_and_reports_missing_and_unexpected_symbols(self):
        frame, counters = normalize_event_frame(
            pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260230", "end_date": "20260230", "event": "bad date"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260721", "end_date": "20260720", "event": "reversed"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event_type": "AnalystMeeting"},
                {"symbol": "MSFT", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event": "unexpected"},
                {"symbol": None, "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event": "missing symbol"},
            ]),
            market="us", category="financial", interface="financial_interface",
            requested_symbols={"AAPL"}, reference_date="20260720",
            past_days=30, future_days=30,
        )
        self.assertEqual(counters["input_rows"], 5)
        self.assertEqual(counters["display_rows"], 1)
        self.assertEqual(counters["invalid_date_rows"], 2)
        self.assertEqual(counters["missing_key_field_rows"], 1)
        self.assertEqual(counters["unexpected_symbol_rows"], 1)
        self.assertEqual(frame.iloc[2]["title"], "AnalystMeeting")
        invalid = frame[frame["validation_status"] != "valid"]
        self.assertEqual(len(invalid), 4)
        self.assertTrue((invalid["time_status"] == "invalid_date").all())

    def test_rejects_missing_dates_and_normalizes_valid_hyphenated_dates(self):
        frame, counters = normalize_event_frame(
            pd.DataFrame([
                {"symbol": "AAPL", "info_date": "2026-07-01", "start_date": "2026-07-20", "end_date": "2026-07-20", "event": "valid"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": None, "end_date": "20260720", "event": "missing date"},
            ]),
            market="us", category="financial", interface="financial_interface",
            requested_symbols={"AAPL"}, reference_date="2026-07-20",
            past_days=30, future_days=30,
        )
        self.assertEqual(frame.iloc[0]["publish_date"], "20260701")
        self.assertEqual(frame.iloc[0]["start_date"], "20260720")
        self.assertEqual(counters["missing_key_field_rows"], 1)
        self.assertEqual(frame.iloc[1]["time_status"], "invalid_date")

    def test_counts_overlapping_unexpected_symbol_and_invalid_date_diagnostics(self):
        frame, counters = normalize_event_frame(
            pd.DataFrame([{
                "symbol": "MSFT", "info_date": "20260701",
                "start_date": "20260230", "end_date": "20260230",
                "event": "unexpected malformed event",
            }]),
            market="us", category="financial", interface="financial_interface",
            requested_symbols={"AAPL"}, reference_date="20260720",
            past_days=30, future_days=30,
        )
        self.assertEqual(counters["unexpected_symbol_rows"], 1)
        self.assertEqual(counters["invalid_date_rows"], 1)
        self.assertEqual(frame.iloc[0]["validation_status"], "unexpected_symbol")
        self.assertEqual(frame.iloc[0]["time_status"], "invalid_date")


class EventCollectionTests(unittest.TestCase):
    def test_event_api_map_has_exact_documented_endpoints_and_fields(self):
        common_fields = [
            "info_date", "symbol", "start_date", "end_date", "event_type",
            "event", "is_estimated", "fiscal_quarter",
        ]
        dividend_fields = [
            "publish_date", "symbol", "excute_date", "event_type", "number",
            "currency", "event",
        ]
        self.assertEqual(event_context.EVENT_APIS, {
            "hk": {
                "dividend": ("get_stock_dividend_event", dividend_fields),
                "capital_market": ("get_stock_market_event", common_fields),
                "meeting": ("get_stock_meeting_event", common_fields),
                "financial": ("get_stock_financial_event", common_fields),
                "ir": ("get_stock_ir_event", common_fields),
            },
            "us": {
                "dividend": ("get_stock_dividend_activity", dividend_fields),
                "capital_market": ("get_stock_market_activity", common_fields),
                "meeting": ("get_stock_meeting_activity", common_fields),
                "financial": ("get_stock_financial_activity", common_fields),
                "ir": ("get_stock_ir_activity", common_fields),
            },
        })

    def test_routes_hk_event_interfaces_with_announcement_window(self):
        panda = RecordingPandaData()

        event_context.collect_market_events(
            panda,
            market="hk",
            symbols=["00700"],
            reference_date="20260720",
            discovery_days=730,
            future_days=30,
        )

        self.assertEqual(
            [call["method"] for call in panda.calls],
            [
                "get_stock_dividend_event",
                "get_stock_market_event",
                "get_stock_meeting_event",
                "get_stock_financial_event",
                "get_stock_ir_event",
            ],
        )
        self.assertTrue(all(call["symbol"] == ["00700"] for call in panda.calls))
        self.assertTrue(all(call["start_date"] == "20240720" for call in panda.calls))
        self.assertTrue(all(call["end_date"] == "20260819" for call in panda.calls))
        self.assertEqual(
            [call["fields"] for call in panda.calls],
            [spec[1] for spec in event_context.EVENT_APIS["hk"].values()],
        )

    def test_collects_batches_normalizes_display_rows_and_reports_diagnostics(self):
        panda = ScenarioPandaData({
            "get_stock_financial_activity": pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event_type": "Earnings", "event": "Q3 earnings"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260901", "end_date": "20260901", "event_type": "Earnings", "event": "Later earnings"},
            ]),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["status"], "available")
        self.assertEqual(bundle.diagnostics["event_reference_date"], "20260720")
        self.assertEqual(bundle.diagnostics["event_window_start"], "20260620")
        self.assertEqual(bundle.diagnostics["event_window_end"], "20260819")
        self.assertEqual(bundle.diagnostics["announcement_query_start"], "20240720")
        self.assertEqual(bundle.diagnostics["announcement_query_end"], "20260819")
        self.assertEqual(bundle.diagnostics["returned_rows"], 2)
        self.assertEqual(bundle.diagnostics["display_event_rows"], 1)
        self.assertEqual(bundle.diagnostics["outside_display_window_rows"], 1)
        self.assertEqual(bundle.diagnostics["returned_symbol_count"], 1)
        self.assertEqual(bundle.diagnostics["symbols_with_display_events"], 1)
        self.assertEqual(bundle.diagnostics["symbols_without_display_events"], 0)
        self.assertEqual(len(bundle.events), 1)
        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial, {
            "interface": "get_stock_financial_activity",
            "category": "financial",
            "status": "success",
            "attempts": 1,
            "batches": 1,
            "successful_batches": 1,
            "returned_rows": 2,
            "error_type": None,
            "error_message": None,
            "error_status_code": None,
        })

    def test_retries_timeout_then_records_second_attempt_success(self):
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": [TimeoutError("slow"), None],
        })

        with patch.object(event_context, "time", create=True) as time_module:
            bundle = event_context.collect_market_events(
                panda,
                market="us",
                symbols=["AAPL"],
                reference_date="20260720",
            )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["attempts"], 2)
        self.assertEqual(financial["status"], "empty")
        time_module.sleep.assert_called_once_with(0.25)

    def test_retries_http_429_then_succeeds(self):
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": [HttpStatusError(429), None],
        })

        with patch("scripts.event_context.time.sleep") as sleep:
            bundle = event_context.collect_market_events(
                panda,
                market="us",
                symbols=["AAPL"],
                reference_date="20260720",
            )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["attempts"], 2)
        sleep.assert_called_once_with(0.25)

    def test_records_non_retryable_value_error_once(self):
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": ValueError("bad parameter"),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["status"], "failed")
        self.assertEqual(financial["attempts"], 1)
        self.assertEqual(financial["error_type"], "ValueError")
        self.assertEqual(
            financial["error_message"],
            "Invalid interface response or parameters",
        )
        self.assertIsNone(financial["error_status_code"])
        self.assertEqual(
            sum(call["method"] == "get_stock_financial_activity" for call in panda.calls),
            1,
        )

    def test_isolates_failed_interface_and_returns_partial_bundle(self):
        panda = ScenarioPandaData(
            responses={
                "get_stock_market_activity": pd.DataFrame([{
                    "symbol": "AAPL", "info_date": "20260701",
                    "start_date": "20260720", "end_date": "20260720",
                    "event": "Market event",
                }]),
            },
            errors={"get_stock_financial_activity": ValueError("bad parameter")},
        )

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["status"], "partial")
        self.assertEqual(len(bundle.events), 1)
        statuses = {
            item["category"]: item["status"]
            for item in bundle.diagnostics["interface_diagnostics"]
        }
        self.assertEqual(statuses["financial"], "failed")
        self.assertEqual(statuses["capital_market"], "success")
        self.assertEqual(statuses["dividend"], "empty")
        self.assertEqual(statuses["meeting"], "empty")
        self.assertEqual(statuses["ir"], "empty")

    def test_all_failed_interfaces_reduce_top_level_status_to_unavailable(self):
        panda = ScenarioPandaData(errors={
            interface: ValueError("bad parameter")
            for interface, _ in event_context.EVENT_APIS["us"].values()
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["status"], "unavailable")
        self.assertTrue(all(
            item["status"] == "failed"
            for item in bundle.diagnostics["interface_diagnostics"]
        ))

    def test_exact_deduplicates_sorts_and_reports_title_conflicts(self):
        panda = ScenarioPandaData({
            "get_stock_financial_activity": pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event_type": "Earnings", "event": "Q3 earnings"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event_type": "Earnings", "event": "Q3 earnings"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event_type": "Earnings", "event": "Q3 earnings update"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260721", "end_date": "20260721", "event_type": "Earnings", "event": "Q3 earnings revised"},
            ]),
            "get_stock_market_activity": pd.DataFrame([{
                "symbol": "AAPL", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event_type": "Earnings", "event": "Q3 earnings",
            }]),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(len(bundle.events), 4)
        self.assertEqual(bundle.diagnostics["exact_duplicate_rows"], 1)
        self.assertEqual(bundle.diagnostics["conflict_group_count"], 1)
        financial = bundle.events[
            (bundle.events["category"] == "financial")
            & (bundle.events["title"] == "Q3 earnings")
        ].iloc[0]
        self.assertEqual(financial["duplicate_count"], 2)
        self.assertEqual(financial["source_interfaces"], ["get_stock_financial_activity"])
        self.assertEqual(
            list(bundle.events["title"]),
            ["Q3 earnings", "Q3 earnings", "Q3 earnings update", "Q3 earnings revised"],
        )

    def test_exact_deduplication_flattens_sorts_and_keeps_interface_lists(self):
        base = {
            "market": "us", "symbol": "AAPL", "category": "financial",
            "event_type": "Earnings", "title": "Q3 earnings",
            "publish_date": "20260701", "start_date": "20260720",
            "end_date": "20260720", "is_estimated": pd.NA,
            "fiscal_quarter": None, "validation_status": "valid",
            "duplicate_count": 1, "time_status": "today",
        }
        events = pd.DataFrame([
            base | {"source_interfaces": ["z_interface", "shared_interface"]},
            base | {"source_interfaces": ["a_interface", "shared_interface"]},
        ], columns=EVENT_COLUMNS)

        result, duplicate_rows = event_context._deduplicate_events(events)

        self.assertEqual(duplicate_rows, 1)
        self.assertEqual(
            result.iloc[0]["source_interfaces"],
            ["a_interface", "shared_interface", "z_interface"],
        )

    def test_isolates_missing_interface_attribute_and_collects_remaining_categories(self):
        panda = MissingFinancialInterfacePandaData()

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["status"], "partial")
        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["status"], "failed")
        self.assertEqual(financial["attempts"], 0)
        self.assertEqual(financial["batches"], 1)
        self.assertEqual(financial["successful_batches"], 0)
        self.assertEqual(financial["error_type"], "AttributeError")
        self.assertEqual(financial["error_message"], "Interface unavailable")
        self.assertIsNone(financial["error_status_code"])
        self.assertNotIn("get_stock_financial_activity", [
            call["method"] for call in panda.calls
        ])
        self.assertEqual(len(panda.calls), 4)

    def test_provenance_excludes_interface_that_was_never_invoked(self):
        panda = MissingFinancialInterfacePandaData()

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["status"], "failed")
        self.assertEqual(financial["attempts"], 0)
        self.assertNotIn(
            "get_stock_financial_activity",
            [item["interface"] for item in bundle.source_interfaces],
        )
        self.assertEqual(
            {item["interface"] for item in bundle.source_interfaces},
            {call["method"] for call in panda.calls},
        )

    def test_reraises_authentication_error_from_interface_lookup(self):
        panda = AuthenticationOnFinancialLookupPandaData()

        with self.assertRaisesRegex(AuthenticationError, "endpoint lookup"):
            event_context.collect_market_events(
                panda,
                market="us",
                symbols=["AAPL"],
                reference_date="20260720",
            )

        self.assertEqual(len(panda.calls), 3)

    def test_counts_two_independent_near_date_conflict_clusters(self):
        panda = ScenarioPandaData({
            "get_stock_financial_activity": pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260701", "end_date": "20260701", "event_type": "Earnings", "event": "First estimate"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260702", "end_date": "20260702", "event_type": "Earnings", "event": "First revision"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260710", "end_date": "20260710", "event_type": "Earnings", "event": "Second estimate"},
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260711", "end_date": "20260711", "event_type": "Earnings", "event": "Second revision"},
            ]),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["conflict_group_count"], 2)

    def test_counts_unexpected_symbol_rows_before_event_deduplication(self):
        panda = ScenarioPandaData({
            "get_stock_financial_activity": pd.DataFrame([
                {
                    "symbol": "MSFT",
                    "info_date": "20260701",
                    "start_date": "20260720",
                    "end_date": "20260720",
                    "event_type": "Roadshow",
                    "event": "Unexpected symbol",
                },
                {
                    "symbol": "MSFT",
                    "info_date": "20260701",
                    "start_date": "20260720",
                    "end_date": "20260720",
                    "event_type": "Roadshow",
                    "event": "Unexpected symbol",
                },
            ]),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["unexpected_symbol_rows"], 2)
        self.assertEqual(len(bundle.events), 1)

    def test_collection_retains_invalid_and_unexpected_rows_with_status_markers(self):
        panda = ScenarioPandaData({
            "get_stock_financial_activity": pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260230", "end_date": "20260230", "event": "Invalid date"},
                {"symbol": "MSFT", "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event": "Unexpected symbol"},
            ]),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(len(bundle.events), 2)
        self.assertEqual(
            set(bundle.events["validation_status"]),
            {"invalid_date", "unexpected_symbol"},
        )
        self.assertTrue((bundle.events["time_status"] == "invalid_date").all())

    def test_returns_unavailable_without_reference_date_or_panda_calls(self):
        panda = RecordingPandaData()

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date=None,
        )

        self.assertEqual(bundle.diagnostics["status"], "unavailable")
        self.assertEqual(panda.calls, [])
        self.assertEqual(len(bundle.diagnostics["interface_diagnostics"]), 5)
        self.assertTrue(all(
            item["status"] == "not_called"
            for item in bundle.diagnostics["interface_diagnostics"]
        ))

    def test_returns_empty_without_symbols_or_panda_calls(self):
        panda = RecordingPandaData()

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=[],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["status"], "empty")
        self.assertEqual(panda.calls, [])
        self.assertEqual(len(bundle.diagnostics["interface_diagnostics"]), 5)
        self.assertTrue(all(
            item["status"] == "not_called"
            for item in bundle.diagnostics["interface_diagnostics"]
        ))

    def test_isolates_failed_batch_and_limits_batches_to_200_symbols(self):
        symbols = [f"S{index:03d}" for index in range(201)]
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": [ValueError("bad batch"), None],
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=symbols,
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["status"], "partial")
        self.assertEqual(bundle.diagnostics["coverage_incomplete_symbol_count"], 200)
        self.assertEqual(len(panda.calls), 10)
        self.assertTrue(all(len(call["symbol"]) <= 200 for call in panda.calls))
        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["status"], "partial")
        self.assertEqual(financial["batches"], 2)
        self.assertEqual(financial["successful_batches"], 1)
        self.assertEqual(financial["attempts"], 2)

    def test_reraises_authentication_error_without_endpoint_isolation(self):
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": AuthenticationError("expired"),
        })

        with self.assertRaisesRegex(AuthenticationError, "expired"):
            event_context.collect_market_events(
                panda,
                market="us",
                symbols=["AAPL"],
                reference_date="20260720",
            )

        self.assertEqual(
            sum(call["method"] == "get_stock_financial_activity" for call in panda.calls),
            1,
        )

    def test_sanitizes_long_value_errors_to_generic_message(self):
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": ValueError("x" * 250),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(
            financial["error_message"],
            "Invalid interface response or parameters",
        )
        self.assertIsNone(financial["error_status_code"])

    def test_sanitizes_sensitive_error_text_from_interface_diagnostics(self):
        panda = ScenarioPandaData(errors={
            "get_stock_financial_activity": RuntimeError(
                "Authorization: Bearer demo-token password=hunter2"
            ),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["status"], "failed")
        self.assertEqual(financial["error_type"], "RuntimeError")
        self.assertEqual(financial["error_message"], "Interface request failed")
        self.assertIsNone(financial["error_status_code"])
        self.assertNotIn("Authorization", str(financial))
        self.assertNotIn("demo-token", str(financial))
        self.assertNotIn("hunter2", str(financial))

    def test_isolates_non_retryable_schema_error_once(self):
        panda = ScenarioPandaData(responses={
            "get_stock_financial_activity": "not a tabular response",
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        financial = next(
            item for item in bundle.diagnostics["interface_diagnostics"]
            if item["category"] == "financial"
        )
        self.assertEqual(financial["status"], "failed")
        self.assertEqual(financial["attempts"], 1)
        self.assertEqual(financial["error_type"], "ValueError")

    def test_counts_each_non_valid_normalized_row_once(self):
        panda = ScenarioPandaData({
            "get_stock_financial_activity": pd.DataFrame([
                {"symbol": "AAPL", "info_date": "20260701", "start_date": "20260230", "end_date": "20260230", "event": "bad date"},
                {"symbol": None, "info_date": "20260701", "start_date": "20260720", "end_date": "20260720", "event": "missing symbol"},
            ]),
        })

        bundle = event_context.collect_market_events(
            panda,
            market="us",
            symbols=["AAPL"],
            reference_date="20260720",
        )

        self.assertEqual(bundle.diagnostics["invalid_rows"], 2)


if __name__ == "__main__":
    unittest.main()
