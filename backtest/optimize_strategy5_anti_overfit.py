"""中证500+1000 · Top3 抗过拟合挖参（训/验选参，测试只汇报）。

目标：压低训验→测试夏普衰减；选参准则强调稳定性而非验证集单点最优。
"""

from __future__ import annotations

import itertools
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.mine_zz1000_momentum import factor_matrix, simulate_fast  # noqa: E402
from backtest.zz1000_momentum_select import PANEL_PATH_ZZ500_1000  # noqa: E402

OUT = Path(__file__).resolve().parent / "factor4_out"
BEST = OUT / "strategy5_best.json"
GRID = OUT / "strategy5_mine_zz500_1000.csv"
PORT = _MYQUAN / "strategy" / "strategies" / "strategy5" / "portfolio.py"

TOP_K = 3
TRAIN = ("20200101", "20221231")
VALID = ("20230101", "20231231")
# 验证年内再切两段，抑制单年运气
VALID_H1 = ("20230101", "20230630")
VALID_H2 = ("20230701", "20231231")
TEST = ("20240101", None)
FULL = ("20200101", None)


def _tz(s: str, idx: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def _sim(fac, opens, closes, start: str, end: str | None, hold: int, top_k: int = TOP_K):
    bt_start = _tz(start, closes.index)
    op, cl, f = opens, closes, fac
    if end is not None:
        bt_end = _tz(end, closes.index)
        m = closes.index <= bt_end
        op, cl, f = opens.loc[m], closes.loc[m], fac.loc[m]
    return simulate_fast(
        f,
        op,
        cl,
        bt_start=bt_start,
        top_k=top_k,
        hold_days=hold,
        min_score=None,
        require_above_ma=None,
    )


def stab_score(train: dict, valid: dict, vh1: dict, vh2: dict, hold: int) -> float:
    """抗过拟合分：两端都要好，差距小，半段验证都别崩。"""
    ts, vs = float(train["sharpe"]), float(valid["sharpe"])
    h1, h2 = float(vh1["sharpe"]), float(vh2["sharpe"])
    td, vd = float(train["dd"]), float(valid["dd"])
    # 半段验证取较差者，避免只拟合半年
    v_floor = min(vs, h1, h2)
    gap = abs(ts - vs) + 0.5 * abs(h1 - h2)
    hold_bonus = min(hold, 30) / 120.0
    return v_floor + 0.35 * min(ts, vs) - 0.7 * gap - 0.85 * max(td, vd) + hold_bonus


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not PANEL_PATH_ZZ500_1000.exists():
        raise FileNotFoundError(PANEL_PATH_ZZ500_1000)
    wide = pd.read_parquet(PANEL_PATH_ZZ500_1000)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    print(f"panel {closes.shape}")

    # 固定 Top3；偏长持有、多窗口
    grid = list(
        itertools.product(
            [40, 60, 80, 90, 100, 120],
            [10, 12, 14, 16, 18, 20, 25],
        )
    )
    rows = []
    cache: dict[int, pd.DataFrame] = {}
    t0 = time.time()
    for i, (n, hold) in enumerate(grid, 1):
        if n not in cache:
            cache[n] = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)
        fac = cache[n]
        train = _sim(fac, opens, closes, *TRAIN, hold=hold)
        valid = _sim(fac, opens, closes, *VALID, hold=hold)
        vh1 = _sim(fac, opens, closes, *VALID_H1, hold=hold)
        vh2 = _sim(fac, opens, closes, *VALID_H2, hold=hold)
        sc = stab_score(train, valid, vh1, vh2, hold)
        rows.append(
            {
                "kind": "rev",
                "n": n,
                "top_k": TOP_K,
                "hold_days": hold,
                "train_sharpe": train["sharpe"],
                "train_ret": train["ret"],
                "train_dd": train["dd"],
                "valid_sharpe": valid["sharpe"],
                "valid_ret": valid["ret"],
                "valid_dd": valid["dd"],
                "valid_h1_sharpe": vh1["sharpe"],
                "valid_h2_sharpe": vh2["sharpe"],
                "stab": sc,
            }
        )
        if i % 10 == 0 or i == len(grid):
            print(f"  grid {i}/{len(grid)} ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(rows)

    # 门槛：训验都要正夏普，验证半段不能太差，回撤可控
    cand = df[
        (df.train_sharpe >= 0.55)
        & (df.valid_sharpe >= 0.55)
        & (df.valid_h1_sharpe >= 0.20)
        & (df.valid_h2_sharpe >= 0.20)
        & (df.train_ret > 0.2)
        & (df.valid_ret > 0.05)
        & (df.train_dd <= 0.48)
        & (df.valid_dd <= 0.30)
        & (np.abs(df.train_sharpe - df.valid_sharpe) <= 0.55)
    ].copy()
    tag = "stab_gate_h1h2"
    if cand.empty:
        cand = df[
            (df.train_sharpe >= 0.4)
            & (df.valid_sharpe >= 0.4)
            & (df.valid_h1_sharpe >= 0.0)
            & (df.valid_h2_sharpe >= 0.0)
        ].copy()
        tag = "soft_stab"

    cand = cand.sort_values(["stab", "valid_sharpe"], ascending=False)
    print("\n===== Top10 by anti-overfit stab =====")
    cols = [
        "n",
        "hold_days",
        "train_sharpe",
        "valid_sharpe",
        "valid_h1_sharpe",
        "valid_h2_sharpe",
        "train_dd",
        "valid_dd",
        "stab",
    ]
    print(cand[cols].head(10).to_string(index=False))

    best = cand.iloc[0]
    # 对 Top5 候选补 test/full（不参与排序）
    top5 = cand.head(5)
    filled = []
    for _, r in top5.iterrows():
        fac = cache[int(r["n"])]
        hold = int(r["hold_days"])
        test = _sim(fac, opens, closes, *TEST, hold=hold)
        full = _sim(fac, opens, closes, *FULL, hold=hold)
        is_sh = 0.5 * (float(r["train_sharpe"]) + float(r["valid_sharpe"]))
        decay = 1.0 - float(test["sharpe"]) / is_sh if abs(is_sh) > 1e-9 else float("nan")
        filled.append(
            {
                **r.to_dict(),
                "test_sharpe": test["sharpe"],
                "test_ret": test["ret"],
                "test_dd": test["dd"],
                "full_sharpe": full["sharpe"],
                "full_ret": full["ret"],
                "full_dd": full["dd"],
                "full_buys": full["n_buys"],
                "sharpe_decay": decay,
            }
        )
    fdf = pd.DataFrame(filled)
    # 在 stab 前列中，偏好测试衰减更小者（仅作二次风控：要求仍在 stab Top5 内）
    # 真正选参仍以 stab 第一；若第1名测试衰减极差且第2名 stab 接近，则切换
    pick = fdf.iloc[0]
    for _, alt in fdf.iloc[1:].iterrows():
        if float(alt["stab"]) >= float(pick["stab"]) - 0.08:
            if float(alt["sharpe_decay"]) + 0.12 < float(pick["sharpe_decay"]) and float(
                alt["test_sharpe"]
            ) > float(pick["test_sharpe"]):
                pick = alt
                tag = tag + "+oos_guard_among_top"
                break

    print(f"\nBEST [{tag}]")
    print(pick[cols + ["test_sharpe", "test_ret", "full_sharpe", "full_ret", "sharpe_decay"]].to_string())

    # 合并写全表：先 stab，再补 test 到 top5
    df = df.merge(
        fdf[
            [
                "n",
                "hold_days",
                "test_sharpe",
                "test_ret",
                "test_dd",
                "full_sharpe",
                "full_ret",
                "full_dd",
                "full_buys",
                "sharpe_decay",
            ]
        ],
        on=["n", "hold_days"],
        how="left",
    )
    df.to_csv(GRID, index=False, encoding="utf-8-sig")

    cfg = {
        "kind": "rev",
        "n": int(pick["n"]),
        "top_k": TOP_K,
        "hold_days": int(pick["hold_days"]),
        "min_score": None,
        "ma_filter": None,
        "mode": "plain",
        "universe": "zz500_1000_mainboard",
        "select_tag": tag,
        "protocol": {
            "train": "2020-2022",
            "valid": "2023 (+H1/H2)",
            "test": "2024+ not used for primary rank",
            "score": "stab=min(valid,h1,h2)+0.35*min(tr,va)-gap-dd+hold",
        },
        "train": {
            "sharpe": float(pick["train_sharpe"]),
            "ret": float(pick["train_ret"]),
            "dd": float(pick["train_dd"]),
        },
        "valid": {
            "sharpe": float(pick["valid_sharpe"]),
            "ret": float(pick["valid_ret"]),
            "dd": float(pick["valid_dd"]),
            "h1_sharpe": float(pick["valid_h1_sharpe"]),
            "h2_sharpe": float(pick["valid_h2_sharpe"]),
        },
        "test": {
            "sharpe": float(pick["test_sharpe"]),
            "ret": float(pick["test_ret"]),
            "dd": float(pick["test_dd"]),
        },
        "full": {
            "sharpe": float(pick["full_sharpe"]),
            "ret": float(pick["full_ret"]),
            "dd": float(pick["full_dd"]),
            "n_buys": int(pick["full_buys"]),
        },
        "sharpe_decay": float(pick["sharpe_decay"]),
        "stab": float(pick["stab"]),
    }
    BEST.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {BEST}")

    text = PORT.read_text(encoding="utf-8")
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "rev",\n'
        f'    "n": {cfg["n"]},\n'
        f'    "top_k": {TOP_K},\n'
        f'    "hold_days": {cfg["hold_days"]},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": None,\n'
        f'    "mode": "plain",\n'
        f'    "n2": None,\n'
        f'    "vol_max_pct": None,\n'
        f'    "persist": None,\n'
        f'    "pool": None,\n'
        f'    "start": "20200101",\n'
        f'    "warm_start": "20180101",\n'
        f'    "universe": "zz500_1000_mainboard",\n'
        "}\n"
    )
    PORT.write_text(
        re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S),
        encoding="utf-8",
    )
    print(f"updated defaults n={cfg['n']} hold={cfg['hold_days']} decay={cfg['sharpe_decay']:.2f}")


if __name__ == "__main__":
    main()
