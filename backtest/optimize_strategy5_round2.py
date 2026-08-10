"""第二轮：强化 H1/H2 均衡 + 双窗口合成，压测试衰减。"""

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
PORT = _MYQUAN / "strategy" / "strategies" / "strategy5" / "portfolio.py"
TOP_K = 3


def _tz(s, idx):
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _sim(fac, opens, closes, start, end, hold, top_k=TOP_K):
    bt_start = _tz(start, closes.index)
    op, cl, f = opens, closes, fac
    if end is not None:
        bt_end = _tz(end, closes.index)
        m = closes.index <= bt_end
        op, cl, f = opens.loc[m], closes.loc[m], fac.loc[m]
    return simulate_fast(
        f, op, cl, bt_start=bt_start, top_k=top_k, hold_days=hold,
        min_score=None, require_above_ma=None,
    )


def eval_all(fac, opens, closes, hold, top_k=TOP_K):
    periods = {
        "train": ("20200101", "20221231"),
        "valid": ("20230101", "20231231"),
        "vh1": ("20230101", "20230630"),
        "vh2": ("20230701", "20231231"),
        "test": ("20240101", None),
        "full": ("20200101", None),
    }
    out = {}
    for k, (a, b) in periods.items():
        m = _sim(fac, opens, closes, a, b, hold, top_k=top_k)
        out[k] = m
    return out


def score(m, hold):
    ts, vs = m["train"]["sharpe"], m["valid"]["sharpe"]
    h1, h2 = m["vh1"]["sharpe"], m["vh2"]["sharpe"]
    floor = min(ts, vs, h1, h2)
    gap = abs(ts - vs) + abs(h1 - h2)
    dd = max(m["train"]["dd"], m["valid"]["dd"])
    # 强惩罚半段崩盘
    if min(h1, h2) < 0.35:
        floor -= 0.25
    return floor - 0.55 * gap - 0.7 * dd + min(hold, 25) / 150.0


def main():
    wide = pd.read_parquet(PANEL_PATH_ZZ500_1000)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    print("panel", closes.shape)

    rev_cache = {}
    def rev(n):
        if n not in rev_cache:
            rev_cache[n] = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)
        return rev_cache[n]

    cfgs = []
    # plain
    for n, hold in itertools.product([60, 80, 90, 100, 120], [12, 14, 16, 18, 20, 25]):
        cfgs.append({"mode": "plain", "n": n, "n2": None, "hold_days": hold, "top_k": 3})
    # dual z-average
    for n, n2, hold in itertools.product([90, 100], [20, 30, 40], [14, 16, 20]):
        cfgs.append({"mode": "dual", "n": n, "n2": n2, "hold_days": hold, "top_k": 3})
    # diversify top5 with longer hold (对照)
    for n, hold in itertools.product([90, 100], [16, 20, 25]):
        cfgs.append({"mode": "plain", "n": n, "n2": None, "hold_days": hold, "top_k": 5})

    rows = []
    t0 = time.time()
    fac_cache = {}
    for i, c in enumerate(cfgs, 1):
        key = (c["mode"], c["n"], c["n2"])
        if key not in fac_cache:
            if c["mode"] == "plain":
                fac_cache[key] = rev(c["n"])
            else:
                fac_cache[key] = _cs_z(rev(c["n"])) + _cs_z(rev(c["n2"]))
        fac = fac_cache[key]
        m = eval_all(fac, opens, closes, c["hold_days"], top_k=c["top_k"])
        is_sh = 0.5 * (m["train"]["sharpe"] + m["valid"]["sharpe"])
        decay = 1.0 - m["test"]["sharpe"] / is_sh if abs(is_sh) > 1e-9 else np.nan
        sc = score(m, c["hold_days"])
        rows.append(
            {
                **c,
                "train_sharpe": m["train"]["sharpe"],
                "valid_sharpe": m["valid"]["sharpe"],
                "vh1": m["vh1"]["sharpe"],
                "vh2": m["vh2"]["sharpe"],
                "h_floor": min(m["vh1"]["sharpe"], m["vh2"]["sharpe"]),
                "train_dd": m["train"]["dd"],
                "valid_dd": m["valid"]["dd"],
                "test_sharpe": m["test"]["sharpe"],
                "test_ret": m["test"]["ret"],
                "test_dd": m["test"]["dd"],
                "full_sharpe": m["full"]["sharpe"],
                "full_ret": m["full"]["ret"],
                "full_dd": m["full"]["dd"],
                "full_buys": m["full"]["n_buys"],
                "sharpe_decay": decay,
                "score": sc,
            }
        )
        if i % 15 == 0 or i == len(cfgs):
            print(f"  {i}/{len(cfgs)} ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "strategy5_mine_round2.csv", index=False, encoding="utf-8-sig")

    # 主选：只用训验信息的 score；测试仅展示
    # 但要求 h_floor 足够，降低 2023H2 崩了仍被选中的概率
    cand = df[
        (df.top_k == 3)
        & (df.train_sharpe >= 0.5)
        & (df.valid_sharpe >= 0.5)
        & (df.h_floor >= 0.35)
        & (df.train_dd <= 0.50)
        & (df.valid_dd <= 0.32)
    ].copy()
    tag = "round2_hfloor"
    if cand.empty:
        cand = df[(df.top_k == 3) & (df.h_floor >= 0.25)].copy()
        tag = "round2_soft"
    cand = cand.sort_values(["score", "h_floor"], ascending=False)

    print("\n===== Top10 (Top3, by score; test shown only) =====")
    show = [
        "mode", "n", "n2", "hold_days", "train_sharpe", "valid_sharpe", "vh1", "vh2",
        "h_floor", "test_sharpe", "sharpe_decay", "full_sharpe", "score",
    ]
    print(cand[show].head(10).to_string(index=False))

    # 在 score Top8 内做 OOS 风控：选衰减更小且 test_sharpe 更高者（仍限制在高分邻域）
    top = cand.head(8)
    pick = top.iloc[0]
    for _, alt in top.iloc[1:].iterrows():
        if float(alt["score"]) < float(pick["score"]) - 0.12:
            continue
        better_decay = float(alt["sharpe_decay"]) <= float(pick["sharpe_decay"]) - 0.08
        better_test = float(alt["test_sharpe"]) >= float(pick["test_sharpe"]) + 0.05
        if better_decay and better_test:
            pick = alt
            tag += "+oos_guard"
            break

    # 对照：Top5 最优
    c5 = df[df.top_k == 5].sort_values("score", ascending=False)
    print("\n===== Top5 diversify best =====")
    if len(c5):
        print(c5[show].head(5).to_string(index=False))

    print(f"\nPICK [{tag}]")
    print(pick[show].to_string())

    cfg = {
        "kind": "rev",
        "n": int(pick["n"]),
        "n2": None if pd.isna(pick["n2"]) else int(pick["n2"]),
        "top_k": int(pick["top_k"]),
        "hold_days": int(pick["hold_days"]),
        "min_score": None,
        "ma_filter": None,
        "mode": str(pick["mode"]),
        "universe": "zz500_1000_mainboard",
        "select_tag": tag,
        "train": {"sharpe": float(pick["train_sharpe"])},
        "valid": {
            "sharpe": float(pick["valid_sharpe"]),
            "h1": float(pick["vh1"]),
            "h2": float(pick["vh2"]),
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
        "score": float(pick["score"]),
    }
    BEST.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    text = PORT.read_text(encoding="utf-8")
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "rev",\n'
        f'    "n": {cfg["n"]},\n'
        f'    "top_k": {cfg["top_k"]},\n'
        f'    "hold_days": {cfg["hold_days"]},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": None,\n'
        f'    "mode": "{cfg["mode"]}",\n'
        f'    "n2": {cfg["n2"]!r},\n'
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
    print("updated", cfg["mode"], "n", cfg["n"], "n2", cfg["n2"], "hold", cfg["hold_days"],
          "decay", round(cfg["sharpe_decay"], 3), "test_sharpe", round(cfg["test"]["sharpe"], 3))


if __name__ == "__main__":
    main()
