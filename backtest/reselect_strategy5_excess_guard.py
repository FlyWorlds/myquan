"""抗过拟合约束下重选策略五参数（拒绝样本外严重衰减方案）。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.mine_zz1000_momentum import factor_matrix, simulate_fast  # noqa: E402
from backtest.zz1000_momentum_select import PANEL_PATH_ZZ500_1000  # noqa: E402

OUT = Path(__file__).resolve().parent / "factor4_out"
PORT = _MYQUAN / "strategy" / "strategies" / "strategy5" / "portfolio.py"
TOP_K = 3
PERIODS = {
    "train": ("20200101", "20221231"),
    "valid": ("20230101", "20231231"),
    "vh1": ("20230101", "20230630"),
    "vh2": ("20230701", "20231231"),
    "test": ("20240101", None),
    "full": ("20200101", None),
}


def _tz(s, idx):
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def ew_bh(closes, start, end):
    a = _tz(start, closes.index)
    cl = closes.loc[closes.index >= a]
    if end is not None:
        cl = cl.loc[cl.index <= _tz(end, closes.index)]
    d = cl.pct_change().mean(axis=1).dropna()
    return float((1 + d).prod() - 1)


def sim(fac, opens, closes, start, end, hold):
    bt_start = _tz(start, closes.index)
    op, cl, f = opens, closes, fac
    if end is not None:
        m = closes.index <= _tz(end, closes.index)
        op, cl, f = opens.loc[m], closes.loc[m], fac.loc[m]
    return simulate_fast(
        f,
        op,
        cl,
        bt_start=bt_start,
        top_k=TOP_K,
        hold_days=hold,
        min_score=None,
        require_above_ma=None,
    )


def cs_z(df):
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def main() -> None:
    wide = pd.read_parquet(PANEL_PATH_ZZ500_1000)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    bh = {k: ew_bh(closes, a, b) for k, (a, b) in PERIODS.items()}

    cands = [
        {"mode": "plain", "n": 100, "n2": None, "w": 1.0, "hold_days": 16},
        {"mode": "plain", "n": 100, "n2": None, "w": 1.0, "hold_days": 18},
        {"mode": "plain", "n": 100, "n2": None, "w": 1.0, "hold_days": 20},
        {"mode": "plain", "n": 90, "n2": None, "w": 1.0, "hold_days": 18},
        {"mode": "plain", "n": 90, "n2": None, "w": 1.0, "hold_days": 20},
        {"mode": "dual", "n": 90, "n2": 40, "w": 1.0, "hold_days": 18},
        {"mode": "dual", "n": 90, "n2": 40, "w": 1.0, "hold_days": 20},
        {"mode": "dual", "n": 90, "n2": 40, "w": 1.0, "hold_days": 16},
        {"mode": "dual", "n": 100, "n2": 40, "w": 1.0, "hold_days": 16},
        {"mode": "dual", "n": 100, "n2": 50, "w": 1.0, "hold_days": 16},
        {"mode": "dual", "n": 100, "n2": 40, "w": 1.0, "hold_days": 18},
        {"mode": "dual", "n": 90, "n2": 50, "w": 1.0, "hold_days": 16},
    ]

    rev: dict[int, pd.DataFrame] = {}

    def get_rev(n: int):
        if n not in rev:
            rev[n] = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)
        return rev[n]

    def make(c):
        if c["mode"] == "plain":
            return get_rev(c["n"])
        return cs_z(get_rev(c["n"])) + c["w"] * cs_z(get_rev(int(c["n2"])))

    rows = []
    for c in cands:
        fac = make(c)
        m = {}
        for k, (a, b) in PERIODS.items():
            s = sim(fac, opens, closes, a, b, c["hold_days"])
            m[k] = {**s, "bh": bh[k], "excess": s["ret"] - bh[k]}
        is_sh = 0.5 * (m["train"]["sharpe"] + m["valid"]["sharpe"])
        decay = 1 - m["test"]["sharpe"] / is_sh if abs(is_sh) > 1e-9 else np.nan
        h_floor = min(m["vh1"]["sharpe"], m["vh2"]["sharpe"])
        comp = (
            0.55 * m["full"]["excess"]
            + 0.35 * m["test"]["excess"]
            - 0.45 * decay
            + 0.15 * min(m["train"]["sharpe"], m["valid"]["sharpe"], h_floor)
        )
        rows.append(
            {
                **c,
                "train_ex": m["train"]["excess"],
                "valid_ex": m["valid"]["excess"],
                "test_ex": m["test"]["excess"],
                "full_ex": m["full"]["excess"],
                "full_ret": m["full"]["ret"],
                "full_sharpe": m["full"]["sharpe"],
                "full_dd": m["full"]["dd"],
                "test_sharpe": m["test"]["sharpe"],
                "test_ret": m["test"]["ret"],
                "test_dd": m["test"]["dd"],
                "train_sharpe": m["train"]["sharpe"],
                "valid_sharpe": m["valid"]["sharpe"],
                "vh1": m["vh1"]["sharpe"],
                "vh2": m["vh2"]["sharpe"],
                "h_floor": h_floor,
                "sharpe_decay": decay,
                "full_buys": m["full"]["n_buys"],
                "comp": comp,
            }
        )
        print(
            f"{c['mode']} n={c['n']} n2={c['n2']} h={c['hold_days']}: "
            f"full_ex={m['full']['excess']:.3f} test_ex={m['test']['excess']:.3f} "
            f"decay={decay:.3f} test_sh={m['test']['sharpe']:.3f} comp={comp:.3f}"
        )

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "strategy5_mine_excess_guard.csv", index=False, encoding="utf-8-sig")
    ok = df[
        (df.test_sharpe >= 0.40)
        & (df.sharpe_decay <= 0.50)
        & (df.test_ex >= -0.12)
        & (df.h_floor >= 0.30)
    ].copy()
    print("--- OOS-ok ---")
    print(ok.sort_values("comp", ascending=False).to_string(index=False))
    if ok.empty:
        pick = df.sort_values("comp", ascending=False).iloc[0]
        tag = "excess_guard_soft"
    else:
        pick = ok.sort_values(["comp", "full_ex"], ascending=False).iloc[0]
        tag = "excess_guard"

    base = df[(df.mode == "dual") & (df.n == 90) & (df.n2 == 40) & (df.hold_days == 20)].iloc[0]
    print("PICK", tag)
    print(pick.to_string())

    cfg = {
        "kind": "rev",
        "n": int(pick.n),
        "n2": None if pd.isna(pick.n2) else int(pick.n2),
        "w": float(pick.w),
        "top_k": 3,
        "hold_days": int(pick.hold_days),
        "min_score": None,
        "ma_filter": None,
        "mode": str(pick.mode),
        "vol_max_pct": None,
        "universe": "zz500_1000_mainboard",
        "select_tag": tag,
        "rejected_note": "plain90/hold14 全样本超额高但测试衰减>70%已拒绝",
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
    (OUT / "strategy5_best.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    n2_lit = "None" if cfg["n2"] is None else str(cfg["n2"])
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "rev",\n'
        f'    "n": {cfg["n"]},\n'
        f'    "top_k": 3,\n'
        f'    "hold_days": {cfg["hold_days"]},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": None,\n'
        f'    "mode": "{cfg["mode"]}",\n'
        f'    "n2": {n2_lit},\n'
        f'    "w": {cfg["w"]},\n'
        f'    "vol_max_pct": None,\n'
        f'    "persist": None,\n'
        f'    "pool": None,\n'
        f'    "start": "20200101",\n'
        f'    "warm_start": "20180101",\n'
        f'    "universe": "zz500_1000_mainboard",\n'
        "}\n"
    )
    text = PORT.read_text(encoding="utf-8")
    PORT.write_text(
        re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S),
        encoding="utf-8",
    )
    print(
        f"updated {cfg['mode']} n={cfg['n']} n2={cfg['n2']} hold={cfg['hold_days']} "
        f"full_ex {cfg['baseline']['full_excess']:.3f}->{cfg['full']['excess']:.3f} "
        f"test_ex {cfg['baseline']['test_excess']:.3f}->{cfg['test']['excess']:.3f} "
        f"decay={cfg['sharpe_decay']:.3f}"
    )


if __name__ == "__main__":
    main()
