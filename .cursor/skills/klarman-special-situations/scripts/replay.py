"""P3 point-in-time replay ledger for the production snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def build_replay(production_path: str | Path, *, data_version: str, output_path: str | Path) -> dict[str, Any]:
    frame = pd.read_parquet(production_path)
    frame = frame.loc[frame["data_version"].astype(str) == data_version].copy()
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        if row.get("result_type") in {"coverage_gap", "scan_summary"}:
            continue
        payload = json.loads(row["result_json"])
        signal_date = payload.get("knowledge_cutoff") or row.get("actual_source_date")
        eligibility = payload.get("validation_eligibility")
        resolution_date = payload.get("resolution_date")
        rows.append({
            "trade_date": row["trade_date"],
            "event_id": payload.get("event_id") or row["target_id"],
            "symbol": payload.get("symbol"),
            "situation_type": payload.get("situation_type"),
            "signal_date": signal_date,
            "knowledge_cutoff": payload.get("knowledge_cutoff"),
            "underwriting_status": payload.get("underwriting_status") or row["result_value"],
            "validation_eligibility": eligibility,
            "resolution_date": resolution_date,
            "outcome_status": (
                "resolved_pending_price_replay"
                if eligibility == "eligible" and resolution_date
                else "right_censored"
                if eligibility == "eligible"
                else "not_eligible"
            ),
        })
    replay = pd.DataFrame(rows)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    replay.to_parquet(output, index=False)
    return {
        "output_path": str(output.resolve()),
        "event_count": len(replay),
        "eligible_count": int((replay.get("validation_eligibility") == "eligible").sum()) if not replay.empty else 0,
        "right_censored_count": int((replay.get("outcome_status") == "right_censored").sum()) if not replay.empty else 0,
    }
