"""Runtime integrity checks for paper and strategy16 state."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HS = Path(__file__).resolve().parent
if str(HS) not in sys.path:
    sys.path.insert(0, str(HS))

import runtime_integrity as ri  # noqa: E402


class TestRuntimeIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write_jsonl(self, name: str, rows: list[dict]) -> Path:
        path = self.root / name
        path.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
            encoding="utf-8",
        )
        return path

    def test_live_trade_also_voided_blocks_trading(self) -> None:
        row = {
            "time": "2026-10-13 09:31:00",
            "session": "2026-10-13",
            "side": "buy",
            "code": "001266",
            "price": 36.54,
            "qty": 1500,
        }
        trades = self._write_jsonl("trades.jsonl", [row])
        voided = self._write_jsonl(
            "trades.voided.jsonl",
            [dict(row, voided_reason="REPLACED_BY_USER_BUY_POINT")],
        )
        issues = ri.find_live_void_conflicts(trades_path=trades, voided_path=voided)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, ri.BLOCK_TRADING)
        self.assertEqual(issues[0].kind, "live_trade_also_voided")

    def test_open_position_backed_by_voided_buy_blocks_trading(self) -> None:
        holdings = self.root / "holdings.json"
        holdings.write_text(
            json.dumps(
                {
                    "positions": {
                        "601208": {
                            "qty": 1300,
                            "cost": 44.23,
                            "buy_time": "2026-10-13 09:30:26",
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        voided = self._write_jsonl(
            "trades.voided.jsonl",
            [
                {
                    "time": "2026-10-13 09:30:26",
                    "side": "buy",
                    "code": "601208",
                    "price": 44.23,
                    "qty": 1300,
                    "voided_reason": "REPLACED_BY_USER_BUY_POINT",
                }
            ],
        )
        issues = ri.find_open_position_void_conflicts(
            holdings_path=holdings,
            voided_path=voided,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "open_position_backed_by_voided_buy")

    def test_repair_live_void_conflicts_dry_run_and_apply(self) -> None:
        row = {
            "time": "2026-10-13 09:31:00",
            "session": "2026-10-13",
            "side": "buy",
            "code": "001266",
            "price": 36.54,
            "qty": 1500,
        }
        self._write_jsonl("trades.jsonl", [row, dict(row, code="002580", price=19.0)])
        self._write_jsonl("trades.voided.jsonl", [dict(row, voided_reason="TEST")])
        (self.root / "trade_ledger.json").write_text(
            json.dumps({"entries": [row, dict(row, code="002580", price=19.0)]}),
            encoding="utf-8",
        )

        dry = ri.repair_live_void_conflicts(root=self.root, apply=False)
        self.assertEqual(dry["removed_trades"], 1)
        self.assertEqual(len(ri._load_jsonl(self.root / "trades.jsonl")), 2)

        applied = ri.repair_live_void_conflicts(root=self.root, apply=True)
        self.assertEqual(applied["removed_trades"], 1)
        trades = ri._load_jsonl(self.root / "trades.jsonl")
        self.assertEqual([x["code"] for x in trades], ["002580"])
        ledger = json.loads((self.root / "trade_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual([x["code"] for x in ledger["entries"]], ["002580"])

    def test_strategy16_buy_missing_entry_pct_uses_default_fallback(self) -> None:
        events = self.root / "strategy_signal_events.json"
        events.write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "strategy_id": "strategy16",
                            "symbol": "603042",
                            "side": "BUY",
                            "trigger_time": "2026-10-13 09:31:00",
                            "trigger_price": 14.71,
                        },
                        {
                            "strategy_id": "strategy16",
                            "symbol": "002580",
                            "side": "BUY",
                            "trigger_time": "2026-10-13 09:32:00",
                            "trigger_price": 19.0,
                            "entry_pct": 0.025,
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        issues = ri.find_strategy16_event_threshold_issues(
            events_path=events,
            start_date="2026-10-08",
        )
        self.assertEqual(issues, [])

    def test_strategy16_long_entry_price_must_match_latest_buy_event(self) -> None:
        state = self.root / "strategy_sim_state.json"
        events = self.root / "strategy_signal_events.json"
        state.write_text(
            json.dumps(
                {
                    "books": {
                        "strategy16:603042": {
                            "strategy_id": "strategy16",
                            "symbol": "603042",
                            "state": "LONG",
                            "entry_price": 14.64,
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        events.write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "strategy_id": "strategy16",
                            "symbol": "603042",
                            "side": "BUY",
                            "trigger_price": 14.71,
                            "trigger_time": "2026-10-13 14:40:00",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        issues = ri.find_strategy_state_event_drift(state_path=state, events_path=events)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "long_entry_event_price_mismatch")


if __name__ == "__main__":
    unittest.main()
