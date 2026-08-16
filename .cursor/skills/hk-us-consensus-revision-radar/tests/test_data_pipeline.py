import unittest

import pandas as pd

import scripts.data_pipeline as data_pipeline
from scripts.data_pipeline import (
    _parse_latest_trade_date, collect_market_data, normalize_market_frames,
)


class FakePandaData:
    def __init__(self):
        self.calls = []

    def get_stock_ncycl_consensus(self, **kwargs):
        self.calls.append(("get_stock_ncycl_consensus", kwargs))
        return pd.DataFrame(
            [
                {"symbol": "0700.HK", "indicator": "TP", "mean": 700.0, "std": 40.0,
                 "currency": "HKD",
                 "estimates_num": 30, "included_estimates_num": 28, "mean_week": 690.0,
                 "mean_1month": 650.0, "mean_3month": 620.0, "mean_6month": 600.0,
                 "mean_12month": 580.0},
                {"symbol": "0700.HK", "indicator": "LTGROWTH", "mean": 18.0},
                {"symbol": "9999.HK", "indicator": "TP", "mean": None, "std": None,
                 "estimates_num": None, "mean_1month": 12.0},
            ]
        )

    def get_stock_recommendation_consensus(self, **kwargs):
        self.calls.append(("get_stock_recommendation_consensus", kwargs))
        return pd.DataFrame(
            [
                {"symbol": "0700.HK", "mean": 1.4, "strong_buy_num": 10, "buy_num": 12,
                 "hold": 6, "sell_num": 1, "strong_sell_num": 0, "no_opinion_num": 0,
                 "recommendations_num": 29, "mean_week": 1.5, "mean_1month": 1.7,
                 "mean_3month": 1.8},
                {"symbol": "9999.HK", "mean": None, "recommendations_num": None},
            ]
        )

    def get_hk_daily(self, **kwargs):
        self.calls.append(("get_hk_daily", kwargs))
        return pd.DataFrame(
            [
                {"symbol": "0700.HK", "date": "20260713", "close": 610.0,
                 "volume": 90.0, "amount": 54900.0, "name": "Tencent"},
                {"symbol": "0700.HK", "date": "20260714", "close": 620.0,
                 "volume": 100.0, "amount": 62000.0, "name": "Tencent"},
            ]
        )

    def get_hk_detail(self, **kwargs):
        self.calls.append(("get_hk_detail", kwargs))
        return pd.DataFrame(
            [
                {
                    "symbol": "0700.HK", "name": "TENCENT HOLDINGS LIMITED",
                    "cn_name": "腾讯控股", "local_name": "腾讯控股有限公司",
                    "status": 1, "trading_code": "0700",
                    "rcs_asset_category_name": r"Equity\Ordinary Share",
                },
                {
                    "symbol": "9999.HK", "name": "HEALTHCARE COMPANY",
                    "cn_name": "健康公司", "local_name": "健康公司",
                    "status": 1, "trading_code": "9999",
                    "rcs_asset_category_name": r"Equity\Ordinary Share",
                },
            ]
        )

    def get_stock_ncycl_estimate(self, **kwargs):
        self.calls.append(("get_stock_ncycl_estimate", kwargs))
        return pd.DataFrame([{
            "symbol": "AAPL", "indicator": "TP", "currency": "USD", "mean": 250.0,
        }])

    def get_stock_recommendation_estimate(self, **kwargs):
        self.calls.append(("get_stock_recommendation_estimate", kwargs))
        return pd.DataFrame([{"symbol": "AAPL", "mean": 1.5, "recommendations_num": 40}])

    def get_us_daily(self, **kwargs):
        self.calls.append(("get_us_daily", kwargs))
        return pd.DataFrame([{"symbol": "AAPL", "date": "20260714", "close": 230.0}])

    def get_us_detail(self, **kwargs):
        self.calls.append(("get_us_detail", kwargs))
        return pd.DataFrame(
            [{"symbol": "AAPL", "name": "APPLE INC.", "local_name": "APPLE INC.",
              "status": 1, "trading_code": "865985",
              "rcs_asset_category_name": r"Equity\Ordinary Share"}]
        )

    def get_last_trade_date(self, **kwargs):
        self.calls.append(("get_last_trade_date", kwargs))
        return pd.DataFrame([{"date": "20260714"}])


class DataPipelineTests(unittest.TestCase):
    def test_consensus_requests_all_documented_trajectory_means_only(self):
        panda = FakePandaData()

        collect_market_data(panda, market="hk", symbols=["0700.HK"])

        requested = {name: kwargs["fields"] for name, kwargs in panda.calls[:2]}
        self.assertEqual(
            data_pipeline.TRAJECTORY_HORIZONS,
            ("week", "1month", "3month", "6month", "12month"),
        )
        for horizon in data_pipeline.TRAJECTORY_HORIZONS:
            self.assertIn(f"mean_{horizon}", requested["get_stock_ncycl_consensus"])
            self.assertIn(
                f"mean_{horizon}",
                requested["get_stock_recommendation_consensus"],
            )
            self.assertNotIn(
                f"std_{horizon}", requested["get_stock_ncycl_consensus"],
            )
            self.assertNotIn(
                f"estimates_num_{horizon}",
                requested["get_stock_ncycl_consensus"],
            )
            self.assertNotIn(
                f"strong_buy_num_{horizon}",
                requested["get_stock_recommendation_consensus"],
            )

    def test_latest_trade_date_parser_accepts_documented_dataframe_shape(self):
        self.assertEqual(
            _parse_latest_trade_date(pd.DataFrame([{"date": "20260714"}])),
            "20260714",
        )
        self.assertEqual(_parse_latest_trade_date({"date": "20260713"}), "20260713")
        self.assertEqual(_parse_latest_trade_date("20260712"), "20260712")
        self.assertIsNone(_parse_latest_trade_date(pd.DataFrame()))
        self.assertIsNone(_parse_latest_trade_date("not-a-date"))
    def test_routes_hk_collection_to_hk_interfaces(self):
        panda = FakePandaData()
        frames = collect_market_data(
            panda,
            market="hk",
            symbols=["0700.HK"],
            start_date="20260701",
            end_date="20260715",
        )
        names = [name for name, _ in panda.calls]
        self.assertEqual(
            names,
            [
                "get_stock_ncycl_consensus",
                "get_stock_recommendation_consensus",
                "get_hk_detail",
                "get_hk_daily",
            ],
        )
        self.assertEqual(frames.market, "hk")

    def test_routes_us_collection_to_us_interfaces(self):
        panda = FakePandaData()
        frames = collect_market_data(
            panda,
            market="us",
            symbols=["AAPL"],
            start_date="20260701",
            end_date="20260715",
        )
        self.assertEqual(
            [name for name, _ in panda.calls],
            [
                "get_stock_ncycl_estimate",
                "get_stock_recommendation_estimate",
                "get_us_detail",
                "get_us_daily",
            ],
        )
        self.assertEqual(frames.market, "us")

    def test_collection_progress_reports_api_phases(self):
        panda = FakePandaData()
        progress = []
        collect_market_data(
            panda,
            market='hk',
            symbols=['0700.HK'],
            start_date='20260701',
            end_date='20260715',
            progress_callback=progress.append,
        )

        message = '\n'.join(progress)
        self.assertIn('HK 正在获取一致预期数据', message)
        self.assertIn('HK 正在获取行情数据', message)
        self.assertIn('HK 正在获取证券名称、状态与类型', message)
        self.assertIn('HK 证券身份数据获取完成', message)

    def test_collection_records_retrieval_time_without_inventing_business_date(self):
        frames = collect_market_data(
            FakePandaData(),
            market="hk",
            symbols=["0700.HK"],
            start_date="20260701",
            end_date="20260715",
            horizon="1month",
        )

        diagnostics = frames.diagnostics
        self.assertRegex(
            diagnostics["consensus_retrieved_at"],
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+0800$",
        )
        self.assertIsNone(diagnostics["consensus_as_of"])
        self.assertEqual(diagnostics["historical_snapshot_label"], "1month")
        self.assertIsNone(diagnostics["historical_snapshot_as_of"])
    def test_normalizes_tp_rows_and_latest_price(self):
        panda = FakePandaData()
        frames = collect_market_data(
            panda,
            market="hk",
            symbols=None,
            start_date="20260701",
            end_date="20260715",
        )
        result = normalize_market_frames(frames)
        row = result.loc[result["symbol"] == "0700.HK"].iloc[0]
        self.assertEqual(len(result), 2)
        self.assertEqual(row["market"], "hk")
        self.assertEqual(row["tp_mean"], 700.0)
        self.assertEqual(row["rec_mean"], 1.4)
        self.assertEqual(row["close"], 620.0)
        self.assertEqual(row["price_date"], "20260714")
        self.assertEqual(row["name"], "腾讯控股")
        self.assertEqual(row["name_source"], "get_hk_detail")
        self.assertEqual(row["source_ncycl"], "get_stock_ncycl_consensus")

    def test_preserves_missing_values_instead_of_zero_filling(self):
        panda = FakePandaData()
        frames = collect_market_data(
            panda,
            market="hk",
            symbols=None,
            start_date="20260701",
            end_date="20260715",
        )
        result = normalize_market_frames(frames)
        row = result.loc[result["symbol"] == "9999.HK"].iloc[0]
        self.assertTrue(pd.isna(row["tp_mean"]))
        self.assertTrue(pd.isna(row["close"]))
        self.assertTrue(pd.isna(row["recommendations_num"]))

    def test_full_market_default_queries_universe_without_empty_symbol_list(self):
        panda = FakePandaData()
        frames = collect_market_data(panda, market="hk", symbols=None)
        names = [name for name, _ in panda.calls]
        self.assertEqual(names.count("get_last_trade_date"), 1)
        self.assertEqual(names.count("get_hk_daily"), 2)
        daily_calls = [kwargs for name, kwargs in panda.calls if name == "get_hk_daily"]
        self.assertEqual(daily_calls[0]["symbol"], ["0700.HK", "9999.HK"])
        self.assertEqual(daily_calls[0]["start_date"], "20260714")
        self.assertEqual(daily_calls[0]["end_date"], "20260714")
        self.assertEqual(daily_calls[1]["symbol"], ["9999.HK"])
        self.assertTrue(frames.diagnostics["price_fallback_used"])
        self.assertEqual(frames.diagnostics["price_initial_rows"], 2)
        self.assertEqual(frames.diagnostics["price_matched_symbols"], 1)

    def test_focused_latest_day_queries_only_requested_symbols(self):
        panda = FakePandaData()

        collect_market_data(panda, market="hk", symbols=["0700.HK"])

        daily_calls = [
            kwargs for name, kwargs in panda.calls if name == "get_hk_daily"
        ]
        self.assertEqual(daily_calls[0]["symbol"], ["0700.HK"])

    def test_detail_name_survives_when_daily_price_is_empty(self):
        class NoPricePanda(FakePandaData):
            def get_hk_daily(self, **kwargs):
                self.calls.append(("get_hk_daily", kwargs))
                return pd.DataFrame()

        panda = NoPricePanda()
        frames = collect_market_data(panda, market="hk", symbols=["0700.HK"])
        row = normalize_market_frames(frames).set_index("symbol").loc["0700.HK"]
        self.assertEqual(row["name"], "腾讯控股")
        self.assertEqual(row["name_source"], "get_hk_detail")
        self.assertTrue(pd.isna(row["close"]))

    def test_empty_latest_day_falls_back_to_recent_window(self):
        class EmptyLatestPanda(FakePandaData):
            def get_hk_daily(self, **kwargs):
                self.calls.append(("get_hk_daily", kwargs))
                if kwargs["start_date"] == kwargs["end_date"]:
                    return pd.DataFrame()
                return pd.DataFrame(
                    [{
                        "symbol": "0700.HK", "date": "20260713", "close": 618.0,
                        "name": "TENCENT HOLDINGS LIMITED",
                    }]
                )

        panda = EmptyLatestPanda()
        frames = collect_market_data(panda, market="hk", symbols=None)
        row = normalize_market_frames(frames).set_index("symbol").loc["0700.HK"]
        self.assertTrue(frames.diagnostics["price_fallback_used"])
        self.assertEqual(frames.diagnostics["price_initial_rows"], 0)
        self.assertEqual(frames.diagnostics["price_matched_symbols"], 1)
        self.assertEqual(row["price_date"], "20260713")


    def test_requests_documented_historical_means_without_undocumented_fields(self):
        panda = FakePandaData()
        collect_market_data(
            panda,
            market="hk",
            symbols=["0700.HK"],
            start_date="20260701",
            end_date="20260715",
            horizon="1month",
        )
        ncycl_kwargs = next(
            kwargs for name, kwargs in panda.calls
            if name == "get_stock_ncycl_consensus"
        )
        recommendation_kwargs = next(
            kwargs for name, kwargs in panda.calls
            if name == "get_stock_recommendation_consensus"
        )
        for horizon in data_pipeline.TRAJECTORY_HORIZONS:
            self.assertIn(f"mean_{horizon}", ncycl_kwargs["fields"])
            self.assertIn(f"mean_{horizon}", recommendation_kwargs["fields"])
            self.assertNotIn(f"std_{horizon}", ncycl_kwargs["fields"])
            self.assertNotIn(f"estimates_num_{horizon}", ncycl_kwargs["fields"])
            self.assertNotIn(
                f"strong_buy_num_{horizon}", recommendation_kwargs["fields"]
            )

    def test_missing_symbol_is_backfilled_even_when_initial_match_rate_exceeds_90_percent(self):
        class HighMatchPanda(FakePandaData):
            symbols = [f"S{index}" for index in range(20)]

            def get_stock_ncycl_estimate(self, **kwargs):
                self.calls.append(("get_stock_ncycl_estimate", kwargs))
                return pd.DataFrame([
                    {"symbol": symbol, "indicator": "TP", "mean": 100.0}
                    for symbol in self.symbols
                ])

            def get_stock_recommendation_estimate(self, **kwargs):
                self.calls.append(("get_stock_recommendation_estimate", kwargs))
                return pd.DataFrame([{"symbol": symbol} for symbol in self.symbols])

            def get_us_detail(self, **kwargs):
                self.calls.append(("get_us_detail", kwargs))
                return pd.DataFrame([
                    {"symbol": symbol, "name": symbol, "status": 1,
                     "rcs_asset_category_name": r"Equity\Ordinary Share"}
                    for symbol in kwargs["symbol"]
                ])

            def get_us_daily(self, **kwargs):
                self.calls.append(("get_us_daily", kwargs))
                if kwargs["start_date"] == kwargs["end_date"]:
                    returned = [s for s in kwargs["symbol"] if s != "S19"]
                    return pd.DataFrame([
                        {"symbol": symbol, "date": "20260714", "close": 10.0}
                        for symbol in returned
                    ])
                return pd.DataFrame([
                    {"symbol": "S19", "date": "20260713", "close": 9.5}
                ])

        panda = HighMatchPanda()
        frames = collect_market_data(panda, market="us")
        daily_calls = [kwargs for name, kwargs in panda.calls if name == "get_us_daily"]

        self.assertEqual(len(daily_calls), 2)
        self.assertEqual(daily_calls[1]["symbol"], ["S19"])
        self.assertTrue(frames.diagnostics["price_fallback_used"])
        row = normalize_market_frames(frames).set_index("symbol").loc["S19"]
        self.assertEqual(row["close"], 9.5)
        self.assertTrue(row["price_is_fallback"])

    def test_security_details_drive_conservative_core_universe_classification(self):
        class MixedDetailsPanda(FakePandaData):
            def get_stock_ncycl_estimate(self, **kwargs):
                self.calls.append(("get_stock_ncycl_estimate", kwargs))
                return pd.DataFrame([
                    {"symbol": symbol, "indicator": "TP", "mean": 100.0}
                    for symbol in ["COMMON", "ETF", "WARRANT", "DELISTED", "UNKNOWN"]
                ])

            def get_stock_recommendation_estimate(self, **kwargs):
                self.calls.append(("get_stock_recommendation_estimate", kwargs))
                return pd.DataFrame()

            def get_us_detail(self, **kwargs):
                self.calls.append(("get_us_detail", kwargs))
                return pd.DataFrame([
                    {"symbol": "COMMON", "name": "Common", "status": 1,
                     "rcs_asset_category_name": r"Equity\Ordinary Share"},
                    {"symbol": "ETF", "name": "Index ETF", "status": 1,
                     "rcs_asset_category_name": r"Fund\Exchange Traded Fund"},
                    {"symbol": "WARRANT", "name": "Call Warrant", "status": 1,
                     "rcs_asset_category_name": r"Derivative\Warrant"},
                    {"symbol": "DELISTED", "name": "Old Co", "status": 0,
                     "rcs_asset_category_name": r"Equity\Ordinary Share"},
                    {"symbol": "UNKNOWN", "name": "Mystery", "status": 1},
                ])

            def get_us_daily(self, **kwargs):
                self.calls.append(("get_us_daily", kwargs))
                return pd.DataFrame([
                    {"symbol": symbol, "date": "20260714", "close": 10.0}
                    for symbol in kwargs["symbol"]
                ])

        panda = MixedDetailsPanda()
        result = normalize_market_frames(collect_market_data(panda, market="us"))
        rows = result.set_index("symbol")

        self.assertTrue(rows.loc["COMMON", "universe_eligible"])
        self.assertEqual(rows.loc["COMMON", "security_type"], "ordinary_share")
        self.assertEqual(rows.loc["ETF", "universe_exclusion_reason"], "non_ordinary_security")
        self.assertEqual(rows.loc["WARRANT", "security_type"], "warrant")
        self.assertEqual(rows.loc["DELISTED", "universe_exclusion_reason"], "inactive_security")
        self.assertEqual(rows.loc["UNKNOWN", "universe_exclusion_reason"], "unknown_security_type")
        detail_call = next(kwargs for name, kwargs in panda.calls if name == "get_us_detail")
        self.assertIn("rcs_asset_category_name", detail_call["fields"])
        self.assertIn("business_sector", detail_call["fields"])

    def test_requested_symbol_without_consensus_is_retained_in_completeness_rows(self):
        class NoConsensusPanda(FakePandaData):
            def get_stock_ncycl_estimate(self, **kwargs):
                self.calls.append(("get_stock_ncycl_estimate", kwargs))
                return pd.DataFrame()

            def get_stock_recommendation_estimate(self, **kwargs):
                self.calls.append(("get_stock_recommendation_estimate", kwargs))
                return pd.DataFrame()

        result = normalize_market_frames(
            collect_market_data(
                NoConsensusPanda(), market="us", symbols=["AAPL"],
                start_date="20260701", end_date="20260715",
            )
        )
        self.assertEqual(list(result["symbol"]), ["AAPL"])
        self.assertTrue(pd.isna(result.iloc[0].get("tp_mean")))
        self.assertEqual(result.iloc[0]["close"], 230.0)

    def test_price_missing_reason_uses_per_symbol_return_evidence(self):
        class MixedPriceEvidencePanda(FakePandaData):
            def get_stock_ncycl_estimate(self, **kwargs):
                self.calls.append(("get_stock_ncycl_estimate", kwargs))
                return pd.DataFrame([
                    {"symbol": "ABSENT", "indicator": "TP", "mean": 10.0},
                    {"symbol": "INVALID", "indicator": "TP", "mean": 10.0},
                ])

            def get_stock_recommendation_estimate(self, **kwargs):
                self.calls.append(("get_stock_recommendation_estimate", kwargs))
                return pd.DataFrame()

            def get_us_detail(self, **kwargs):
                self.calls.append(("get_us_detail", kwargs))
                return pd.DataFrame([
                    {"symbol": symbol, "name": symbol, "status": 1,
                     "rcs_asset_category_name": r"Equity\Ordinary Share"}
                    for symbol in kwargs["symbol"]
                ])

            def get_us_daily(self, **kwargs):
                self.calls.append(("get_us_daily", kwargs))
                if kwargs["start_date"] == kwargs["end_date"]:
                    return pd.DataFrame([
                        {"symbol": "INVALID", "date": "20260714", "close": 0.0}
                    ])
                return pd.DataFrame()

        result = normalize_market_frames(
            collect_market_data(MixedPriceEvidencePanda(), market="us")
        ).set_index("symbol")
        self.assertEqual(result.loc["ABSENT", "price_missing_reason"], "not_returned_by_api")
        self.assertEqual(result.loc["INVALID", "price_missing_reason"], "invalid_or_nonpositive")
if __name__ == "__main__":
    unittest.main()
