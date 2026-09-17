"""ExitDecisionEngine 对照 paper_exit_decision 的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.core.exit_decision import ExitAction, ReasonCode
from strategy.core.factor_result import DecisionContext
from strategy.exit_rules.engine import ExitDecisionEngine, exit_decision_to_paper_dict


def _paper(**kw):
    from index import paper_exit_decision

    return paper_exit_decision(**kw)


def _ctx_from_paper_kw(**kw) -> DecisionContext:
    return DecisionContext(
        qty=int(kw.get("qty") or 0),
        sellable=int(kw.get("sellable") or 0),
        t1_today=bool(kw.get("t1_today")),
        hold_locked=bool(kw.get("hold_locked")),
        stop_locked=bool(kw.get("stop_locked")),
        current_price=float(kw.get("last") or 0),
        open_px=float(kw.get("open_px") or 0),
        prev_close=kw.get("prev_close"),
        entry_price=kw.get("cost"),
        peak_high=kw.get("peak_high"),
        working_stop=float(kw.get("working_stop") or 0),
        path_hit=bool(kw.get("path_hit")),
        path_fill_px=float(kw.get("path_fill_px") or 0),
        path_action_kind=str(kw.get("path_action_kind") or ""),
        path_stop_kind=str(kw.get("path_stop_kind") or ""),
        signal_ok=bool(kw.get("signal_ok", True)),
        overnight_high_ok=kw.get("overnight_high_ok"),
        buy_time=kw.get("buy_time"),
        session=str(kw.get("session") or ""),
    )


class TestExitDecisionEngineParity(unittest.TestCase):
    def setUp(self) -> None:
        self.eng = ExitDecisionEngine()

    def _assert_match(self, **kw) -> None:
        paper = _paper(**kw)
        dec = self.eng.evaluate(_ctx_from_paper_kw(**kw))
        adapted = exit_decision_to_paper_dict(dec)
        self.assertEqual(bool(adapted["hit"]), bool(paper["hit"]), msg=f"hit {kw}")
        self.assertEqual(bool(adapted["hit_show"]), bool(paper["hit_show"]), msg=f"show {kw}")
        if paper["hit"]:
            self.assertEqual(adapted["kind"], paper["kind"])
            self.assertAlmostEqual(
                float(adapted["fill_px"]), float(paper["fill_px"]), places=6
            )
            # 半仓
            if paper.get("action_kind") == "half":
                self.assertLess(dec.quantity_ratio, 1.0)
            else:
                self.assertAlmostEqual(dec.quantity_ratio, 1.0, places=6)

    def test_hold_mid(self) -> None:
        self._assert_match(
            qty=400,
            sellable=400,
            t1_today=False,
            last=100.5,
            open_px=100.0,
            cost=100.0,
            peak_high=101.0,
            working_stop=97.5,
            path_hit=False,
            prev_close=99.5,
        )

    def test_open_protect(self) -> None:
        self._assert_match(
            qty=2600,
            sellable=2600,
            t1_today=False,
            last=34.59,
            open_px=33.84,
            prev_close=34.49,
            cost=33.48,
            peak_high=34.78,
            working_stop=34.13,
            path_hit=False,
            overnight_high_ok=True,
        )

    def test_working_stop_last(self) -> None:
        self._assert_match(
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
        )

    def test_path_full(self) -> None:
        self._assert_match(
            qty=400,
            sellable=400,
            t1_today=False,
            last=104.0,
            open_px=105.0,
            cost=100.0,
            peak_high=108.0,
            working_stop=104.0,
            path_hit=True,
            path_fill_px=104.0,
            path_stop_kind="half_gain",
            path_action_kind="full",
            prev_close=104.5,
        )

    def test_path_half_ratio(self) -> None:
        kw = dict(
            qty=400,
            sellable=400,
            t1_today=False,
            last=110.0,
            open_px=110.0,
            cost=100.0,
            peak_high=112.0,
            working_stop=109.0,
            path_hit=True,
            path_fill_px=110.0,
            path_stop_kind="ladder_half_10",
            path_action_kind="half",
            prev_close=109.0,
        )
        self._assert_match(**kw)
        dec = self.eng.evaluate(_ctx_from_paper_kw(**kw))
        self.assertEqual(dec.action, ExitAction.SELL)
        self.assertAlmostEqual(dec.quantity_ratio, 0.5, places=6)
        self.assertEqual(dec.reason_code, ReasonCode.PATH)

    def test_t1_show_only(self) -> None:
        self._assert_match(
            qty=400,
            sellable=0,
            t1_today=True,
            last=97.0,
            open_px=100.0,
            cost=100.0,
            peak_high=100.0,
            working_stop=97.5,
            path_hit=True,
            path_fill_px=97.0,
            prev_close=99.0,
        )

    def test_heimiao_no_open_protect(self) -> None:
        self._assert_match(
            qty=7200,
            sellable=7200,
            t1_today=False,
            last=10.60,
            open_px=10.48,
            prev_close=10.14,
            cost=10.13,
            peak_high=11.15,
            working_stop=9.88,
            path_hit=False,
            overnight_high_ok=True,
            buy_time="2026-09-16 09:31:00",
            session="2026-09-17",
        )


if __name__ == "__main__":
    unittest.main()
