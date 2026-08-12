"""落地 plain rev100 / hold18 为策略五默认。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backtest" / "factor4_out"
PORT = ROOT / "strategy" / "strategies" / "strategy5" / "portfolio.py"

df = pd.read_csv(OUT / "strategy5_mine_excess_guard.csv")
pick = df[(df["mode"] == "plain") & (df["n"] == 100) & (df["hold_days"] == 18)].iloc[0]
base = df[(df["mode"] == "dual") & (df["n"] == 90) & (df["n2"] == 40) & (df["hold_days"] == 20)].iloc[0]

prev = {}
best_path = OUT / "strategy5_best.json"
if best_path.exists():
    prev = json.loads(best_path.read_text(encoding="utf-8"))
bh = prev.get(
    "bh",
    {
        "train": 0.5664,
        "valid": 0.0198,
        "vh1": 0.0804,
        "vh2": -0.0617,
        "test": 0.4815,
        "full": 1.4141,
    },
)

cfg = {
    "kind": "rev",
    "n": 100,
    "n2": None,
    "w": 1.0,
    "top_k": 3,
    "hold_days": 18,
    "min_score": None,
    "ma_filter": None,
    "mode": "plain",
    "vol_max_pct": None,
    "universe": "zz500_1000_mainboard",
    "select_tag": "excess_guard_plain100_h18",
    "rejected_note": "拒绝 plain90/hold14（衰减76%）；选 OOS 超额>0 且衰减约26% 的 plain100/hold18",
    "baseline": {
        "mode": "dual",
        "n": 90,
        "n2": 40,
        "hold_days": 20,
        "full_ret": float(base.full_ret),
        "full_excess": float(base.full_ex),
        "full_sharpe": float(base.full_sharpe),
        "test_excess": float(base.test_ex),
        "test_sharpe": float(base.test_sharpe),
    },
    "bh": {k: float(v) for k, v in bh.items()},
    "train": {"sharpe": float(pick.train_sharpe), "excess": float(pick.train_ex)},
    "valid": {
        "sharpe": float(pick.valid_sharpe),
        "excess": float(pick.valid_ex),
        "h1": float(pick.vh1),
        "h2": float(pick.vh2),
    },
    "test": {
        "sharpe": float(pick.test_sharpe),
        "ret": float(pick.test_ret),
        "dd": float(pick.test_dd),
        "excess": float(pick.test_ex),
    },
    "full": {
        "sharpe": float(pick.full_sharpe),
        "ret": float(pick.full_ret),
        "dd": float(pick.full_dd),
        "excess": float(pick.full_ex),
        "n_buys": int(pick.full_buys),
    },
    "sharpe_decay": float(pick.sharpe_decay),
    "score": float(pick.comp),
}
best_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

block = """PORTFOLIO_DEFAULTS = {
    "kind": "rev",
    "n": 100,
    "top_k": 3,
    "hold_days": 18,
    "min_score": None,
    "ma_filter": None,
    "mode": "plain",
    "n2": None,
    "w": 1.0,
    "vol_max_pct": None,
    "persist": None,
    "pool": None,
    "start": "20200101",
    "warm_start": "20180101",
    "universe": "zz500_1000_mainboard",
}
"""
text = PORT.read_text(encoding="utf-8")
PORT.write_text(
    re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S),
    encoding="utf-8",
)
print("PICK plain rev100 / hold18")
print(
    f"full_ex {cfg['baseline']['full_excess']:.3f}->{cfg['full']['excess']:.3f} "
    f"test_ex {cfg['baseline']['test_excess']:.3f}->{cfg['test']['excess']:.3f} "
    f"decay={cfg['sharpe_decay']:.3f}"
)
