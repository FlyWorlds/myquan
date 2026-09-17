"""Phase 2E：fixture 驱动的 ExitDecisionEngine ↔ paper_exit_decision parity。"""

from __future__ import annotations

import json
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
_FIX = Path(__file__).resolve().parent / "fixtures" / "exit_parity_cases.json"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.core.exit_decision import ExitAction
from strategy.exit_rules.engine import ExitDecisionEngine, exit_decision_to_paper_dict
from strategy.exit_rules.shadow import build_exit_context_from_paper_kwargs


def _load_cases() -> list[dict[str, Any]]:
    return json.loads(_FIX.read_text(encoding="utf-8"))


def _paper_kw(case: dict[str, Any]) -> dict[str, Any]:
    skip = {"name", "tags"}
    return {k: v for k, v in case.items() if k not in skip}


def run_fixture_parity() -> dict[str, Any]:
    from index import paper_exit_decision

    eng = ExitDecisionEngine()
    rows: list[dict[str, Any]] = []
    tallies: Counter[str] = Counter()
    tag_miss: Counter[str] = Counter()

    for case in _load_cases():
        kw = _paper_kw(case)
        paper = paper_exit_decision(**kw)
        ctx = build_exit_context_from_paper_kwargs(**kw)
        dec = eng.evaluate(ctx)
        adapted = exit_decision_to_paper_dict(dec)

        hit_m = bool(adapted["hit"]) == bool(paper["hit"])
        show_m = bool(adapted["hit_show"]) == bool(paper["hit_show"])
        kind_m = (not paper["hit"]) or adapted["kind"] == paper["kind"]
        price_m = True
        if paper["hit"]:
            price_m = abs(float(adapted["fill_px"]) - float(paper["fill_px"])) <= 1e-6
        qty_m = True
        if paper["hit"]:
            expect_half = str(paper.get("action_kind") or "") == "half"
            got_half = dec.quantity_ratio < 1.0 - 1e-12
            qty_m = expect_half == got_half

        exact = hit_m and show_m and kind_m and price_m and qty_m
        tallies["total"] += 1
        if exact:
            tallies["exact_match"] += 1
        else:
            tallies["mismatch"] += 1
            for t in case.get("tags") or []:
                tag_miss[str(t)] += 1

        # 分类（本批期望 0 mismatch；若有则标 G）
        klass = ""
        if not exact:
            klass = "G"
            if not hit_m:
                klass = "D" if (paper.get("kind") or adapted.get("kind")) else "G"
            elif not price_m:
                klass = "E"
            elif not qty_m:
                klass = "A"

        if paper["hit"] and paper.get("kind") == "open_protect":
            tallies["open_protect_cases"] += 1
            if exact:
                tallies["open_protect_match"] += 1
        if paper["hit"] and paper.get("kind") == "last":
            tallies["working_stop_cases"] += 1
            if exact:
                tallies["working_stop_match"] += 1
        if paper["hit"] and paper.get("kind") == "path":
            tallies["factor26_path_cases"] += 1
            if exact:
                tallies["factor26_path_match"] += 1
        if paper.get("reason") == "t1" or kw.get("t1_today"):
            tallies["t1_cases"] += 1
            if exact:
                tallies["t1_match"] += 1
        if paper.get("action_kind") == "half" or (
            dec.action == ExitAction.SELL and dec.quantity_ratio < 1.0
        ):
            tallies["half_cases"] += 1
            if exact:
                tallies["half_match"] += 1

        rows.append(
            {
                "case": case["name"],
                "tags": case.get("tags"),
                "exact": exact,
                "class": klass,
                "paper_hit": paper.get("hit"),
                "paper_kind": paper.get("kind"),
                "paper_reason": paper.get("reason"),
                "paper_fill": paper.get("fill_px"),
                "paper_action_kind": paper.get("action_kind"),
                "new_hit": adapted.get("hit"),
                "new_kind": adapted.get("kind"),
                "new_fill": adapted.get("fill_px"),
                "new_qty_ratio": dec.quantity_ratio if dec.action == ExitAction.SELL else None,
                "reason_code": dec.reason_code.value,
                "trace": list(dec.trace),
            }
        )

    return {
        "tallies": dict(tallies),
        "tag_mismatch": dict(tag_miss),
        "rows": rows,
    }


class TestExitFixtureParity(unittest.TestCase):
    def test_all_fixtures_exact_match(self) -> None:
        report = run_fixture_parity()
        bad = [r for r in report["rows"] if not r["exact"]]
        self.assertEqual(
            report["tallies"].get("mismatch", 0),
            0,
            msg=json.dumps(bad, ensure_ascii=False, indent=2),
        )
        self.assertGreaterEqual(report["tallies"]["total"], 20)


if __name__ == "__main__":
    print(json.dumps(run_fixture_parity(), ensure_ascii=False, indent=2))
    unittest.main(verbosity=2)
