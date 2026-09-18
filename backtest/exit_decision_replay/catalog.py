"""Exit path catalog for coverage scanning (Phase 3C+).

rule_id == ReasonCode.value. PATH subtypes are Factor26 stop_kind consumed by
the PATH branch; they are not separate ExitDecisionEngine rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strategy.core.exit_decision import ReasonCode


@dataclass(frozen=True)
class ExitPath:
    rule_id: str
    effect: str  # SELL | PARTIAL_SELL | BLOCK_SELL | HOLD | SIGNAL
    description: str
    engine: bool
    legacy: bool
    reason_code: str
    paper_reason: str
    paper_kind: str
    position_changing: bool
    notes: str = ""
    subtype_of: str | None = None


# Engine-level paths that can change position or block a fill.
EXIT_PATHS: tuple[ExitPath, ...] = (
    ExitPath(
        rule_id="QTY_EMPTY",
        effect="HOLD",
        description="qty<=0 → empty, no show, no fill",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.NONE.value,
        paper_reason="",
        paper_kind="",
        position_changing=False,
        notes="Engine step 00",
    ),
    ExitPath(
        rule_id="HIT_SHOW_FALSE",
        effect="HOLD",
        description="no open/last/path hit after T+1 narrowing → empty",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.NONE.value,
        paper_reason="",
        paper_kind="",
        position_changing=False,
        notes="Most T+1 evaluations land here, not T1_BLOCK",
    ),
    ExitPath(
        rule_id="T1_BLOCK",
        effect="BLOCK_SELL",
        description="hit_show after T+1 narrowing, fill blocked",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.T1_BLOCK.value,
        paper_reason="t1",
        paper_kind="",
        position_changing=False,
    ),
    ExitPath(
        rule_id="HOLD_LOCK",
        effect="BLOCK_SELL",
        description="hold_locked → show only",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.HOLD_LOCK.value,
        paper_reason="hold_lock",
        paper_kind="",
        position_changing=False,
        notes="Replay-generated holdings do not set hold_locked",
    ),
    ExitPath(
        rule_id="LIMIT_DOWN",
        effect="BLOCK_SELL",
        description="stop_locked → show only (paper reason=limit_down)",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.LIMIT_DOWN.value,
        paper_reason="limit_down",
        paper_kind="",
        position_changing=False,
        notes="Replay-generated holdings do not set stop_locked",
    ),
    ExitPath(
        rule_id="NOT_SELLABLE",
        effect="BLOCK_SELL",
        description="sellable<=0 → show only",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.NOT_SELLABLE.value,
        paper_reason="not_sellable",
        paper_kind="",
        position_changing=False,
    ),
    ExitPath(
        rule_id="WAIT_AUCTION",
        effect="BLOCK_SELL",
        description="not signal_ok → show only",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.WAIT_AUCTION.value,
        paper_reason="wait_auction",
        paper_kind="",
        position_changing=False,
        notes="Replay defaults signal_ok=True",
    ),
    ExitPath(
        rule_id="OPEN_PROTECT",
        effect="SELL",
        description="open_hit → full sell at day open",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.OPEN_PROTECT.value,
        paper_reason="open_protect",
        paper_kind="open_protect",
        position_changing=True,
    ),
    ExitPath(
        rule_id="PATH",
        effect="SELL",
        description="Factor26 1m path_ok → sell at path_fill (full unless half kind)",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        notes="factor_id=factor26; quantity_ratio 1.0 or 0.5",
    ),
    ExitPath(
        rule_id="WORKING_STOP",
        effect="SELL",
        description="last<=working_stop fallback → full sell at working_stop",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.WORKING_STOP.value,
        paper_reason="last",
        paper_kind="last",
        position_changing=True,
        notes="Only wins when open_protect and path are idle",
    ),
)

PATH_SUBTYPES: tuple[ExitPath, ...] = (
    ExitPath(
        rule_id="PATH_HALF",
        effect="PARTIAL_SELL",
        description="path action_kind=half / stop_kind=ladder_half_10 → quantity_ratio=0.5",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
        notes="is_half_stop_kind; not a separate ReasonCode",
    ),
    ExitPath(
        rule_id="PATH_HALF_GAIN",
        effect="SELL",
        description="Factor26 mid-gain half_gain stop_kind, full exit",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
    ),
    ExitPath(
        rule_id="PATH_VOL_GIVEBACK",
        effect="SELL",
        description="Factor26 vol_giveback stop_kind, full exit",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
    ),
    ExitPath(
        rule_id="PATH_HARD_FROM_COST",
        effect="SELL",
        description="Factor26 hard_from_cost stop_kind, full exit",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
    ),
    ExitPath(
        rule_id="PATH_HARD_GAP",
        effect="SELL",
        description="Factor26 hard_open_dump / hard gap at open, consumed as PATH",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
        notes="ReasonCode.HARD_GAP is unused by ExitDecisionEngine",
    ),
    ExitPath(
        rule_id="PATH_LADDER_FULL_15",
        effect="SELL",
        description="Factor26 ladder_full_15 stop_kind, full exit",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
    ),
    ExitPath(
        rule_id="PATH_PEAK_PULLBACK",
        effect="SELL",
        description="Factor26 peak_pullback / peak_pullback_clear, full exit",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
    ),
    ExitPath(
        rule_id="PATH_T1_PEAK_TRAIL",
        effect="SELL",
        description="Factor26 t1_peak_trail stop_kind (fill still blocked if t1_today)",
        engine=True,
        legacy=True,
        reason_code=ReasonCode.PATH.value,
        paper_reason="path",
        paper_kind="path",
        position_changing=True,
        subtype_of="PATH",
    ),
)

UNUSED_REASON_CODES: tuple[str, ...] = (
    ReasonCode.FACTOR_26.value,  # PATH + factor_id=factor26
    ReasonCode.HARD_GAP.value,  # Factor26 path_stop_kind, not engine rule
    ReasonCode.UNKNOWN.value,  # mapping fallback only
)

RULE_ALIASES: dict[str, str] = {
    "LAST": "WORKING_STOP",
    "WORKING_STOP": "WORKING_STOP",
    "OPEN_PROTECT": "OPEN_PROTECT",
    "PATH": "PATH",
    "FACTOR_26_PATH": "PATH",
    "FACTOR26": "PATH",
    "FACTOR_26": "PATH",
    "T1": "T1_BLOCK",
    "T+1": "T1_BLOCK",
    "T1_BLOCK": "T1_BLOCK",
    "HALF_POSITION": "PATH_HALF",
    "HALF": "PATH_HALF",
    "HALF_GAIN": "PATH_HALF_GAIN",
    "HARD_GAP": "PATH_HARD_GAP",
    "HOLD_LOCK": "HOLD_LOCK",
    "LIMIT_DOWN": "LIMIT_DOWN",
    "NOT_SELLABLE": "NOT_SELLABLE",
    "WAIT_AUCTION": "WAIT_AUCTION",
}


def normalize_rule_id(rule: str | None) -> str:
    raw = str(rule or "").strip().upper().replace("-", "_").replace(" ", "_")
    return RULE_ALIASES.get(raw, raw)


def all_paths() -> tuple[ExitPath, ...]:
    return EXIT_PATHS + PATH_SUBTYPES


def path_by_id(rule_id: str) -> ExitPath | None:
    rid = normalize_rule_id(rule_id)
    for row in all_paths():
        if row.rule_id == rid:
            return row
    return None


def catalog_as_dicts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in all_paths():
        rows.append(
            {
                "rule_id": item.rule_id,
                "effect": item.effect,
                "description": item.description,
                "engine": item.engine,
                "legacy": item.legacy,
                "reason_code": item.reason_code,
                "paper_reason": item.paper_reason,
                "paper_kind": item.paper_kind,
                "position_changing": item.position_changing,
                "subtype_of": item.subtype_of,
                "notes": item.notes,
            }
        )
    return rows
