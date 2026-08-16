"""1 年 A 股扫描：跑 20250801-20260715 全量事件，落地到 validation/scan_1y.parquet。

用途：Klarman Event Study 回测数据集生成器。
凭证从进程环境变量读取，用完清除，不写入任何文件。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd
from panda_adapter import (
    configure_from_environment,
    clear_process_credentials,
    PandaAuthenticationError,
)
from build import run


def scan(as_of: str, start: str, out_path: Path) -> pd.DataFrame:
    result = run({"as_of_date": as_of, "start_date": start})
    records = result.get("records", [])
    if not records:
        print(f"[warn] no records for {start}~{as_of}")
        return pd.DataFrame()
    rows = []
    for rec in records:
        payload = rec.get("payload", {})
        rows.append({
            "target_id": rec.get("target_id"),
            "result_type": rec.get("result_type"),
            "result_value": rec.get("result_value"),
            "symbol": payload.get("symbol") or payload.get("target_symbol") or "",
            "situation_type": payload.get("situation_type"),
            "signal_date": payload.get("knowledge_cutoff") or payload.get("event_date"),
            "event_date": payload.get("event_date"),
            "event_id": payload.get("event_id"),
            "underwriting_status": payload.get("underwriting_status"),
            "discovery_status": payload.get("discovery_status"),
            "evidence_completeness": (payload.get("evidence_completeness") or {}).get("status"),
            "gates_missing": ",".join((payload.get("klarman_gates") or {}).get("missing_required") or []),
            "payload_json": json.dumps(payload, ensure_ascii=False, default=str),
        })
    df = pd.DataFrame(rows)
    df.to_parquet(out_path, index=False)
    print(f"[ok] {len(df)} rows -> {out_path}")
    print("by result_type × result_value:")
    print(df.groupby(["result_type", "result_value"]).size().to_string())
    return df


def main():
    try:
        configure_from_environment()
    except PandaAuthenticationError as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        out = ROOT / "validation" / "scan_1y.parquet"
        scan(as_of="20260715", start="20250801", out_path=out)
    finally:
        clear_process_credentials()
        for k in list(os.environ):
            if k.startswith("PANDA_"):
                del os.environ[k]


if __name__ == "__main__":
    main()
