"""Phase 1D：盯盘 paper_exit_decision vs Factor26Decision 决策对齐 harness。

不修改任何交易规则。输出结构化差异供 DECISION_PARITY_REPORT.md。
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.core.context import Decision, MarketContext  # noqa: E402
from strategy.strategies.strategy16.decision import Strategy16Decision  # noqa: E402
from strategy.strategies.strategy16.bindings import FACTOR_BINDINGS  # noqa: E402


@dataclass
class ParityCase:
    name: str
    # paper inputs
    qty: int
    sellable: int
    t1_today: bool
    last: float
    open_px: float
    cost: float
    peak_high: float
    working_stop: float
    path_hit: bool
    path_fill_px: float = 0.0
    path_action_kind: str = ""
    path_stop_kind: str = ""
    prev_close: float | None = None
    overnight_high_ok: bool | None = True
    buy_time: str | None = None
    session: str = "2026-09-17"
    # engine extras
    high: float | None = None
    low: float | None = None
    expect_structural_gap: str = ""


def _paper_action(dec: dict[str, Any]) -> str:
    if dec.get("hit"):
        return "SELL"
    if dec.get("hit_show") and not dec.get("hit"):
        return "HOLD_SHOW"  # T+1 等只展示
    return "HOLD"


def _engine_action(d: Decision) -> str:
    a = str(d.action).lower()
    if a == "sell":
        return "SELL"
    if a == "buy":
        return "BUY"
    return "HOLD"


def _run_paper(case: ParityCase) -> dict[str, Any]:
    from index import paper_exit_decision

    return paper_exit_decision(
        qty=case.qty,
        sellable=case.sellable,
        t1_today=case.t1_today,
        last=case.last,
        open_px=case.open_px,
        prev_close=case.prev_close,
        cost=case.cost,
        peak_high=case.peak_high,
        working_stop=case.working_stop,
        path_hit=case.path_hit,
        path_fill_px=case.path_fill_px,
        path_action_kind=case.path_action_kind,
        path_stop_kind=case.path_stop_kind,
        signal_ok=True,
        overnight_high_ok=case.overnight_high_ok,
        buy_time=case.buy_time,
        session=case.session,
    )


def _run_engine(case: ParityCase) -> Decision:
    eng = Strategy16Decision(FACTOR_BINDINGS)
    high = float(case.high if case.high is not None else max(case.last, case.open_px, case.peak_high))
    low = float(case.low if case.low is not None else min(case.last, case.open_px))
    ctx = MarketContext(
        open=float(case.open_px),
        high=high,
        low=low,
        close=float(case.last),
        last=float(case.last),
        session=case.session,
        prev_close=case.prev_close,
        position_qty=float(case.qty),
        available_qty=float(case.sellable),
        buy_time=case.buy_time,
        entry_price=float(case.cost),
        meta={
            "t_plus_one": bool(case.t1_today),
            "path_hit_stop": bool(case.path_hit),
            "path_fill_px": float(case.path_fill_px or 0),
            "peak_high": float(case.peak_high),
            "parity_case": case.name,
        },
    )
    return eng.decide(ctx)


CASES: list[ParityCase] = [
    ParityCase(
        name="hold_mid_range",
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
    ),
    ParityCase(
        name="path_hit_sell",
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
        high=108.0,
        low=103.5,
    ),
    ParityCase(
        name="t1_path_show_only",
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
        expect_structural_gap="paper may HOLD_SHOW; engine HOLD(t1)",
    ),
    ParityCase(
        name="open_protect_gap_down",
        qty=2600,
        sellable=2600,
        t1_today=False,
        last=34.59,
        open_px=33.84,
        cost=33.48,
        peak_high=34.78,
        working_stop=34.13,
        path_hit=False,
        prev_close=34.49,
        overnight_high_ok=True,
        expect_structural_gap="paper open_protect SELL; engine HOLD without path_hit_stop",
    ),
    ParityCase(
        name="heimiao_gap_up_no_open_protect",
        qty=7200,
        sellable=7200,
        t1_today=False,
        last=10.60,
        open_px=10.48,
        cost=10.13,
        peak_high=11.15,
        working_stop=9.88,
        path_hit=False,
        prev_close=10.14,
        buy_time="2026-09-16 09:31:00",
        session="2026-09-17",
        overnight_high_ok=True,
    ),
    ParityCase(
        name="last_vs_working_stop_no_path",
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
        expect_structural_gap="paper may SELL on last<=working_stop; engine HOLD without path",
    ),
]


def run_parity() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    tallies = {
        "total": 0,
        "action_match": 0,
        "action_mismatch": 0,
        "sell_match": 0,
        "sell_mismatch": 0,
        "hold_match": 0,
        "hold_mismatch": 0,
        "structural_expected": 0,
        "price_compared": 0,
        "price_match": 0,
        "price_mismatch": 0,
        "factor_id_engine_sell": 0,
    }
    for case in CASES:
        paper = _run_paper(case)
        eng = _run_engine(case)
        pa = _paper_action(paper)
        ea = _engine_action(eng)
        # 对齐粒度：HOLD_SHOW 与 HOLD 都算「不成交」侧
        pa_norm = "HOLD" if pa in ("HOLD", "HOLD_SHOW") else pa
        ea_norm = "HOLD" if ea == "HOLD" else ea
        match = pa_norm == ea_norm
        structural = bool(case.expect_structural_gap) and not match

        price_info: dict[str, Any] = {}
        if pa_norm == "SELL" and ea_norm == "SELL":
            tallies["price_compared"] += 1
            pp = float(paper.get("fill_px") or 0)
            ep = float(eng.price or 0)
            price_ok = abs(pp - ep) <= 1e-6 or abs(pp - ep) / max(pp, ep, 1e-9) < 1e-4
            if price_ok:
                tallies["price_match"] += 1
            else:
                tallies["price_mismatch"] += 1
            price_info = {"paper_fill": pp, "engine_price": ep, "price_match": price_ok}

        tallies["total"] += 1
        if match:
            tallies["action_match"] += 1
            if pa_norm == "SELL":
                tallies["sell_match"] += 1
            else:
                tallies["hold_match"] += 1
        else:
            tallies["action_mismatch"] += 1
            if structural:
                tallies["structural_expected"] += 1
            if pa_norm == "SELL" or ea_norm == "SELL":
                tallies["sell_mismatch"] += 1
            else:
                tallies["hold_mismatch"] += 1
        if ea_norm == "SELL" and eng.factor_id:
            tallies["factor_id_engine_sell"] += 1

        rows.append(
            {
                "case": case.name,
                "paper_action": pa,
                "engine_action": ea,
                "action_match": match,
                "structural_expected": structural,
                "expect_note": case.expect_structural_gap,
                "paper_kind": paper.get("kind"),
                "paper_reason": paper.get("reason"),
                "engine_reason": eng.reason,
                "engine_factor_id": eng.factor_id,
                **price_info,
            }
        )

    return {"tallies": tallies, "rows": rows}


class TestDecisionParityHarness(unittest.TestCase):
    def test_harness_runs_and_records_gaps(self) -> None:
        report = run_parity()
        self.assertEqual(report["tallies"]["total"], len(CASES))
        # 已知：开盘保护 / 无 path 现价破卖 与引擎分叉
        mismatches = [r for r in report["rows"] if not r["action_match"]]
        self.assertGreaterEqual(len(mismatches), 1)
        # harness 本身不应崩溃；差异写入报告而非强行 assert 全一致
        out = _ROOT / "docs" / "_parity_raw.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    report = run_parity()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    unittest.main(verbosity=2)
