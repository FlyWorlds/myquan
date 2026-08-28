"""因子14 · 美股隔夜主题联动测试。"""

from __future__ import annotations

import unittest

import pandas as pd

import strategy.factors  # noqa: F401
from strategy.core.factor_registry import get_factor
from strategy.us_a_factor import (
    compute_us_a_linkage,
    factor14_signal,
    linkage_config_from_params,
    panel_us_a_linkage,
    us_a_linkage_rules_text,
)
from strategy.us_a_linkage import fetch_us_theme_returns, UsLinkageConfig


class Factor14Tests(unittest.TestCase):
    def test_registered(self) -> None:
        spec = get_factor("factor14")
        self.assertEqual(spec.id, "factor14")
        self.assertEqual(spec.name, "因子14·美股隔夜主题联动")
        self.assertIn("us_a_theme_linkage", spec.meta.get("kind", ""))

    def test_rules_text(self) -> None:
        text = us_a_linkage_rules_text()
        self.assertIn("因子14", text)
        self.assertIn("IGV", text)

    def test_compute_columns(self) -> None:
        us = fetch_us_theme_returns("2025-01-01", "2025-03-01")
        daily = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-06", periods=10, freq="B"),
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1e6,
            }
        )
        out = compute_us_a_linkage(
            daily,
            symbol="sh600552",
            code="600552",
            themes=("semiconductor", "tech"),
            theme_returns=us,
        )
        self.assertIn("us_link_score", out.columns)
        self.assertIn("us_link_hit", out.columns)
        self.assertIn("us_link_exec", out.columns)
        self.assertEqual(len(out), len(daily))

    def test_panel_rank(self) -> None:
        us = fetch_us_theme_returns("2025-01-01", "2025-02-15")
        d1 = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-06", periods=5, freq="B"),
                "open": 10,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1e6,
            }
        )
        d2 = d1.copy()
        panel = panel_us_a_linkage(
            {"sh600552": d1, "sz001339": d2},
            theme_returns=us,
        )
        self.assertIn("us_link_cs_rank", panel.columns)
        self.assertGreaterEqual(len(panel), 5)

    def test_signal_snapshot(self) -> None:
        sig = factor14_signal()
        self.assertEqual(sig["factor_id"], "factor14")
        self.assertIn("theme_returns_pct", sig)

    def test_linkage_config(self) -> None:
        cfg = linkage_config_from_params({"top_n_themes": 3, "min_theme_ret": 0.01})
        self.assertEqual(cfg.top_n_themes, 3)
        self.assertEqual(cfg.min_theme_ret, 0.01)


if __name__ == "__main__":
    unittest.main()
