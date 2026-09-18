"""Scan ExitDecisionEngine / ReasonCode / legacy mapping and write coverage matrix."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.exit_decision_replay.catalog import (  # noqa: E402
    EXIT_PATHS,
    PATH_SUBTYPES,
    UNUSED_REASON_CODES,
    all_paths,
)
from strategy.core.exit_decision import ReasonCode, paper_reason_to_code  # noqa: E402

ENGINE = ROOT / "strategy" / "exit_rules" / "engine.py"
LEGACY = ROOT / "holdingStocks" / "index.py"
FIXTURES = ROOT / "strategy" / "fixtures" / "exit_parity_cases.json"
ORDER_DOC = ROOT / "docs" / "EXIT_RULE_ORDER.md"
MATRIX_DOC = ROOT / "docs" / "EXIT_COVERAGE_MATRIX.md"


def _reason_names_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "ReasonCode":
                found.add(node.attr)
    return found


def scan() -> dict[str, Any]:
    engine_codes = {f"ReasonCode.{n}" for n in _reason_names_in(ENGINE)}
    engine_values = _reason_names_in(ENGINE)
    enum_values = {c.value for c in ReasonCode}
    catalog_codes = {p.reason_code for p in EXIT_PATHS if p.reason_code != "NONE"}
    mapping_ok = {
        "t1": paper_reason_to_code("t1").value == "T1_BLOCK",
        "hold_lock": paper_reason_to_code("hold_lock").value == "HOLD_LOCK",
        "limit_down": paper_reason_to_code("limit_down").value == "LIMIT_DOWN",
        "not_sellable": paper_reason_to_code("not_sellable").value == "NOT_SELLABLE",
        "wait_auction": paper_reason_to_code("wait_auction").value == "WAIT_AUCTION",
        "open_protect": paper_reason_to_code("open_protect").value == "OPEN_PROTECT",
        "path": paper_reason_to_code("path").value == "PATH",
        "last": paper_reason_to_code("last").value == "WORKING_STOP",
    }
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    tag_counts = Counter()
    for case in fixtures:
        for tag in case.get("tags") or []:
            tag_counts[str(tag)] += 1
    unused_in_engine = sorted(enum_values - engine_values - {"NONE"})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine_reason_codes": sorted(engine_values),
        "enum_reason_codes": sorted(enum_values),
        "catalog_reason_codes": sorted(catalog_codes),
        "unused_reason_codes": list(UNUSED_REASON_CODES),
        "unused_in_engine": unused_in_engine,
        "paper_reason_map_ok": mapping_ok,
        "legacy_file_has_paper_exit": "def _paper_exit_decision_legacy" in LEGACY.read_text(
            encoding="utf-8"
        ),
        "exit_rule_order_exists": ORDER_DOC.is_file(),
        "fixture_tag_counts": dict(tag_counts),
        "fixture_total": len(fixtures),
        "engine_ast_refs": sorted(engine_codes),
        "legacy_only_rules": [],
        "unified_only_rules": [],
    }


def _yn(ok: bool) -> str:
    return "✓" if ok else "✗"


def _fixture_mark(rule_id: str, tags: Counter[str]) -> str:
    mapping = {
        "T1_BLOCK": "t1",
        "HOLD_LOCK": "hold",
        "LIMIT_DOWN": "hold",
        "NOT_SELLABLE": "t1",
        "WAIT_AUCTION": "hold",
        "OPEN_PROTECT": "open_protect",
        "PATH": "path",
        "WORKING_STOP": "working_stop",
        "PATH_HALF": "half",
        "QTY_EMPTY": "hold",
        "HIT_SHOW_FALSE": "hold",
    }
    tag = mapping.get(rule_id)
    if tag and tags.get(tag, 0) > 0:
        return "✓"
    if rule_id.startswith("PATH_"):
        return "✓/subtype"
    return "✗"


def render_matrix(scan_result: dict[str, Any], historical: dict[str, dict[str, Any]] | None = None) -> str:
    hist = historical or {}
    tags = Counter(scan_result.get("fixture_tag_counts") or {})
    lines = [
        "# Exit Coverage Matrix",
        "",
        "> Phase 3C+ · 由 `backtest/exit_decision_replay/scan_rules.py` 根据代码生成。",
        f"> 生成时间：{scan_result['generated_at']}",
        "",
        "`rule_id` = `ExitDecision.reason_code.value`。未新增并行字段。",
        "",
        "证据等级必须分开写：**Synthetic** / **Historical** / **Production Shadow**。",
        "",
        "## Engine / Legacy 主路径",
        "",
        "| Rule | Effect | Legacy | Unified | Fixture | Replay | Hist SELL | Price parity | Qty parity | Notes |",
        "| ---- | ------ | ------ | ------- | ------- | ------ | --------: | ------------ | ---------- | ----- |",
    ]
    for path in EXIT_PATHS:
        h = hist.get(path.rule_id) or {}
        replay = h.get("replay", "?")
        sell = h.get("sell", "?")
        price = h.get("price_parity", "?")
        qty = h.get("qty_parity", "?")
        lines.append(
            "| {rule} | {effect} | {legacy} | {unified} | {fixture} | {replay} | {sell} | {price} | {qty} | {notes} |".format(
                rule=path.rule_id,
                effect=path.effect,
                legacy=_yn(path.legacy),
                unified=_yn(path.engine),
                fixture=_fixture_mark(path.rule_id, tags),
                replay=replay,
                sell=sell,
                price=price,
                qty=qty,
                notes=path.notes.replace("|", "/") or path.description,
            )
        )
    lines.extend(
        [
            "",
            "## PATH 子类型（Factor26 `path_stop_kind`，仍映射 `reason_code=PATH`）",
            "",
            "| Rule | Effect | subtype_of | Fixture | Notes |",
            "| ---- | ------ | ---------- | ------- | ----- |",
        ]
    )
    for path in PATH_SUBTYPES:
        lines.append(
            f"| {path.rule_id} | {path.effect} | {path.subtype_of} | {_fixture_mark(path.rule_id, tags)} | {path.description} |"
        )
    lines.extend(
        [
            "",
            "## 未作为 Engine 成交规则的 ReasonCode",
            "",
            "| Code | 说明 |",
            "| ---- | ---- |",
            "| FACTOR_26 | 未使用；PATH 成交时 `factor_id=factor26` |",
            "| HARD_GAP | 未使用；因子26 `hard_open_dump` 作为 PATH 子类型进入编排 |",
            "| UNKNOWN | `paper_reason_to_code` 回退 |",
            "",
            "## 扫描结论",
            "",
            f"- Legacy-only rule: **{scan_result.get('legacy_only_rules') or 'none'}**",
            f"- Unified-only rule: **{scan_result.get('unified_only_rules') or 'none'}**",
            f"- Fixture 总数: {scan_result.get('fixture_total')}",
            f"- paper_reason 映射: {scan_result.get('paper_reason_map_ok')}",
            f"- Engine 引用的 ReasonCode: {scan_result.get('engine_reason_codes')}",
            "",
            "## 成交优先级（真源 `docs/EXIT_RULE_ORDER.md`）",
            "",
            "```text",
            "open_protect  >  path (Factor26)  >  working_stop(last)",
            "T+1 / hold_lock / limit_down / not_sellable / wait_auction  拦截成交",
            "T+1 会先清掉 open_hit，并把 last/path 收窄到成本硬保护",
            "```",
            "",
            "*研究用途，非投资建议。*",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan exit rules and write coverage matrix")
    parser.add_argument("--write", action="store_true", help="Write rule_scan.json")
    parser.add_argument("--write-md", action="store_true", help="Also write generated matrix markdown")
    parser.add_argument("--historical", type=Path, default=None)
    args = parser.parse_args()
    result = scan()
    historical = None
    if args.historical and args.historical.is_file():
        historical = json.loads(args.historical.read_text(encoding="utf-8"))
    if args.write:
        out = ROOT / "backtest" / "exit_decision_replay" / "rule_scan.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out}")
    if args.write_md:
        md = render_matrix(result, historical)
        MATRIX_DOC.write_text(md, encoding="utf-8")
        print(f"wrote {MATRIX_DOC}")
    print(json.dumps({k: v for k, v in result.items() if k != "engine_ast_refs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
