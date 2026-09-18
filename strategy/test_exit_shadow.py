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
    get_shadow_errors,
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
        self.assertEqual(rec.get("unified_rule"), "WORKING_STOP")
        self.assertEqual(rec.get("legacy_rule"), "WORKING_STOP")
        self.assertEqual(rec.get("config_version"), shadow.SHADOW_CONFIG_VERSION)
        self.assertTrue(rec.get("context_snapshot"))
        self.assertEqual(rec.get("log_level"), "full")

    def test_consistent_hold_is_sampled_minimal(self) -> None:
        from index import paper_exit_decision

        old = shadow.SHADOW_HOLD_SAMPLE_EVERY
        shadow.SHADOW_HOLD_SAMPLE_EVERY = 2
        try:
            kwargs = dict(
                qty=400,
                sellable=400,
                t1_today=False,
                last=100.5,
                open_px=100.0,
                prev_close=99.5,
                cost=100.0,
                peak_high=101.0,
                working_stop=97.5,
                path_hit=False,
                symbol="600552",
            )
            paper_exit_decision(**kwargs)
            self.assertEqual(len(get_shadow_buffer()), 0)
            paper_exit_decision(**kwargs)
            buf = get_shadow_buffer()
            self.assertEqual(len(buf), 1)
            self.assertTrue(buf[0]["sampled"])
            self.assertEqual(buf[0]["log_level"], "minimal")
            self.assertEqual(buf[0]["decision_trace"], [])
        finally:
            shadow.SHADOW_HOLD_SAMPLE_EVERY = old

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


def _sell_kwargs() -> dict:
    return dict(
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


class TestShadowFailureIsolation(unittest.TestCase):
    def setUp(self) -> None:
        clear_shadow_buffer()
        self._use = shadow.USE_UNIFIED_EXIT_ENGINE
        self._sh = shadow.SHADOW_UNIFIED_EXIT_ENGINE
        shadow.USE_UNIFIED_EXIT_ENGINE = False
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = False

    def tearDown(self) -> None:
        shadow.USE_UNIFIED_EXIT_ENGINE = self._use
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = self._sh
        clear_shadow_buffer()

    def test_shadow_off_matches_legacy(self) -> None:
        from index import _paper_exit_decision_legacy, paper_exit_decision

        kw = _sell_kwargs()
        paper = paper_exit_decision(**kw)
        legacy = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})
        self.assertEqual(paper, legacy)
        self.assertEqual(get_shadow_buffer(), [])
        self.assertEqual(get_shadow_errors(), [])

    def test_shadow_on_still_returns_legacy(self) -> None:
        from index import _paper_exit_decision_legacy, paper_exit_decision

        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True
        kw = _sell_kwargs()
        paper = paper_exit_decision(**kw)
        legacy = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})
        self.assertEqual(paper, legacy)
        self.assertTrue(paper["hit"])
        self.assertEqual(paper["kind"], "last")

    def test_unified_engine_exception_returns_legacy(self) -> None:
        from index import _paper_exit_decision_legacy, paper_exit_decision

        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True
        kw = _sell_kwargs()
        expected = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})

        def boom(_ctx):
            raise RuntimeError("engine down")

        orig = shadow.run_unified_exit
        shadow.run_unified_exit = boom
        try:
            out = paper_exit_decision(**kw)
        finally:
            shadow.run_unified_exit = orig
        self.assertEqual(out, expected)
        self.assertTrue(any(e["where"] == "unified_engine" for e in get_shadow_errors()))

    def test_compare_exception_returns_legacy(self) -> None:
        from index import _paper_exit_decision_legacy, paper_exit_decision

        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True
        kw = _sell_kwargs()
        expected = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})

        def boom(*_a, **_k):
            raise RuntimeError("compare down")

        orig = shadow.compare_paper_vs_exit
        shadow.compare_paper_vs_exit = boom
        try:
            out = paper_exit_decision(**kw)
        finally:
            shadow.compare_paper_vs_exit = orig
        self.assertEqual(out, expected)
        self.assertTrue(any(e["where"] == "compare_or_log" for e in get_shadow_errors()))

    def test_logging_exception_returns_legacy(self) -> None:
        from index import _paper_exit_decision_legacy, paper_exit_decision

        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True
        kw = _sell_kwargs()
        expected = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})

        def boom(_payload):
            raise RuntimeError("log down")

        orig = shadow.emit_shadow_record
        shadow.emit_shadow_record = boom
        try:
            out = paper_exit_decision(**kw)
        finally:
            shadow.emit_shadow_record = orig
        self.assertEqual(out, expected)
        self.assertTrue(any(e["where"] == "compare_or_log" for e in get_shadow_errors()))

    def test_context_built_before_legacy_when_shadow_on(self) -> None:
        from index import paper_exit_decision

        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True
        order: list[str] = []
        orig_legacy = __import__("index")._paper_exit_decision_legacy
        orig_build = shadow.build_exit_context_from_paper_kwargs

        def tracking_legacy(**kw):
            order.append("legacy")
            return orig_legacy(**kw)

        def tracking_build(**kw):
            order.append("context")
            return orig_build(**kw)

        index = __import__("index")
        index._paper_exit_decision_legacy = tracking_legacy
        shadow.build_exit_context_from_paper_kwargs = tracking_build
        try:
            paper_exit_decision(**_sell_kwargs())
        finally:
            index._paper_exit_decision_legacy = orig_legacy
            shadow.build_exit_context_from_paper_kwargs = orig_build
        self.assertEqual(order[:2], ["context", "legacy"])

    def test_context_not_built_when_shadow_off(self) -> None:
        from index import paper_exit_decision

        built = []
        orig_build = shadow.build_exit_context_from_paper_kwargs

        def tracking_build(**kw):
            built.append(True)
            return orig_build(**kw)

        shadow.build_exit_context_from_paper_kwargs = tracking_build
        try:
            paper_exit_decision(**_sell_kwargs())
        finally:
            shadow.build_exit_context_from_paper_kwargs = orig_build
        self.assertEqual(built, [])

    def test_production_flags_remain_false_in_module(self) -> None:
        import importlib

        fresh = importlib.reload(shadow)
        self.assertFalse(fresh.USE_UNIFIED_EXIT_ENGINE)
        self.assertFalse(fresh.SHADOW_UNIFIED_EXIT_ENGINE)
        # restore test isolation defaults after reload
        fresh.USE_UNIFIED_EXIT_ENGINE = False
        fresh.SHADOW_UNIFIED_EXIT_ENGINE = False


if __name__ == "__main__":
    unittest.main()
