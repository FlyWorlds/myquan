"""信号层因子组合：去冗余后比较 equal / icir / score，权重只来自发现集。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from strategy.chan.config import DEFAULT_CONFIG, ChanStrategyConfig
from strategy.chan.mining import cs_winsorize_zscore, evaluate_factor


TARGET_SHARPE = 0.8
SCHEMES = ("equal", "icir", "score")


@dataclass
class BlendResult:
    members: list[str]
    scheme: str
    weights: dict[str, float]
    combined_column: str | None
    validation_sharpe: float
    validation_score: float
    meets_target: bool
    dropped: list[str]
    scheme_rows: list[dict[str, Any]]


def _member_metrics(journal: pd.DataFrame) -> pd.DataFrame:
    rows = journal[journal["status"] == "ACCEPTED"].copy()
    return rows


def _dedupe_members(
    journal: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    config: ChanStrategyConfig,
) -> tuple[list[str], list[str]]:
    accepted = _member_metrics(journal)
    if accepted.empty:
        return [], []
    ordered = accepted.sort_values("discovery_score", ascending=False)
    kept: list[str] = []
    dropped: list[str] = []
    zcols: list[str] = []
    for _, row in ordered.iterrows():
        name = str(row["factor"])
        zname = f"z_{name}"
        if zname not in panel:
            dropped.append(name)
            continue
        too_close = False
        for prev in zcols:
            pair = panel[[zname, prev]].dropna()
            corr = 0.0
            if (
                len(pair) > 10
                and float(pair.iloc[:, 0].std()) > 0
                and float(pair.iloc[:, 1].std()) > 0
            ):
                corr = abs(float(pair.corr().iloc[0, 1]))
            if corr >= config.correlation_prefer:
                too_close = True
                break
        if too_close:
            dropped.append(name)
            continue
        kept.append(name)
        zcols.append(zname)
    return kept, dropped


def _scheme_weights(
    members: list[str],
    journal: pd.DataFrame,
    scheme: str,
) -> dict[str, float]:
    accepted = _member_metrics(journal).set_index("factor")
    if scheme == "equal" or not members:
        w = 1.0 / max(len(members), 1)
        return {name: w for name in members}
    if scheme == "icir":
        raw = np.array(
            [max(0.01, float(accepted.loc[name, "discovery_rank_ic_ir"])) for name in members]
        )
    else:
        raw = np.array(
            [max(0.0, float(accepted.loc[name, "discovery_score"])) for name in members]
        )
        if float(raw.sum()) <= 0:
            raw = np.ones(len(members))
    raw = raw / raw.sum()
    return {name: float(raw[i]) for i, name in enumerate(members)}


def blend_accepted_factors(
    panel: pd.DataFrame,
    journal: pd.DataFrame,
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
) -> BlendResult:
    """在验证集上比较三种加权，权重只用发现集 ICIR/主分。不碰最终测试集。"""
    members, dropped = _dedupe_members(journal, panel, config=config)
    empty = BlendResult(
        members=[],
        scheme="equal",
        weights={},
        combined_column=None,
        validation_sharpe=float("nan"),
        validation_score=float("nan"),
        meets_target=False,
        dropped=dropped,
        scheme_rows=[],
    )
    if not members:
        return empty
    data = panel.copy()
    best: dict[str, Any] | None = None
    scheme_rows: list[dict[str, Any]] = []
    for scheme in SCHEMES:
        weights = _scheme_weights(members, journal, scheme)
        col = f"combo_{scheme}"
        acc = 0.0
        for name, weight in weights.items():
            acc = acc + weight * pd.to_numeric(data[f"z_{name}"], errors="coerce")
        data[col] = acc
        data[col] = cs_winsorize_zscore(
            data,
            col,
            min_cross_section=min(config.min_cross_section, config.min_eligible),
            eligible_col="eligible_long",
        )
        validation, _ = evaluate_factor(
            data,
            col,
            config=config,
            start=config.validation_start,
            end=config.validation_end,
            split_role="validation",
        )
        row = {
            "op_type": "blend",
            "hypothesis": f"{scheme} 加权合成可买集合内的低相关因子",
            "change": f"members={members} scheme={scheme}",
            "expected": f"验证集成本后 Sharpe>={TARGET_SHARPE}",
            "factor": col,
            "status": "COMBO",
            "reason": scheme,
            "validation_sharpe": validation["sharpe"],
            "validation_score": validation["score"],
            "validation_annual_return": validation["annual_return"],
            "validation_max_drawdown": validation["max_drawdown"],
            "weights": weights,
        }
        scheme_rows.append(row)
        if best is None or float(validation["sharpe"]) > float(best["validation_sharpe"]):
            best = row | {"scheme": scheme, "combined_column": col}
    assert best is not None
    data["factor_score"] = data[str(best["combined_column"])]
    panel["factor_score"] = data["factor_score"]
    for scheme in SCHEMES:
        col = f"combo_{scheme}"
        if col in data:
            panel[col] = data[col]
    return BlendResult(
        members=members,
        scheme=str(best["scheme"]),
        weights=dict(best["weights"]),
        combined_column="factor_score",
        validation_sharpe=float(best["validation_sharpe"]),
        validation_score=float(best["validation_score"]),
        meets_target=float(best["validation_sharpe"]) >= TARGET_SHARPE,
        dropped=dropped,
        scheme_rows=scheme_rows,
    )


__all__ = ["BlendResult", "TARGET_SHARPE", "blend_accepted_factors"]
