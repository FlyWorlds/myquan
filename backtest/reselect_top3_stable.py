"""仅用 train/valid 稳定性重选 Top3（不看 test）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "factor4_out"
GRID = OUT / "strategy5_mine_grid_top3.csv"
BEST = OUT / "strategy5_best.json"
PORT = Path(__file__).resolve().parent.parent / "strategy" / "strategies" / "strategy5" / "portfolio.py"


def stab(r: pd.Series) -> float:
    ts, vs = float(r.train_sharpe), float(r.valid_sharpe)
    td, vd = float(r.train_dd), float(r.valid_dd)
    # 两端夏普都要高，差距小，回撤可控；略偏好更长持有（降换手）
    hold_bonus = min(float(r.hold_days), 25) / 100.0
    return min(ts, vs) - 0.6 * abs(ts - vs) - 0.9 * max(td, vd) + hold_bonus


def main() -> None:
    df = pd.read_csv(GRID)
    # 只要 train/valid；rev 主族
    cand = df[
        (df.kind == "rev")
        & (df.top_k == 3)
        & (df.train_sharpe >= 0.5)
        & (df.valid_sharpe >= 0.7)
        & (df.train_ret > 0.2)
        & (df.valid_ret > 0.1)
        & (df.train_dd <= 0.45)
        & (df.valid_dd <= 0.30)
    ].copy()
    cand["stab"] = cand.apply(stab, axis=1)
    cand = cand.sort_values(["stab", "valid_sharpe"], ascending=False)
    cols = [
        "kind",
        "n",
        "hold_days",
        "ma_filter",
        "train_sharpe",
        "valid_sharpe",
        "train_dd",
        "valid_dd",
        "test_sharpe",
        "test_ret",
        "full_sharpe",
        "full_ret",
        "full_dd",
        "stab",
    ]
    print("stable top8 (selection ignores test columns):")
    print(cand[cols].head(8).to_string(index=False))
    best = cand.iloc[0]

    # 若 test/full 缺失则保持 NaN，回测脚本会重算
    def fget(col, default=None):
        v = best.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v) if col != "full_buys" else int(v)

    cfg = {
        "kind": str(best["kind"]),
        "n": int(best["n"]),
        "top_k": 3,
        "hold_days": int(best["hold_days"]),
        "min_score": None,
        "ma_filter": None if pd.isna(best["ma_filter"]) else int(best["ma_filter"]),
        "select_tag": "train_valid_stability_no_test",
        "protocol": {
            "train": "20200101-20221231",
            "valid": "20230101-20231231",
            "test": "20240101-now",
            "no_lookahead": "signal close -> next open",
            "selection_uses_test": False,
            "stability": "min(train,valid)_sharpe - 0.6*|gap| - 0.9*max_dd + hold_bonus",
        },
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
        "test": {
            "sharpe": fget("test_sharpe"),
            "ret": fget("test_ret"),
            "dd": fget("test_dd"),
        },
        "full": {
            "sharpe": fget("full_sharpe"),
            "ret": fget("full_ret"),
            "dd": fget("full_dd"),
            "n_buys": fget("full_buys"),
        },
        "stab": float(best["stab"]),
    }
    BEST.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    text = PORT.read_text(encoding="utf-8")
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "{cfg["kind"]}",\n'
        f'    "n": {cfg["n"]},\n'
        f'    "top_k": 3,\n'
        f'    "hold_days": {cfg["hold_days"]},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": {cfg["ma_filter"]!r},\n'
        '    "start": "20200101",\n'
        '    "warm_start": "20180101",\n'
        '    "universe": "zz1000_mainboard",\n'
        "}\n"
    )
    PORT.write_text(
        re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S),
        encoding="utf-8",
    )
    print("PICK", cfg["kind"], cfg["n"], "top", 3, "hold", cfg["hold_days"])
    print(
        "reported test sharpe (not used in pick):",
        cfg["test"]["sharpe"],
        "full sharpe:",
        cfg["full"]["sharpe"],
    )


if __name__ == "__main__":
    main()
