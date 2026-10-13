from __future__ import annotations

import unittest

from market_data_sources.eastmoney import parse_limit_up_pool_payload
from market_data_sources.reconcile import compare_quote_records
from market_data_sources.sina import parse_sina_quote_line
from market_data_sources.tencent import parse_tencent_quote_line
from market_data_sources.models import QuoteRecord


class MarketDataSourcesTests(unittest.TestCase):
    def test_parse_eastmoney_limit_up_pool_payload(self) -> None:
        payload = {
            "data": {
                "pool": [
                    {
                        "c": "002343",
                        "n": "慈文传媒",
                        "p": 7.36,
                        "zdp": 10.01,
                        "amount": 1.17,
                        "hs": 3.37,
                        "fbt": "092500",
                        "lbt": "092500",
                        "zbc": 0,
                        "lbc": 3,
                        "hybk": "影视院线",
                        "zttj": "3天3板",
                    }
                ]
            }
        }

        rows = parse_limit_up_pool_payload(
            payload,
            trade_date="2026-10-13",
            fetched_at="2026-10-13 17:00:00",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].code, "002343")
        self.assertEqual(rows[0].first_seal, "09:25:00")
        self.assertEqual(rows[0].limit_days, 3)
        self.assertEqual(rows[0].source, "eastmoney_limit_up_pool")

    def test_quote_reconcile_reports_material_disagreement(self) -> None:
        issues = compare_quote_records(
            [
                QuoteRecord(code="002580", source="sina", fetched_at="t", last=19.00, open=18.53),
                QuoteRecord(code="002580", source="tencent", fetched_at="t", last=19.08, open=18.53),
            ],
            price_abs_tol=0.02,
            price_pct_tol=0.002,
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "002580")
        self.assertEqual(issues[0].field, "last")
        self.assertEqual(issues[0].severity, "block_trading")

    def test_quote_reconcile_ignores_tiny_noise(self) -> None:
        issues = compare_quote_records(
            [
                QuoteRecord(code="002580", source="sina", fetched_at="t", last=19.00),
                QuoteRecord(code="002580", source="tencent", fetched_at="t", last=19.01),
            ],
            price_abs_tol=0.02,
            price_pct_tol=0.002,
        )

        self.assertEqual(issues, [])

    def test_parse_sina_quote_line(self) -> None:
        line = (
            'var hq_str_sz002580="圣阳股份,18.53,18.35,19.00,19.18,18.50,'
            '0,0,0,123456789,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
            '2026-10-13,09:31:00,00";'
        )

        q = parse_sina_quote_line(line, fetched_at="now")

        self.assertIsNotNone(q)
        assert q is not None
        self.assertEqual(q.code, "002580")
        self.assertEqual(q.source, "sina_quote")
        self.assertEqual(q.open, 18.53)
        self.assertEqual(q.last, 19.0)
        self.assertEqual(q.quote_ts, "2026-10-13 09:31:00")

    def test_parse_tencent_quote_line(self) -> None:
        fields = [""] * 40
        fields[1] = "圣阳股份"
        fields[3] = "19.00"
        fields[4] = "18.35"
        fields[5] = "18.53"
        fields[30] = "20261013093100"
        fields[37] = "123456789"
        line = 'v_sz002580="' + "~".join(fields) + '";'

        q = parse_tencent_quote_line(line, fetched_at="now")

        self.assertIsNotNone(q)
        assert q is not None
        self.assertEqual(q.code, "002580")
        self.assertEqual(q.source, "tencent_quote")
        self.assertEqual(q.open, 18.53)
        self.assertEqual(q.last, 19.0)
        self.assertEqual(q.quote_ts, "2026-10-13 09:31:00")


if __name__ == "__main__":
    unittest.main()
