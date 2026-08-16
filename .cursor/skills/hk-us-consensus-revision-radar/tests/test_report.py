import tempfile
import unittest
from pathlib import Path

from scripts.report import render_report


class ReportTests(unittest.TestCase):
    def test_data_completeness_is_collapsed_and_resets_on_market_switch_in_browser(self):
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise unittest.SkipTest(
                "Playwright is not installed; browser regression test cannot run."
            ) from exc

        def market(symbol, source, requested_symbols):
            return {
                "rows": [{"symbol": symbol, "name": symbol}],
                "rankings": {"upgrades": [symbol]},
                "quality": {
                    "core_universe_rows": requested_symbols,
                    "excluded_universe_rows": 1,
                    "eligible_rows": requested_symbols - 1,
                    "rating_eligible_rows": requested_symbols - 1,
                    "validation_error_rows": 1,
                    "validation_warning_rows": 2,
                    "validation_partial_rows": 3,
                    "currency_unverified_rows": 4,
                    "missing_name": 1,
                    "missing_price": 2,
                    "missing_history": 3,
                    "missing_recommendation": 4,
                    "missing_coverage": 5,
                },
                "sources": [source],
                "event_context": {
                    "requested_symbol_count": requested_symbols,
                    "returned_rows": requested_symbols + 10,
                    "display_event_rows": requested_symbols + 5,
                    "invalid_rows": 1,
                    "returned_symbol_count": requested_symbols,
                    "symbols_with_display_events": requested_symbols - 1,
                    "symbols_without_display_events": 1,
                    "coverage_incomplete_symbol_count": 1,
                    "exact_duplicate_rows": 0,
                    "conflict_group_count": 0,
                },
            }

        payload = {
            "horizon": "1month",
            "markets": {
                "hk": market("HK-COMPLETE", "hk_completeness_source", 11),
                "us": market("US-COMPLETE", "us_completeness_source", 22),
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            try:
                with sync_playwright() as playwright:
                    try:
                        browser = playwright.chromium.launch(headless=True)
                    except PlaywrightError as exc:
                        raise unittest.SkipTest(
                            "Chromium is unavailable for the Playwright browser regression test."
                        ) from exc
                    with browser:
                        page = browser.new_page()
                        page_errors = []
                        console_errors = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.on(
                            "console",
                            lambda message: console_errors.append(message.text)
                            if message.type == "error" else None,
                        )
                        page.goto(output.as_uri(), wait_until="networkidle")
                        page.wait_for_selector("#dataCompletenessToggle")

                        toggle = page.locator("#dataCompletenessToggle")
                        content = page.locator("#dataCompletenessContent")
                        self.assertEqual(toggle.evaluate("element => element.tagName"), "BUTTON")
                        self.assertEqual(toggle.get_attribute("type"), "button")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                        self.assertEqual(
                            toggle.get_attribute("aria-controls"), "dataCompletenessContent"
                        )
                        self.assertFalse(content.is_visible())

                        toggle.focus()
                        page.keyboard.press("Enter")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
                        self.assertTrue(content.is_visible())
                        hk_content = content.inner_text()
                        self.assertIn("hk_completeness_source", hk_content)
                        for expected in (
                            "PandaData",
                            "数据来源与接口",
                            "股票池与一致性校验",
                            "数据缺失",
                            "事件数据完整性",
                        ):
                            self.assertIn(expected, hk_content)
                        self.assertTrue(page.locator("#qualityGovernance").is_visible())
                        self.assertTrue(page.locator("#sourceProvenance").is_visible())
                        self.assertTrue(page.locator("#eventDataCompleteness").is_visible())
                        page.keyboard.press("Space")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                        self.assertFalse(content.is_visible())

                        page.locator("#marketTabs button[data-m='us']").click()
                        page.wait_for_function(
                            """() => document.querySelector('#marketTabs .active')?.dataset.m === 'us'
                                && document.querySelector('#dataCompletenessToggle')?.getAttribute('aria-expanded') === 'false'"""
                        )
                        toggle = page.locator("#dataCompletenessToggle")
                        content = page.locator("#dataCompletenessContent")
                        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                        self.assertFalse(content.is_visible())
                        toggle.click()
                        self.assertTrue(content.is_visible())
                        us_content = content.inner_text()
                        self.assertIn("us_completeness_source", us_content)
                        self.assertNotIn("hk_completeness_source", us_content)
                        self.assertIn("22", us_content)
                        self.assertEqual(page_errors, [])
                        self.assertEqual(console_errors, [])
                        no_javascript_context = browser.new_context(java_script_enabled=False)
                        try:
                            no_javascript_page = no_javascript_context.new_page()
                            no_javascript_page.goto(output.as_uri(), wait_until="load")
                            data_alert = no_javascript_page.locator("#dataAlert")
                            self.assertTrue(data_alert.is_visible())
                            fallback_content = data_alert.inner_text()
                            for expected in (
                                "数据完整性",
                                "PandaData",
                                "数据来源与接口",
                                "股票池与一致性校验",
                                "数据缺失",
                                "事件数据完整性",
                            ):
                                self.assertIn(expected, fallback_content)
                        finally:
                            no_javascript_context.close()
            finally:
                pass

    def test_report_is_standalone_and_contains_required_sections(self):
        payload = {
            "generated_at": "2026-07-15 10:00:00 +08:00",
            "horizon": "1month",
            "min_analysts": 5,
            "markets": {
                "hk": {
                    "overview": {
                        "eligible_rows": 1,
                        "upgrade_rows": 1,
                        "downgrade_rows": 0,
                        "min_analysts": 5,
                    },
                    "rows": [{
                        "symbol": "0700.HK", "name": "Tencent", "tp_revision": 0.08,
                        "tp_distance": 0.12, "dispersion": 0.15, "rating_score": 1.2,
                        "rating_change": 0.1, "tp_mean": 600, "close": 535,
                        "estimates_num": 30, "recommendations_num": 28,
                    }],
                    "rankings": {"upgrades": ["0700.HK"], "downgrades": []},
                    "quality": {"total_rows": 1, "eligible_rows": 1},
                    "sources": ["get_stock_ncycl_consensus", "get_hk_daily"],
                },
                "us": {
                    "rows": [{
                        "symbol": "AAPL", "name": "Apple", "tp_revision": -0.02,
                        "tp_distance": 0.05, "dispersion": 0.1, "rating_score": 0.8,
                        "rating_change": -0.1, "tp_mean": 240, "close": 228,
                        "estimates_num": 40, "recommendations_num": 35,
                    }],
                    "rankings": {"upgrades": [], "downgrades": ["AAPL"]},
                    "quality": {"total_rows": 1, "eligible_rows": 1},
                    "sources": ["get_stock_ncycl_estimate", "get_us_daily"],
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            result = render_report(payload, output)
            html = result.read_text(encoding="utf-8")

        self.assertIn("港美股一致预期修订雷达", html)
        self.assertIn('id="marketTabs"', html)
        self.assertNotIn('id="scatter"', html)
        self.assertNotIn('id="quality"', html)
        self.assertNotIn('securityQuality', html)
        self.assertGreater(html.index('id="dataAlert"'), html.index('id="methodologySteps"'))
        self.assertIn("\u5f02\u52a8\u699c\u5355", html)
        self.assertIn("\u65b9\u6cd5\u3001\u5047\u8bbe\u4e0e\u98ce\u9669\u8fb9\u754c", html)
        self.assertIn("window.REPORT_DATA", html)
        self.assertIn("0700.HK", html)
        self.assertIn("AAPL", html)
        self.assertIn('"upgrade_rows":1', html)
        self.assertIn("覆盖数缺失", html)
        self.assertNotIn(
            'const up=r.filter(x=>x.revision_direction==="upgrade").length',
            html,
        )
        self.assertNotIn("http://", html.lower())
        self.assertNotIn("https://", html.lower())
        self.assertNotIn("PANDADATA_USERNAME", html)
        self.assertNotIn("PANDADATA_PASSWORD", html)
        self.assertNotIn("token", html.lower())

    def test_ranking_table_exposes_inputs_and_calculation_formulas(self):
        payload = {
            'generated_at': '2026-07-17 10:00:00 +08:00',
            'horizon': '1month',
            'min_analysts': 5,
            'markets': {
                'hk': {
                    'rows': [{
                        'symbol': '0700.HK', 'name': 'Tencent',
                        'tp_mean': 120.0, 'tp_mean_1month': 100.0,
                        'close': 80.0, 'tp_revision': 0.2,
                        'tp_distance': 0.5, 'dispersion': 0.2,
                        'estimates_num': 8,
                    }],
                    'rankings': {'upgrades': ['0700.HK']},
                    'quality': {'total_rows': 1, 'eligible_rows': 1},
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'report.html'
            render_report(payload, output)
            html = output.read_text(encoding='utf-8')

        self.assertIn('前目标价均值', html)
        self.assertIn('当前目标价均值', html)
        self.assertIn('最新收盘价', html)
        self.assertIn('修订 = 当前目标价均值 ÷', html)
        self.assertIn('价格偏离 = 当前目标价均值 ÷', html)
        self.assertIn('分歧 = 目标价标准差 ÷', html)
        self.assertIn('覆盖 = estimates_num', html)

    def test_detail_panel_is_prominent_below_ranking_panel(self):
        payload = {
            'markets': {
                'hk': {
                    'rows': [],
                    'rankings': {},
                    'quality': {},
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'report.html'
            render_report(payload, output)
            html = output.read_text(encoding='utf-8')

        ranking_position = html.index('ranking-panel')
        detail_section_position = html.index('class="detail-section reveal"')
        self.assertLess(ranking_position, detail_section_position)
        self.assertIn('class="panel detail-panel"', html)
        self.assertIn('.detail-section{', html)
        self.assertIn('.detail-panel{padding:', html)
    def test_payload_is_escaped_inside_script_context(self):
        payload = {"markets": {}, "note": "</script><script>alert(1)</script>"}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert(1)</script>", html)
        self.assertIn("\\u003c/script", html)


    def test_report_prioritizes_key_findings_and_preserves_missing_values(self):
        payload = {
            "generated_at": "2026-07-16 09:00:00 +08:00",
            "horizon": "1month",
            "min_analysts": 5,
            "markets": {
                "us": {
                    "rows": [{
                        "symbol": "MISS", "name": "Missing Price",
                        "tp_revision": 0.25, "tp_distance": None,
                        "dispersion": 0.3, "rating_change": 0.2,
                        "tp_mean": 10.0, "close": None, "estimates_num": 8,
                    }],
                    "rankings": {
                        "upgrades": ["MISS"], "downgrades": [],
                        "high_dispersion": ["MISS"], "rating_changes": ["MISS"],
                        "price_consensus_divergence": [],
                    },
                    "quality": {
                        "total_rows": 1, "eligible_rows": 1,
                        "excluded_low_coverage": 0, "missing_target_price": 0,
                        "missing_price": 1, "missing_history": 0,
                    },
                    "sources": ["get_stock_ncycl_estimate", "get_us_daily"],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn('id="dataAlert"', html)
        self.assertIn('id="brief"', html)
        self.assertIn('id="movers"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("requestAnimationFrame", html)
        self.assertIn('v===null||v===undefined||v===""', html)
        self.assertIn("\u4ef7\u683c\u6570\u636e\u7f3a\u5931", html)


    def test_report_exposes_security_evidence_methodology_and_diagnostics(self):
        payload = {
            "generated_at": "2026-07-16 10:00:00 +08:00",
            "horizon": "1month",
            "min_analysts": 5,
            "revision_threshold": 0.01,
            "markets": {
                "hk": {
                    "rows": [{
                        "symbol": "0700.HK", "name": "腾讯控股",
                        "tp_mean": 600.0, "tp_mean_1month": 570.0,
                        "tp_revision_abs": 30.0, "tp_revision": 0.0526,
                        "revision_direction": "upgrade", "revision_threshold": 0.01,
                        "tp_median": 595.0, "tp_high": 700.0, "tp_low": 480.0,
                        "tp_std": 42.0, "estimates_num": 30,
                        "included_estimates_num": 28, "included_ratio": 0.9333,
                        "strong_buy_num": 10, "buy_num": 12, "hold": 6,
                        "sell_num": 1, "strong_sell_num": 0,
                        "no_opinion_num": 1, "recommendations_num": 30,
                        "rec_mean": 1.5, "rec_mean_1month": 1.8,
                        "rating_change": 0.3, "rating_direction": "improved",
                        "close": 535.0, "price_date": "20260715",
                        "tp_distance": 0.1215, "dispersion": 0.07,
                        "name_source": "get_hk_detail",
                    }],
                    "rankings": {
                        "upgrades": [{"symbol": "0700.HK", "name": "腾讯控股",
                                      "tp_revision": 0.0526}],
                        "downgrades": [], "high_dispersion": [],
                        "rating_changes": [], "price_consensus_divergence": [],
                    },
                    "quality": {
                        "total_rows": 1, "eligible_rows": 1,
                        "name_coverage": 1.0, "price_coverage": 1.0,
                        "history_coverage": 1.0, "recommendation_coverage": 1.0,
                        "scatter_eligible_rows": 1, "scatter_coverage": 1.0,
                    },
                    "diagnostics": {
                        "requested_latest_date": "20260715",
                        "price_initial_rows": 0, "price_fallback_used": True,
                        "price_matched_symbols": 1, "price_universe_symbols": 1,
                        "price_match_rate": 1.0, "price_date_max": "20260715",
                    },
                    "methodology": {
                        "revision_threshold": 0.01,
                        "consensus_level": "aggregate",
                    },
                    "sources": ["get_hk_detail", "get_hk_daily",
                                "get_stock_ncycl_consensus"],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn('"targetEvidence"', html)
        self.assertIn('"recommendationEvidence"', html)
        self.assertIn('"priceEvidence"', html)
        self.assertIn('id="methodologySteps"', html)
        self.assertIn('id="dataAlert"', html)
        self.assertGreater(html.index('id="dataAlert"'), html.index('id="methodologySteps"'))
        self.assertIn("identityLabel", html)
        self.assertIn("revision_threshold", html)
        self.assertIn("聚合一致预期", html)
        self.assertIn("修订广度", html)
        self.assertIn("腾讯控股", html)
        self.assertIn("0700.HK", html)
    def test_report_explicitly_discloses_pandadata_completeness_gaps(self):
        payload = {
            "generated_at": "2026-07-17 15:00:00 +08:00",
            "horizon": "1month",
            "min_analysts": 5,
            "markets": {
                "us": {
                    "rows": [],
                    "rankings": {},
                    "quality": {
                        "total_rows": 10,
                        "missing_name": 1,
                        "missing_price": 2,
                        "missing_history": 3,
                        "missing_recommendation": 4,
                        "missing_coverage": 5,
                    },
                    "diagnostics": {
                        "price_match_rate": 0.8,
                        "price_matched_symbols": 8,
                        "price_universe_symbols": 10,
                        "price_fallback_used": True,
                    },
                    "sources": ["get_us_daily"],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("PandaData", html)
        self.assertIn("价格匹配率", html)
        self.assertIn("分析师覆盖数缺失", html)
        self.assertIn("推荐数据缺失", html)
    def test_report_exposes_source_interfaces_and_security_charts(self):
        payload = {
            "generated_at": "2026-07-17 16:00:00 +08:00",
            "horizon": "1month",
            "markets": {
                "hk": {
                    "rows": [{
                        "symbol": "0700.HK",
                        "name": "Tencent",
                        "tp_mean": 600.0,
                        "tp_mean_1month": 570.0,
                        "tp_low": 480.0,
                        "tp_high": 700.0,
                        "close": 535.0,
                        "strong_buy_num": 8,
                        "buy_num": 12,
                        "hold": 5,
                        "sell_num": 1,
                        "strong_sell_num": 0,
                        "no_opinion_num": 1,
                    }],
                    "rankings": {"upgrades": ["0700.HK"]},
                    "quality": {},
                    "source_interfaces": [{
                        "interface": "get_stock_ncycl_consensus",
                        "purpose": "target-price consensus",
                    }],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("get_stock_ncycl_consensus", html)
        self.assertIn("target-price consensus", html)
        self.assertIn('"targetPositionChart"', html)
        self.assertIn('"ratingDistributionChart"', html)
        self.assertIn("function targetChart", html)
        self.assertIn("function ratingChart", html)

    def test_report_renders_event_context_timeline_and_diagnostics(self):
        malicious_title = "Results </script><img onerror=alert(1)>"
        payload = {
            "generated_at": "2026-07-20 18:00:00 +08:00",
            "horizon": "1month",
            "markets": {
                "hk": {
                    "rows": [{
                        "symbol": "0700.HK", "name": "Tencent",
                        "tp_mean": 600.0, "tp_mean_1month": 570.0,
                        "price_date": "20260718",
                    }],
                    "rankings": {"upgrades": ["0700.HK"]},
                    "quality": {},
                    "source_interfaces": [
                        "get_stock_dividend_event",
                        "get_stock_market_event",
                        "get_stock_meeting_event",
                        "get_stock_financial_event",
                        "get_stock_ir_event",
                    ],
                    "events": [
                        {
                            "market": "hk", "symbol": "0700.HK",
                            "category": "financial", "event_type": "Results",
                            "title": malicious_title, "publish_date": "20260701",
                            "start_date": "20260718", "end_date": "20260718",
                            "is_estimated": False, "fiscal_quarter": "2026Q2",
                            "source_interfaces": ["get_stock_financial_event"],
                            "validation_status": "valid", "duplicate_count": 1,
                            "time_status": "recent",
                        },
                        {
                            "market": "hk", "symbol": "0700.HK",
                            "category": "meeting", "event_type": "AGM",
                            "title": "Annual meeting", "publish_date": "20260710",
                            "start_date": "20260725", "end_date": "20260725",
                            "is_estimated": True, "fiscal_quarter": None,
                            "source_interfaces": ["get_stock_meeting_event"],
                            "validation_status": "valid", "duplicate_count": 1,
                            "time_status": "upcoming",
                        },
                        {
                            "market": "hk", "symbol": "0700.HK",
                            "category": "ir", "event_type": "Roadshow",
                            "title": "Investor roadshow", "publish_date": "20260712",
                            "start_date": "20260719", "end_date": "20260721",
                            "is_estimated": False, "fiscal_quarter": None,
                            "source_interfaces": ["get_stock_ir_event"],
                            "validation_status": "valid", "duplicate_count": 2,
                            "time_status": "ongoing",
                        },
                        {
                            "market": "hk", "symbol": "0700.HK",
                            "category": "capital_market", "event_type": "Invalid",
                            "title": "Invalid retained for diagnostics",
                            "publish_date": "20260701", "start_date": "20260230",
                            "end_date": "20260230", "is_estimated": False,
                            "fiscal_quarter": None,
                            "source_interfaces": ["get_stock_market_event"],
                            "validation_status": "invalid_date", "duplicate_count": 1,
                            "time_status": "invalid_date",
                        },
                    ],
                    "event_context": {
                        "status": "partial",
                        "event_reference_date": "20260720",
                        "event_window_start": "20260620",
                        "event_window_end": "20260819",
                        "announcement_query_start": "20240720",
                        "announcement_query_end": "20260819",
                        "event_past_days": 30, "event_future_days": 30,
                        "event_discovery_days": 730,
                        "requested_symbol_count": 1, "returned_symbol_count": 1,
                        "symbols_with_display_events": 1,
                        "symbols_without_display_events": 0,
                        "coverage_incomplete_symbol_count": 1,
                        "returned_rows": 5, "display_event_rows": 3,
                        "invalid_rows": 1, "unexpected_symbol_rows": 1,
                        "outside_display_window_rows": 1,
                        "exact_duplicate_rows": 1, "conflict_group_count": 1,
                        "interface_diagnostics": [
                            {"interface": "get_stock_dividend_event", "category": "dividend", "status": "success", "attempts": 1, "returned_rows": 0},
                            {"interface": "get_stock_market_event", "category": "capital_market", "status": "failed", "attempts": 1, "returned_rows": 0},
                            {"interface": "get_stock_meeting_event", "category": "meeting", "status": "success", "attempts": 1, "returned_rows": 1},
                            {"interface": "get_stock_financial_event", "category": "financial", "status": "success", "attempts": 1, "returned_rows": 2},
                            {"interface": "get_stock_ir_event", "category": "ir", "status": "success", "attempts": 1, "returned_rows": 1},
                        ],
                        "discovery_limitation": "PandaData事件接口按公告日期筛选；早于公告发现窗口发布的窗口内事件可能无法发现。",
                    },
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        for dom_id in ("eventMarketOverview", "eventTimeline", "eventDataCompleteness"):
            self.assertIn(dom_id, html)
        self.assertIn("事件上下文", html)
        self.assertIn("PandaData事件接口按公告日期筛选", html)
        for purpose in (
            "港股分红拆股事件", "港股资本市场事件", "港股公司会议事件",
            "港股财务披露事件", "港股投资者关系事件",
            "美股分红拆股活动", "美股资本市场活动", "美股公司会议活动",
            "美股财务披露活动", "美股投资者关系活动",
        ):
            self.assertIn(purpose, html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn('"source_interfaces":["get_stock_financial_event"]', html)
        self.assertNotIn(malicious_title, html)
        self.assertNotIn("http://", html.lower())
        self.assertNotIn("https://", html.lower())
        self.assertNotIn("<script src=", html.lower())
        self.assertNotIn("<link href=", html.lower())

        self.assertIn('event.validation_status === "valid" && event.time_status !== "invalid_date"', html)
        self.assertIn('event.validation_status === "unexpected_symbol"', html)
        self.assertIn('String(event.symbol) === String(symbol)', html)
        self.assertIn('const payloadState = context.status;', html)
        self.assertIn('querySelectorAll(".event-context-head,.event-context-cell")', html)
        self.assertIn('eventOriginalRank', html)
        self.assertIn('if (!Object.prototype.hasOwnProperty.call(tr.dataset, "eventBaseHidden"))', html)
        self.assertIn('tr.dataset.eventBaseHidden = tr.hidden ? "true" : "false"', html)
        self.assertIn('const baseHidden = tr.dataset.eventBaseHidden === "true"', html)
        self.assertIn('tr.hidden = baseHidden || eventCategory !== "all" && filteredEvents.length === 0', html)
        self.assertIn("eventCategoryFilters", html)
        for label in ("全部", "财务披露", "投资者关系", "公司会议", "资本市场", "分红拆股"):
            self.assertIn(label, html)
        self.assertIn("slice(0, 8)", html)
        self.assertIn("查看全部（", html)
        self.assertIn("event-accessible-list", html)
        self.assertIn('interpretation.insertAdjacentElement("afterend", timeline)', html)
        self.assertIn('make("h3", displayValue(event.title)', html)
        for state in ("当前窗口无事件", "事件接口部分可用", "事件模块不可用", "事件模块已关闭"):
            self.assertIn(state, html)
        self.assertIn("事件市场概览", html)
        self.assertIn("完全重复记录合并", html)
        self.assertIn("相邻日期冲突组", html)
        self.assertIn("检测到相邻日期冲突", html)
        self.assertIn("接口状态、尝试次数与返回行数", html)
        self.assertIn("价格日期早于事件参考日", html)

    def test_report_keeps_extension_assets_inside_document(self):
        payload = {"markets": {"hk": {"rows": [], "rankings": {}, "quality": {}}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertEqual(html.count("</html>"), 1)
        self.assertLess(html.index("<style>.detail-charts"), html.index("</head>"))
        self.assertLess(html.index("<script>\n(function ()"), html.index("</body>"))

    def test_report_extension_uses_safe_dom_chart_markers(self):
        payload = {"markets": {"hk": {"rows": [], "rankings": {}, "quality": {}}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn('setAttribute("data-chart-role", role)', html)
        self.assertIn('role === "target" ? "targetPositionChart" : "ratingDistributionChart"', html)
        self.assertIn('identityText.endsWith(" · " + String(item.symbol))', html)
        self.assertIn('.detail-charts{grid-column:1/-1;display:block', html)
        self.assertIn('ledger.insertBefore(ratingSlot, recommendation)', html)

    def test_target_chart_reserves_readable_label_and_value_columns(self):
        payload = {"markets": {"hk": {"rows": [], "rankings": {}, "quality": {}}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn(
            '.detail-charts .rating-row{grid-template-columns:minmax(88px,110px) minmax(220px,1fr) minmax(64px,76px);gap:10px}',
            html,
        )
        self.assertIn('.detail-charts .rating-track{min-width:0}', html)
        self.assertIn(
            '@media(max-width:560px){.detail-charts .rating-row{grid-template-columns:minmax(78px,82px) minmax(0,1fr) minmax(58px,62px);gap:8px}}',
            html,
        )

    def test_rating_chart_hides_zero_width_bars_but_keeps_zero_values(self):
        payload = {"markets": {"hk": {"rows": [], "rankings": {}, "quality": {}}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn(
            'value === 0 ? "0%" : Math.max(2, value / total * 100)',
            html,
        )
        self.assertIn('make("b", String(value))', html)

    def test_report_discloses_core_universe_separate_thresholds_and_reasons(self):
        payload = {
            "min_analysts": 5,
            "min_recommendations": 8,
            "markets": {
                "us": {
                    "rows": [], "rankings": {},
                    "overview": {"min_analysts": 5, "min_recommendations": 8},
                    "quality": {
                        "core_universe_rows": 10,
                        "excluded_universe_rows": 2,
                        "eligible_rows": 7,
                        "rating_eligible_rows": 4,
                        "validation_error_rows": 1,
                        "universe_exclusion_reasons": {"non_ordinary_security": 2},
                        "price_missing_reasons": {"not_returned_by_api": 1},
                    },
                    "source_interfaces": [
                        {"interface": "get_us_detail", "purpose": "证券名称、状态、类型与行业身份"}
                    ],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("股票池与一致性校验", html)
        self.assertIn("min_recommendations", html)
        self.assertIn("目标价可排名", html)
        self.assertIn("评级可排名", html)
        self.assertIn("universe_exclusion_reasons", html)
        self.assertIn("price_missing_reasons", html)
        self.assertIn("评级覆盖", html)

    def test_report_exposes_time_coverage_change_and_eligibility_funnels(self):
        payload = {
            "generated_at": "2026-07-20 15:10:00 +0800",
            "horizon": "1month",
            "markets": {"hk": {
                "rows": [{
                    "symbol": "0700.HK", "name": "Tencent",
                    "tp_mean": 110.0, "tp_mean_1month": 100.0,
                    "estimates_num": 12, "estimates_num_1month": 10,
                    "estimates_change_abs": 2,
                    "estimates_change_ratio": 0.2,
                    "included_estimates_num": 9,
                    "included_estimates_num_1month": 7,
                    "included_estimates_change_abs": 2,
                    "included_estimates_change_ratio": 2 / 7,
                    "coverage_change_status": "significant",
                    "coverage_change_note": "目标价均值变化可能受到聚合样本构成变化影响",
                }],
                "rankings": {"upgrades": [{"symbol": "0700.HK"}]},
                "quality": {}, "overview": {},
                "diagnostics": {
                    "consensus_retrieved_at": "2026-07-20 15:00:00 +0800",
                    "consensus_as_of": None,
                    "historical_snapshot_label": "1month",
                    "historical_snapshot_as_of": None,
                },
                "eligibility_funnels": {
                    "target_revision": [
                        {"key": "total", "label": "全部记录", "count": 1,
                         "retention": None},
                        {"key": "revision_eligible", "label": "修订榜可排名", "count": 1,
                         "retention": 1.0},
                    ],
                    "rating": [
                        {"key": "total", "label": "全部记录", "count": 1,
                         "retention": None},
                        {"key": "rating_eligible", "label": "评级榜可排名", "count": 1,
                         "retention": 1.0},
                    ],
                },
            }},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("consensusTimeDisclosure", html)
        self.assertIn("coverageChangeEvidence", html)
        self.assertIn("eligibilityFunnels", html)
        self.assertIn("PandaData 最新可用快照", html)
        self.assertIn("PandaData 未提供具体业务日期", html)
        self.assertIn("目标价修订榜资格漏斗", html)
        self.assertIn("评级榜资格漏斗", html)
        self.assertIn("目标价均值变化可能受到聚合样本构成变化影响", html)

    def test_extension_numeric_formatter_preserves_null_as_missing(self):
        payload = {"markets": {"hk": {"rows": [], "rankings": {}, "quality": {}}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn(
            'const finite = value => value === null || value === undefined || value === "" ? null',
            html,
        )

    def test_report_renders_trajectory_matrix_and_state_module_with_safe_empty_fallbacks(self):
        payload = {
            "horizon": "1month",
            "markets": {"hk": {
                "rows": [{"symbol": "0700.HK", "name": "Tencent"}],
                "rankings": {}, "quality": {},
                "trajectory_matrix": [{
                    "symbol": "0700.HK", "name": "Tencent", "industry_group": "互联网",
                    "target_price_trajectory": [{"horizon": "week", "change": 0.1, "direction": "positive"}],
                    "rating_trajectory": [{"horizon": "week", "change": -0.1, "direction": "negative"}],
                    "consensus_states": [{
                        "label": "持续上修", "explanation": "多个回看期为正向。",
                        "evidence": {"horizon": "1month", "current": 1.8, "historical": 2.0},
                    }],
                    "dispersion_p75": 0.2, "dispersion_sample_count": 10,
                }],
            }},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        for expected in (
            "修订轨迹矩阵", "名称 · 代码", "行业", "目标价修订", "评级修订",
            "周度", "1个月", "3个月", "6个月", "12个月", "持续上修",
            "历史评级均值 − 当前评级均值", "不构成投资建议", "状态为规则化研究分类",
            "P75", "样本数", "覆盖变化", "暂无轨迹矩阵数据", "暂无状态数据",
        ):
            self.assertIn(expected, html)

        for expected_css in (
            ".trajectory-wrap{max-height:520px;overflow:auto",
            ".trajectory-table{min-width:1420px;table-layout:fixed",
            ".trajectory-table th{position:sticky;top:0",
            ".trajectory-table th:first-child,.trajectory-table td:first-child{position:sticky;left:0",
            ".trajectory-table th:nth-child(2),.trajectory-table td:nth-child(2){position:sticky;left:220px",
            ".trajectory-table th:nth-child(n+3),.trajectory-table td:nth-child(n+3){min-width:104px",
            ".trajectory-signal{display:block;white-space:nowrap",
            "@media(max-width:560px){.trajectory-wrap{max-height:420px",
        ):
            self.assertIn(expected_css, html)

    def test_trajectory_matrix_uses_bounded_scroll_container_in_browser(self):
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise unittest.SkipTest(
                "Playwright is not installed; browser regression test cannot run."
            ) from exc

        horizons = ("week", "1month", "3month", "6month", "12month")
        trajectory_matrix = []
        for index in range(24):
            trajectory_matrix.append({
                "symbol": f"{700 + index:04d}.HK",
                "name": f"Browser Regression Stock {index + 1}",
                "industry_group": "Internet Services",
                "target_price_trajectory": [
                    {"horizon": horizon, "change": 0.01, "direction": "positive"}
                    for horizon in horizons
                ],
                "rating_trajectory": [
                    {"horizon": horizon, "change": -0.01, "direction": "negative"}
                    for horizon in horizons
                ],
            })
        payload = {
            "horizon": "1month",
            "markets": {"hk": {
                "rows": [{"symbol": row["symbol"], "name": row["name"]}
                         for row in trajectory_matrix],
                "rankings": {},
                "quality": {},
                "trajectory_matrix": trajectory_matrix,
            }},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            try:
                with sync_playwright() as playwright:
                    try:
                        browser = playwright.chromium.launch(headless=True)
                    except PlaywrightError as exc:
                        raise unittest.SkipTest(
                            "Chromium is unavailable for the Playwright browser regression test."
                        ) from exc
                    with browser:
                        page = browser.new_page(viewport={"width": 1280, "height": 900})
                        page_errors = []
                        console_errors = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.on(
                            "console",
                            lambda message: console_errors.append(message.text)
                            if message.type == "error" else None,
                        )
                        page.goto(output.as_uri(), wait_until="networkidle")
                        page.wait_for_selector(".trajectory-wrap")

                        desktop = page.evaluate("""() => {
                            const wrap = document.querySelector('.trajectory-wrap');
                            const table = document.querySelector('.trajectory-table');
                            return {
                                maxHeight: getComputedStyle(wrap).maxHeight,
                                scrollHeight: wrap.scrollHeight,
                                clientHeight: wrap.clientHeight,
                                headerPosition: getComputedStyle(table.querySelector('th')).position,
                                firstColumnPosition: getComputedStyle(table.querySelector('td:first-child')).position,
                                secondColumnPosition: getComputedStyle(table.querySelector('td:nth-child(2)')).position,
                                thirdColumnWhiteSpace: getComputedStyle(table.querySelector('td:nth-child(3)')).whiteSpace,
                            };
                        }""")
                        self.assertEqual(desktop["maxHeight"], "520px")
                        self.assertGreater(desktop["scrollHeight"], desktop["clientHeight"])
                        self.assertEqual(desktop["headerPosition"], "sticky")
                        self.assertEqual(desktop["firstColumnPosition"], "sticky")
                        self.assertEqual(desktop["secondColumnPosition"], "sticky")
                        self.assertEqual(desktop["thirdColumnWhiteSpace"], "nowrap")

                        page.set_viewport_size({"width": 500, "height": 900})
                        mobile = page.evaluate("""() => {
                            const wrap = document.querySelector('.trajectory-wrap');
                            const style = getComputedStyle(wrap);
                            return {maxHeight: style.maxHeight, overflowY: style.overflowY};
                        }""")
                        self.assertEqual(mobile["maxHeight"], "420px")
                        self.assertIn(mobile["overflowY"], ("auto", "scroll"))
                        self.assertEqual(page_errors, [])
                        self.assertEqual(console_errors, [])
            finally:
                pass

    def test_report_renders_trajectory_search_and_security_trajectory(self):
        horizons = ("week", "1month", "3month", "6month", "12month")
        def trajectory(change, direction):
            return [
                {"horizon": horizon, "change": change, "direction": direction}
                for horizon in horizons
            ]

        payload = {
            "horizon": "1month",
            "markets": {"hk": {
                "rows": [
                    {"symbol": "0001.HK", "name": "Alpha"},
                    {"symbol": "0002.HK", "name": "Beta"},
                ],
                "rankings": {"upgrades": ["0001.HK"]},
                "quality": {},
                "trajectory_matrix": [
                    {
                        "symbol": "0001.HK", "name": "Alpha",
                        "target_price_trajectory": trajectory(0.1, "positive"),
                        "rating_trajectory": trajectory(-0.1, "negative"),
                    },
                    {
                        "symbol": "0002.HK", "name": "Beta",
                        "target_price_trajectory": trajectory(0.02, "positive"),
                        "rating_trajectory": trajectory(0, "flat"),
                    },
                ],
            }},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        for expected in (
            'search.id = "trajectorySearch"', 'count.id = "trajectorySearchCount"',
            'empty.id = "trajectorySearchEmpty"', 'section.id = "securityTrajectory"',
            "匹配", "暂无该个股修订轨迹数据",
        ):
            self.assertIn(expected, html)

    def test_trajectory_search_filters_name_and_symbol_in_browser(self):
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise unittest.SkipTest(
                "Playwright is not installed; browser regression test cannot run."
            ) from exc

        horizons = ("week", "1month", "3month", "6month", "12month")
        def trajectory(change, direction):
            return [
                {"horizon": horizon, "change": change, "direction": direction}
                for horizon in horizons
            ]

        def market(rows):
            return {
                "rows": [
                    {"symbol": symbol, "name": name}
                    for symbol, name, _change in rows
                ],
                "rankings": {"upgrades": [rows[0][0]]},
                "quality": {},
                "trajectory_matrix": [
                    {
                        "symbol": symbol,
                        "name": name,
                        "target_price_trajectory": trajectory(change, "positive"),
                        "rating_trajectory": trajectory(-change, "negative"),
                    }
                    for symbol, name, change in rows
                ],
            }

        payload = {
            "horizon": "1month",
            "markets": {
                "hk": market([
                    ("0001.HK", "Harbor Alpha", 0.1),
                    ("0002.HK", "Harbor Beta", 0.02),
                ]),
                "us": market([
                    ("USAA", "United Aurora", 0.03),
                    ("USBB", "United Beacon", 0.04),
                ]),
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            try:
                with sync_playwright() as playwright:
                    try:
                        browser = playwright.chromium.launch(headless=True)
                    except PlaywrightError as exc:
                        raise unittest.SkipTest(
                            "Chromium is unavailable for the Playwright browser regression test."
                        ) from exc
                    with browser:
                        page = browser.new_page()
                        page_errors = []
                        console_errors = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.on(
                            "console",
                            lambda message: console_errors.append(message.text)
                            if message.type == "error" else None,
                        )
                        page.goto(output.as_uri(), wait_until="networkidle")
                        page.wait_for_selector("#trajectorySearch")

                        def visible_rows():
                            return page.locator("#trajectoryMatrix tbody tr:visible").count()

                        search = page.locator("#trajectorySearch")
                        search.fill("hArBoR aLpHa")
                        self.assertEqual(visible_rows(), 1)
                        self.assertEqual(
                            page.locator("#trajectorySearchCount").inner_text(),
                            "匹配 1 / 总计 2",
                        )
                        self.assertIn(
                            "Harbor Alpha",
                            page.locator("#trajectoryMatrix tbody tr:visible").inner_text(),
                        )

                        search.fill("0002.hK")
                        self.assertEqual(visible_rows(), 1)
                        self.assertEqual(
                            page.locator("#trajectorySearchCount").inner_text(),
                            "匹配 1 / 总计 2",
                        )
                        self.assertIn(
                            "Harbor Beta",
                            page.locator("#trajectoryMatrix tbody tr:visible").inner_text(),
                        )

                        search.fill("not-a-hk-security")
                        self.assertEqual(visible_rows(), 0)
                        self.assertTrue(page.locator("#trajectorySearchEmpty").is_visible())

                        search.fill("")
                        self.assertEqual(visible_rows(), 2)
                        self.assertEqual(
                            page.locator("#trajectorySearchCount").inner_text(),
                            "匹配 2 / 总计 2",
                        )

                        page.locator("#rankingTable button.symbol").click()
                        page.wait_for_selector("#securityTrajectory")
                        self.assertTrue(page.locator("#securityTrajectory").is_visible())
                        self.assertEqual(
                            page.locator("#securityTrajectory tbody tr").count(),
                            5,
                        )
                        self.assertEqual(
                            page.locator("#securityTrajectory tbody tr td:first-child")
                            .all_inner_texts(),
                            ["周度", "1个月", "3个月", "6个月", "12个月"],
                        )

                        page.locator("#marketTabs button[data-m='us']").click()
                        page.wait_for_function(
                            """() => document.querySelector('#marketTabs .active')?.dataset.m === 'us'
                                && document.querySelector('#trajectorySearch')?.value === ''"""
                        )
                        search = page.locator("#trajectorySearch")
                        self.assertEqual(search.input_value(), "")
                        self.assertEqual(visible_rows(), 2)
                        self.assertEqual(
                            page.locator("#trajectorySearchCount").inner_text(),
                            "匹配 2 / 总计 2",
                        )
                        us_rows = page.locator("#trajectoryMatrix tbody tr:visible").all_inner_texts()
                        self.assertEqual(len(us_rows), 2)
                        self.assertTrue(all("United" in row for row in us_rows))
                        self.assertTrue(all("Harbor" not in row for row in us_rows))

                        search.fill("harbor alpha")
                        self.assertEqual(visible_rows(), 0)
                        self.assertTrue(page.locator("#trajectorySearchEmpty").is_visible())

                        search.fill("")
                        self.assertEqual(visible_rows(), 2)
                        self.assertEqual(
                            page.locator("#trajectorySearchCount").inner_text(),
                            "匹配 2 / 总计 2",
                        )
                        self.assertEqual(page_errors, [])
                        self.assertEqual(console_errors, [])
            finally:
                pass

    def test_report_uses_correct_rating_level_and_change_wording(self):
        payload = {"markets": {"hk": {"rows": [], "rankings": {}, "quality": {}}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            render_report(payload, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("评级均值越低代表评级更积极", html)
        self.assertIn("历史评级均值 − 当前评级均值越大代表评级改善/更积极", html)
        self.assertNotIn("评级变化 = 历史评级均值 − 当前评级均值；数值越低代表评级更积极", html)
if __name__ == "__main__":
    unittest.main()
