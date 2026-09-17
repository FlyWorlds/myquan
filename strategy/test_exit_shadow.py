"""Shadow Compare：默认不成交；可记录 decision_trace。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import strategy.exit_rules.shadow as shadow
from strategy.exit_rules.shadow import (
    clear_shadow_buffer,
    get_shadow_buffer,
    maybe_shadow_and_select,
)


class TestShadowCompare(unittest.TestCase):
    def setUp(self) -> None:
        clear_shadow_buffer()
        self._use = shadow.USE_UNIFIED_EXIT_ENGINE
        self._sh = shadow.SHADOW_UNIFIED_EXIT_ENGINE
        shadow.USE_UNIFIED_EXIT_ENGINE = False
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True

    def tearDown(self) -> None:
        shadow.USE_UNIFIED_EXIT_ENGINE = self._use
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = self._sh
        clear_shadow_buffer()

    def test_shadow_records_without_switching(self) -> None:
        from index import paper_exit_decision

        out = paper_exit_decision(
            qty=400,
            sellable=400,
            t1_today=False,
            last=96.0,
            open_px=100.0,
            prev_close=99.0,
            cost=100.0,
            peak_high=101.0,
            working_stop=97.5,
            path_hit=False,
            symbol="600552",
        )
        self.assertTrue(out["hit"])
        self.assertEqual(out["kind"], "last")
        buf = get_shadow_buffer()
        self.assertGreaterEqual(len(buf), 1)
        rec = buf[-1]
        self.assertTrue(rec["match_action"])
        self.assertTrue(rec["match_price"])
        self.assertTrue(rec.get("decision_trace"))

    def test_unified_flag_can_select_engine(self) -> None:
        from index import _paper_exit_decision_legacy

        legacy = _paper_exit_decision_legacy(
            qty=400,
            sellable=400,
            t1_today=False,
            last=96.0,
            open_px=100.0,
            cost=100.0,
            peak_high=101.0,
            working_stop=97.5,
            path_hit=False,
            prev_close=99.0,
        )
        selected = maybe_shadow_and_select(
            legacy,
            paper_kwargs={
                "qty": 400,
                "sellable": 400,
                "t1_today": False,
                "last": 96.0,
                "open_px": 100.0,
                "cost": 100.0,
                "peak_high": 101.0,
                "working_stop": 97.5,
                "path_hit": False,
                "prev_close": 99.0,
            },
            use_unified=True,
            shadow=False,
        )
        self.assertTrue(selected["hit"])
        self.assertEqual(selected["kind"], "last")


if __name__ == "__main__":
    unittest.main()
