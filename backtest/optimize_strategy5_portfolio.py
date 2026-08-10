"""策略五 Top3：训/验/测拆分挖参（抬夏普，禁止用测试段选参）。

时间线（未来对选参未知）：
  · train  2020-01 → 2022-12  ：门槛过滤
  · valid  2023-01 → 2023-12  ：选参唯一依据
  · test   2024-01 → 今        ：只汇报，不参与选参
交易无未来函数：信号日收盘 → 次日开盘成交（simulate_fast）。
"""

from __future__ import annotations

import itertools
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.mine_zz1000_momentum import factor_matrix, simulate_fast  # noqa: E402
from backtest.zz1000_momentum_select import PANEL_PATH  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "factor4_out"
BEST_PATH = OUT_DIR / "strategy5_best.json"
GRID_PATH = OUT_DIR / "strategy5_mine_grid_top3.csv"

TOP_K = 3
TRAIN_START, TRAIN_END = "20200101", "20221231"
VALID_START, VALID_END = "20230101", "20231231"
TEST_START, FULL_START = "20240101", "20200101"


def _load_panel():
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"缺少面板: {PANEL_PATH}")
    wide = pd.read_parquet(PANEL_PATH)
    print(f"panel {wide['close'].shape}")
    return wide["open"], wide["high"], wide["low"], wide["close"]


def _tz(s: str, idx: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def _sim(fac, opens, closes, *, start: str, end: str | None, hold: int, ma):
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
        top_k=TOP_K,
        hold_days=hold,
        min_score=None,
        require_above_ma=ma,
    )


def _score_sharpe_first(m: dict) -> float:
    """选参分：夏普为主，回撤惩罚，收益弱权重。"""
    return float(m["sharpe"] - 1.2 * m["dd"] + 0.15 * max(min(m["ret"], 2.0), -0.5))


def _eval_grid(opens, highs, lows, closes, grid, rows: list, tag: str) -> None:
    t0 = time.time()
    cache: dict[tuple, object] = {}
    for i, (kind, n, hold, ma) in enumerate(grid, 1):
        key = (kind, n)
        if key not in cache:
            cache[key] = factor_matrix(opens, highs, lows, closes, kind=kind, n=n)
        fac = cache[key]
        train = _sim(
            fac, opens, closes, start=TRAIN_START, end=TRAIN_END, hold=hold, ma=ma
        )
        valid = _sim(
            fac, opens, closes, start=VALID_START, end=VALID_END, hold=hold, ma=ma
        )
        # 测试/全区间仅对候选后算；粗筛阶段先算 valid，全量在末尾补
        rows.append(
            {
                "phase": tag,
                "kind": kind,
                "n": n,
                "top_k": TOP_K,
                "hold_days": hold,
                "ma_filter": ma,
                "train_sharpe": train["sharpe"],
                "train_ret": train["ret"],
                "train_dd": train["dd"],
                "valid_sharpe": valid["sharpe"],
                "valid_ret": valid["ret"],
                "valid_dd": valid["dd"],
                "valid_score": _score_sharpe_first(valid),
                "train_score": _score_sharpe_first(train),
            }
        )
        if i % 15 == 0 or i == len(grid):
            print(f"  [{tag}] {i}/{len(grid)} ({time.time()-t0:.0f}s)")


def _fill_test_full(opens, highs, lows, closes, df: pd.DataFrame) -> pd.DataFrame:
    cache: dict[tuple, object] = {}
    out = df.copy()
    for col in (
        "test_sharpe",
        "test_ret",
        "test_dd",
        "full_sharpe",
        "full_ret",
        "full_dd",
        "full_buys",
        "test_score",
        "full_score",
    ):
        out[col] = pd.NA
    t0 = time.time()
    for i, row in out.iterrows():
        key = (row["kind"], int(row["n"]))
        if key not in cache:
            cache[key] = factor_matrix(
                opens, highs, lows, closes, kind=str(row["kind"]), n=int(row["n"])
            )
        fac = cache[key]
        ma = None if pd.isna(row["ma_filter"]) else int(row["ma_filter"])
        hold = int(row["hold_days"])
        test = _sim(
            fac, opens, closes, start=TEST_START, end=None, hold=hold, ma=ma
        )
        full = _sim(
            fac, opens, closes, start=FULL_START, end=None, hold=hold, ma=ma
        )
        out.at[i, "test_sharpe"] = test["sharpe"]
        out.at[i, "test_ret"] = test["ret"]
        out.at[i, "test_dd"] = test["dd"]
        out.at[i, "test_score"] = _score_sharpe_first(test)
        out.at[i, "full_sharpe"] = full["sharpe"]
        out.at[i, "full_ret"] = full["ret"]
        out.at[i, "full_dd"] = full["dd"]
        out.at[i, "full_buys"] = full["n_buys"]
        out.at[i, "full_score"] = _score_sharpe_first(full)
        if (out.index.get_loc(i) + 1) % 20 == 0:
            print(f"  [oos-fill] {out.index.get_loc(i)+1}/{len(out)} ({time.time()-t0:.0f}s)")
    return out


def _pick_best(df: pd.DataFrame) -> tuple[pd.Series, str]:
    # 选参只用 train+valid；测试集不进门槛
    cand = df[
        (df["train_sharpe"] >= 0.25)
        & (df["train_dd"] <= 0.50)
        & (df["train_ret"] > -0.15)
        & (df["valid_sharpe"] >= 0.40)
        & (df["valid_ret"] > 0.0)
        & (df["valid_dd"] <= 0.35)
    ].copy()
    tag = "train_gate+valid_sharpe"
    if cand.empty:
        cand = df[
            (df["train_sharpe"] >= 0.10)
            & (df["valid_sharpe"] >= 0.20)
            & (df["valid_ret"] > -0.10)
        ].copy()
        tag = "soft_gate+valid_sharpe"
    if cand.empty:
        cand = df.copy()
        tag = "fallback_valid"
    cand = cand.sort_values(
        ["valid_score", "valid_sharpe", "train_score"], ascending=False
    )
    best = cand.iloc[0]

    # 在 valid 接近的候选里，偏好更低 valid 回撤 / 更高 valid 夏普稳定性
    near = cand[
        cand["valid_score"] >= float(best["valid_score"]) - 0.15
    ].copy()
    if len(near) > 1:
        alt = near.sort_values(
            ["valid_sharpe", "valid_dd", "train_sharpe"],
            ascending=[False, True, False],
        ).iloc[0]
        if float(alt["valid_sharpe"]) >= float(best["valid_sharpe"]) - 0.05:
            if float(alt["valid_dd"]) < float(best["valid_dd"]) - 0.01:
                return alt, tag + "+lower_valid_dd"
            best = alt
    return best, tag


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opens, highs, lows, closes = _load_panel()
    rows: list[dict] = []

    # Phase1：反转主搜（Top3，偏长持有压换手抬夏普）
    g1 = list(
        itertools.product(
            ["rev"],
            [15, 20, 30, 40, 50, 60, 70, 90],
            [8, 10, 12, 15, 18, 20, 25, 30],
            [None, 20, 60],
        )
    )
    print(f"phase1 rev×Top{TOP_K} grid={len(g1)}  (选参只用2023 valid)")
    _eval_grid(opens, highs, lows, closes, g1, rows, "p1_rev")
    pd.DataFrame(rows).to_csv(GRID_PATH, index=False, encoding="utf-8-sig")

    # Phase2：动量族抽检（预期差，作对照）
    g2 = list(
        itertools.product(
            ["roc", "ma_gap", "breakout", "roc_vol"],
            [20, 40, 60],
            [12, 20, 30],
            [None],
        )
    )
    print(f"phase2 mom spot={len(g2)}")
    _eval_grid(opens, highs, lows, closes, g2, rows, "p2_mom")
    pd.DataFrame(rows).to_csv(GRID_PATH, index=False, encoding="utf-8-sig")

    df0 = pd.DataFrame(rows)
    top = (
        df0[df0["phase"] == "p1_rev"]
        .sort_values(["valid_score", "valid_sharpe"], ascending=False)
        .head(5)
    )
    g3_set: set[tuple] = set()
    for _, r in top.iterrows():
        ns = {int(r["n"]), max(10, int(r["n"]) - 5), int(r["n"]) + 5, int(r["n"]) + 10}
        holds = {
            int(r["hold_days"]),
            max(6, int(r["hold_days"]) - 2),
            int(r["hold_days"]) + 2,
            int(r["hold_days"]) + 5,
        }
        for item in itertools.product(["rev"], ns, holds, [None, 20, 60]):
            g3_set.add(item)
    seen = {(r["kind"], r["n"], r["hold_days"], r["ma_filter"]) for r in rows}
    g3 = sorted(
        g3_set - seen,
        key=lambda x: (x[0], x[1], x[2], x[3] is None, x[3] or 0),
    )
    print(f"phase3 refine={len(g3)}")
    if g3:
        _eval_grid(opens, highs, lows, closes, g3, rows, "p3_refine")

    df = pd.DataFrame(rows)
    # 只对 valid 前列补测 test/full，避免算完全表太慢
    pre = df.sort_values(["valid_score", "valid_sharpe"], ascending=False).head(40)
    print(f"fill test/full for top{len(pre)} by valid_score (测试段不选参)")
    filled = _fill_test_full(opens, highs, lows, closes, pre)
    # 合并回 df
    for col in (
        "test_sharpe",
        "test_ret",
        "test_dd",
        "full_sharpe",
        "full_ret",
        "full_dd",
        "full_buys",
        "test_score",
        "full_score",
    ):
        df[col] = pd.NA
    df.loc[filled.index, filled.columns] = filled

    df.to_csv(GRID_PATH, index=False, encoding="utf-8-sig")
    print(f"saved {GRID_PATH} n={len(df)}")

    best, tag = _pick_best(df)
    # 若 best 还没填 test，补一次
    if pd.isna(best.get("test_sharpe")):
        one = _fill_test_full(opens, highs, lows, closes, best.to_frame().T)
        best = one.iloc[0]

    cols = [
        "phase",
        "kind",
        "n",
        "top_k",
        "hold_days",
        "ma_filter",
        "train_sharpe",
        "train_ret",
        "train_dd",
        "valid_sharpe",
        "valid_ret",
        "valid_dd",
        "test_sharpe",
        "test_ret",
        "test_dd",
        "full_sharpe",
        "full_ret",
        "full_dd",
        "valid_score",
    ]
    ranked = df.sort_values(["valid_score", "valid_sharpe"], ascending=False)
    print("\n===== Top10 by VALID (测试未参与排序) =====")
    show = ranked.head(10).copy()
    # 确保展示列有 test/full
    need_fill = show[show["test_sharpe"].isna()]
    if len(need_fill):
        show.loc[need_fill.index] = _fill_test_full(
            opens, highs, lows, closes, need_fill
        )
    print(show[cols].to_string(index=False))
    print(f"\nBEST [{tag}]  (选参仅看 train+valid)")
    print(best[cols].to_string())
    print(
        f"\nOOS test(2024+) sharpe={float(best['test_sharpe']):.3f} "
        f"ret={float(best['test_ret'])*100:.1f}% dd={float(best['test_dd'])*100:.1f}%"
    )

    cfg = {
        "kind": str(best["kind"]),
        "n": int(best["n"]),
        "top_k": TOP_K,
        "hold_days": int(best["hold_days"]),
        "min_score": None,
        "ma_filter": None if pd.isna(best["ma_filter"]) else int(best["ma_filter"]),
        "select_tag": tag,
        "protocol": {
            "train": f"{TRAIN_START}-{TRAIN_END}",
            "valid": f"{VALID_START}-{VALID_END}",
            "test": f"{TEST_START}-now",
            "no_lookahead": "signal close -> next open",
            "selection_uses_test": False,
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
            "sharpe": float(best["test_sharpe"]),
            "ret": float(best["test_ret"]),
            "dd": float(best["test_dd"]),
        },
        "full": {
            "sharpe": float(best["full_sharpe"]),
            "ret": float(best["full_ret"]),
            "dd": float(best["full_dd"]),
            "n_buys": int(best["full_buys"]),
        },
    }
    BEST_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {BEST_PATH}")

    port_py = _MYQUAN / "strategy" / "strategies" / "strategy5" / "portfolio.py"
    text = port_py.read_text(encoding="utf-8")
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "{cfg["kind"]}",\n'
        f'    "n": {cfg["n"]},\n'
        f'    "top_k": {TOP_K},\n'
        f'    "hold_days": {cfg["hold_days"]},\n'
        f'    "min_score": {cfg["min_score"]!r},\n'
        f'    "ma_filter": {cfg["ma_filter"]!r},\n'
        '    "start": "20200101",\n'
        '    "warm_start": "20180101",\n'
        '    "universe": "zz1000_mainboard",\n'
        "}\n"
    )
    new = re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S)
    if new != text:
        port_py.write_text(new, encoding="utf-8")
        print(f"updated {port_py}")


if __name__ == "__main__":
    main()
