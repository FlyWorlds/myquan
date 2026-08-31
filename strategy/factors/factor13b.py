"""因子13B · 熊市盾牌（WF + 个股 thr* Top3，🔒锁定）。

真源：``strategy/factor13_bear_shield.py``。见 ``docs/FACTOR13.md`` 与 ``LOCKED.json``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor13_bear_shield import (
    DEFAULT_PARAMS,
    is_locked,
    rules_text,
    select_top,
)

_MYQUAN = Path(__file__).resolve().parents[2]
_LOCKED = _MYQUAN / "backtest" / "factor13_bear_shield" / "LOCKED.json"

FACTOR_ID = "factor13b"
FACTOR_NAME = "因子13B-熊市盾牌 thr* Top3"


def _load_locked_params() -> dict[str, Any]:
    if _LOCKED.exists():
        try:
            data = json.loads(_LOCKED.read_text(encoding="utf-8"))
            return {**DEFAULT_PARAMS, **data.get("params", {})}
        except Exception:
            pass
    return dict(DEFAULT_PARAMS)


def factor13b_signal(
    *,
    year_panel: pd.DataFrame | None = None,
    fit_end_year: int = 2025,
    params: dict[str, Any] | None = None,
    top_k: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    p = {**_load_locked_params(), **(params or {})}
    if year_panel is None:
        cache = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
        if not cache.exists():
            raise ValueError("factor13b 需要 year_panel 或先构建 year_thr_panel.parquet")
        year_panel = pd.read_parquet(cache)
    k = int(top_k if top_k is not None else p.get("top_k", 3))
    picks = select_top(year_panel, fit_end_year=int(fit_end_year), params=p, k=k)
    return {
        "factor_id": FACTOR_ID,
        "params": p,
        "fit_end_year": int(fit_end_year),
        "hold_year": int(fit_end_year) + 1,
        "picks": picks,
        "universe": picks["symbol"].tolist() if len(picks) else [],
        "rules_text": rules_text(p),
        "locked": is_locked(),
        "locked_path": str(_LOCKED),
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "熊/季熊超额 + 软牛 + 稳定性过滤；个股 thr* 在 {2%,2.5%,3%} 择优。"
        "生产研究默认锁定配置见 LOCKED.json"
    ),
    rules_text=rules_text(_load_locked_params()),
    implemented=True,
    signal=factor13b_signal,
    meta={
        "kind": "bear_shield_wf_thr",
        "standalone": True,
        "default_params": _load_locked_params(),
        "timing": "year_t_bear_shield_hold_year_t_plus_1",
        "research_only": True,
        "locked": is_locked(),
        "locked_path": "backtest/factor13_bear_shield/LOCKED.json",
        "docs": "docs/FACTOR13.md#2-熊市盾牌锁定版",
        "legacy_id": "factor13",
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor13b_signal(**kwargs)
