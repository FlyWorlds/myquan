"""策略二冻结的信号层因子组合。由挖掘流程写入，回测与面板构建读取。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from strategy.chan.mining import cs_winsorize_zscore


FROZEN_PATH = Path(__file__).with_name("frozen_combo.json")
TARGET_SHARPE = 0.8


def load_frozen_combo() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        return {
            "members": [],
            "scheme": "equal",
            "weights": {},
            "meets_target": False,
            "target_sharpe": TARGET_SHARPE,
            "validation_sharpe": None,
        }
    return json.loads(FROZEN_PATH.read_text(encoding="utf-8"))


def save_frozen_combo(payload: dict[str, Any]) -> Path:
    sharpe = payload.get("validation_sharpe")
    try:
        sharpe_f = float(sharpe) if sharpe is not None else None
        if sharpe_f is not None and sharpe_f != sharpe_f:
            sharpe_f = None
    except (TypeError, ValueError):
        sharpe_f = None
    body = {
        "members": list(payload.get("members") or []),
        "scheme": payload.get("scheme") or "equal",
        "weights": dict(payload.get("weights") or {}),
        "meets_target": bool(payload.get("meets_target")),
        "target_sharpe": TARGET_SHARPE,
        "validation_sharpe": sharpe_f,
        "research_only": True,
    }
    FROZEN_PATH.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return FROZEN_PATH


def apply_frozen_combo(panel: pd.DataFrame, *, min_cross_section: int = 10) -> pd.DataFrame:
    spec = load_frozen_combo()
    members = list(spec.get("members") or [])
    weights = dict(spec.get("weights") or {})
    if not members:
        return panel
    out = panel.copy()
    if "eligible_long" not in out.columns:
        return out
    acc = 0.0
    used = 0.0
    for name in members:
        if name not in out:
            continue
        z = cs_winsorize_zscore(
            out,
            name,
            min_cross_section=min_cross_section,
            eligible_col="eligible_long",
        )
        out[f"z_{name}"] = z
        weight = float(weights.get(name, 1.0))
        acc = acc + weight * pd.to_numeric(z, errors="coerce")
        used += abs(weight)
    if used <= 0:
        return out
    out["factor_score"] = acc
    out["factor_score"] = cs_winsorize_zscore(
        out,
        "factor_score",
        min_cross_section=min_cross_section,
        eligible_col="eligible_long",
    )
    return out


__all__ = [
    "FROZEN_PATH",
    "TARGET_SHARPE",
    "apply_frozen_combo",
    "load_frozen_combo",
    "save_frozen_combo",
]
