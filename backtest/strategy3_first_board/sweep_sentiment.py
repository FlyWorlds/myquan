#!/usr/bin/env python3
"""扫情绪门槛（T-1 mkt_lu + 连板梯度），基于可买信号与组合回测。"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from strategy.strategies.strategy3 import first_board as fb

fb.MKT_LU_MIN = None
fb.MKT_LU_MAX = None
fb.MKT_LIANBAN_MIN = None
fb.MKT_MAX_HEIGHT_MIN = None
fb.MKT_MAX_HEIGHT_MAX = None
fb.MKT_LADDER_SCORE_MIN = None
fb.SENTIMENT_LAG = 1
fb._SENTIMENT = None
fb._SENTIMENT_PREV = {}

sig_path = fb.OUT / "signals_0p0250_lag1.parquet"
if not sig_path.is_file():
    raise SystemExit(f"请先运行无门槛信号: {sig_path}")
entries = pd.read_parquet(sig_path)
entries = entries[entries["entry"] == True].copy()  # noqa: E712
print(f"可买信号 {len(entries)}")

# 补 T-1 情绪（信号里已有 sentiment 字段若从有门槛版本来）
if "sentiment_date" not in entries.columns:
    rows = []
    for _, r in entries.iterrows():
        _, s = fb.sentiment_row(r["trade_date"])
        rows.append(s)
    extra = pd.DataFrame(rows)
    entries = pd.concat([entries.reset_index(drop=True), extra], axis=1)

# 用组合回测逐配置（不重算 process_symbol）
lu_ranges = [(None, None), (20, 35), (24, 32), (22, 34)]
lb_mins = [None, 2, 3]
h_ranges = [(None, None), (2, 6), (2, 5), (3, 5)]

best = []
for (lu_lo, lu_hi), lb, (h_lo, h_hi) in itertools.product(lu_ranges, lb_mins, h_ranges):
    m = entries.copy()
    if lu_lo is not None:
        m = m[m["mkt_lu"].between(lu_lo, lu_hi)]
    if lb is not None:
        m = m[m["mkt_lianban"] >= lb]
    if h_lo is not None:
        m = m[m["mkt_max_height"].between(h_lo, h_hi)]
    if len(m) < 8:
        continue
    eq, summary, _ = fb.run_portfolio(m, entry_pct=0.025)
    best.append(
        (
            summary["total_return_pct"],
            summary["n_trades"],
            summary["sharpe_ratio"],
            lu_lo,
            lu_hi,
            lb,
            h_lo,
            h_hi,
        )
    )

best.sort(reverse=True)
print("\nTop 10 configs (2.5% thr):")
for row in best[:10]:
    ret, n, sh, lu_lo, lu_hi, lb, h_lo, h_hi = row
    print(
        f"ret={ret:+.1f}% n={n:3d} sh={sh:+.2f} "
        f"lu={lu_lo}-{lu_hi} lb>={lb} h={h_lo}-{h_hi}"
    )
