import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_workflow.py"
FIXTURES = Path(__file__).parent / "fixtures"
SPEC = importlib.util.spec_from_file_location("audit_workflow", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def workflow(code: str, *, wrapped: bool = False) -> dict:
    code_uuid = "code-node"
    backtest_uuid = "backtest-node"
    payload = {
        "format_version": "V1.0",
        "name": "synthetic review fixture",
        "description": "",
        "litegraph": {"nodes": [], "links": []},
        "nodes": [
            {
                "uuid": code_uuid,
                "name": "CodeControl",
                "type": "CodeControl",
                "title": "Python code",
                "litegraph_id": 1,
                "static_input_data": {"code": code},
                "output_db_id": None,
            },
            {
                "uuid": backtest_uuid,
                "name": "StockBacktestControl",
                "type": "StockBacktestControl",
                "title": "Stock backtest",
                "litegraph_id": 2,
                "static_input_data": {
                    "start_date": "20250101",
                    "end_date": "20250301",
                    "commission_rate": 1,
                    "slippage": 0,
                },
                "output_db_id": None,
            },
        ],
        "links": [
            {
                "uuid": "link-1",
                "litegraph_id": 1,
                "status": 1,
                "previous_node_uuid": code_uuid,
                "next_node_uuid": backtest_uuid,
                "output_field_name": "code",
                "input_field_name": "code",
            }
        ],
    }
    return {"code": 0, "data": payload} if wrapped else payload


class AuditWorkflowTests(unittest.TestCase):
    def run_audit(self, payload: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return MODULE.audit(path)

    def test_accepts_api_data_wrapper(self):
        report = self.run_audit(workflow("def initialize(context):\n    pass\n", wrapped=True))
        self.assertEqual(report["workflow"]["kind"], "strategy")
        self.assertEqual(report["workflow"]["node_count"], 2)

    def test_flags_negative_shift(self):
        report = self.run_audit(
            workflow(
                "def handle_data(context, data):\n"
                "    future = data.close.shift(-1)\n"
                "    return future\n"
            )
        )
        rules = {item["rule_id"] for item in report["findings"]}
        self.assertIn("WF-CODE-NEGATIVE-SHIFT", rules)

    def test_flags_dangling_link(self):
        payload = workflow("def initialize(context):\n    pass\n")
        payload["links"][0]["next_node_uuid"] = "missing"
        report = self.run_audit(payload)
        rules = {item["rule_id"] for item in report["findings"]}
        self.assertIn("WF-STRUCT-DANGLING-LINK", rules)

    def test_static_only_never_claims_not_overfit(self):
        report = self.run_audit(workflow("def initialize(context):\n    pass\n"))
        self.assertEqual(report["assessment"]["verdict"], "insufficient-evidence")
        self.assertEqual(report["assessment"]["overfit_risk"], "unassessable")

    def test_evidence_findings_do_not_saturate_static_risk(self):
        payload = workflow("def initialize(context):\n    pass\n")
        payload["nodes"][1]["static_input_data"].update(
            {"start_date": "20230101", "end_date": "20260101", "slippage": 0.001}
        )
        report = self.run_audit(payload)
        self.assertEqual(report["assessment"]["verdict"], "insufficient-evidence")
        self.assertEqual(report["assessment"]["static_risk"], "low")

    def test_unknown_trials_is_info_context(self):
        report = self.run_audit(workflow("def initialize(context):\n    pass\n"))
        trials = [f for f in report["findings"] if f["rule_id"] == "WF-EVIDENCE-UNKNOWN-TRIALS"]
        self.assertEqual(len(trials), 1)
        self.assertEqual(trials[0]["severity"], "info")

    def test_fixture_stock_hold_flags_universe_and_short_window(self):
        report = MODULE.audit(FIXTURES / "frontend_stock_hold.json")
        rules = {item["rule_id"] for item in report["findings"]}
        self.assertIn("WF-CODE-HARDCODED-UNIVERSE", rules)
        self.assertIn("WF-BACKTEST-SINGLE-WINDOW", rules)
        self.assertIn("WF-EVIDENCE-NO-RUN-OUTPUT", rules)
        self.assertEqual(report["assessment"]["evidence_level"], "static-only")
        self.assertEqual(report["assessment"]["static_risk"], "high")

    def test_fixture_futures_numpy_same_bar_and_universe(self):
        report = MODULE.audit(FIXTURES / "frontend_futures_numpy.json")
        rules = {item["rule_id"] for item in report["findings"]}
        self.assertIn("WF-CODE-SAME-BAR-RISK", rules)
        self.assertIn("WF-CODE-HARDCODED-UNIVERSE", rules)

    def test_fixture_litegraph_only_chinese_code_key(self):
        report = MODULE.audit(FIXTURES / "litegraph_only_chinese_code.json")
        rules = {item["rule_id"] for item in report["findings"]}
        self.assertIn("WF-CODE-NEGATIVE-SHIFT", rules)
        self.assertNotIn("WF-CODE-NOT-AVAILABLE", rules)


if __name__ == "__main__":
    unittest.main()
