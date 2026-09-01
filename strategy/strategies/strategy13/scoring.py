"""策略十三 OOS 综合打分（研究用，非注册因子）。

权重：夏普 30% + 超额 30% + 收益 20% + 胜率 20%（截面分位）。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

WEIGHTS = {
    "sharpe": 0.30,
    "excess_pct": 0.30,
    "ret_pct": 0.20,
    "win_rate": 0.20,
}


def _rank_pct(series: pd.Series, higher_better: bool = True) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if not higher_better:
        s = -s
    return s.rank(pct=True, method="average")


def score_oos_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为每只 ETF 的 OOS 段打 composite_score。"""
    if not rows:
        return []
    df = pd.DataFrame(rows)
    for col in WEIGHTS:
        src = "oos_win_rate" if col == "win_rate" else col
        if col == "win_rate":
            df[col] = pd.to_numeric(df.get("oos_win_rate"), errors="coerce")
        elif col in ("sharpe", "excess_pct", "ret_pct"):
            df[col] = df["oos"].apply(lambda x: x.get(col) if isinstance(x, dict) else float("nan"))
    score = pd.Series(0.0, index=df.index)
    for col, w in WEIGHTS.items():
        score = score + w * _rank_pct(df[col]).fillna(0.0)
    # 闭环过少惩罚
    trades = pd.to_numeric(df.get("closed_trades"), errors="coerce").fillna(0)
    score = score - (trades < 2).astype(float) * 0.5
    df["composite_score"] = score
    out = []
    for i, row in df.iterrows():
        d = rows[int(i)].copy()
        d["composite_score"] = float(df.loc[i, "composite_score"])
        for col in WEIGHTS:
            d[f"oos_{col}"] = float(df.loc[i, col]) if pd.notna(df.loc[i, col]) else float("nan")
        out.append(d)
    out.sort(key=lambda x: x.get("composite_score", -1e9), reverse=True)
    for rank, row in enumerate(out, 1):
        row["oos_rank"] = rank
    return out
