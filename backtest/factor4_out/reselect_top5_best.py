"""从 Top5 挖参表中按稳健口径重选默认。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
PORT = Path(__file__).resolve().parents[1] / "strategy" / "strategies" / "strategy5" / "portfolio.py"


def main() -> None:
    df = pd.read_csv(OUT / "strategy5_mine_grid_top5.csv")
    cand = df[
        (df.train_sharpe >= 0.05)
        & (df.train_dd <= 0.60)
        & (df.train_ret > -0.35)
        & (df.full_buys >= 100)
    ].copy()
    robust = cand[
        (cand.valid_ret > 0)
        & (cand.full_dd <= 0.40)
        & (cand.valid_sharpe >= 0.7)
    ].copy()
    print("robust n", len(robust))
    cols = [
        "kind",
        "n",
        "top_k",
        "hold_days",
        "ma_filter",
        "train_ret",
        "valid_ret",
        "valid_sharpe",
        "full_ret",
        "full_dd",
        "full_sharpe",
        "valid_score",
        "full_score",
    ]
    ranked = robust.sort_values(["full_score", "valid_score"], ascending=False)
    print(ranked[cols].head(8).to_string(index=False))
    best = ranked.iloc[0]
    cfg = {
        "kind": str(best["kind"]),
        "n": int(best["n"]),
        "top_k": 5,
        "hold_days": int(best["hold_days"]),
        "min_score": None,
        "ma_filter": None if pd.isna(best["ma_filter"]) else int(best["ma_filter"]),
        "select_tag": "top5_robust_full_dd<=40%",
        "train": {
            "sharpe": float(best["train_sharpe"]),
            "ret": float(best["train_ret"]),
            "dd": float(best["train_dd"]),
        },
        "valid": {
            "sharpe": float(best["valid_sharpe"]),
            "ret": float(best["valid_ret"]),
            "dd": float(best["valid_dd"]),
        },
        "full": {
            "sharpe": float(best["full_sharpe"]),
            "ret": float(best["full_ret"]),
            "dd": float(best["full_dd"]),
            "n_buys": int(best["full_buys"]),
        },
    }
    (OUT / "strategy5_best.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    text = PORT.read_text(encoding="utf-8")
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "{cfg["kind"]}",\n'
        f'    "n": {cfg["n"]},\n'
        f'    "top_k": 5,\n'
        f'    "hold_days": {cfg["hold_days"]},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": {cfg["ma_filter"]!r},\n'
        '    "start": "20200101",\n'
        '    "warm_start": "20180101",\n'
        '    "universe": "zz1000_mainboard",\n'
        "}\n"
    )
    new = re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S)
    PORT.write_text(new, encoding="utf-8")
    print("PICK", cfg)


if __name__ == "__main__":
    main()
