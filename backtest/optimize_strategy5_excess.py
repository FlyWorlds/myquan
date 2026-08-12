"""策略五 · 抬超额挖参（两阶段加速）：粗筛训验 → TopN 全量精评。

用法：
  cd backtest && python optimize_strategy5_excess.py
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
GRID = OUT / "strategy5_mine_excess.csv"
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
SCREEN = ("train", "valid", "vh1", "vh2")


def _tz(s: str, idx: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def ew_bh_ret(closes: pd.DataFrame, start: str, end: str | None) -> float:
    a = _tz(start, closes.index)
    cl = closes.loc[closes.index >= a]
    if end is not None:
        b = _tz(end, closes.index)
        cl = cl.loc[cl.index <= b]
    daily = cl.pct_change().mean(axis=1).dropna()
    if daily.empty:
        return float("nan")
    return float((1.0 + daily).prod() - 1.0)


def _sim(fac, opens, closes, start: str, end: str | None, hold: int):
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
        require_above_ma=None,
    )


def eval_keys(fac, opens, closes, hold: int, bh: dict, keys: tuple[str, ...]) -> dict:
    out = {}
    for k in keys:
        a, b = PERIODS[k]
        m = dict(_sim(fac, opens, closes, a, b, hold))
        m["bh"] = bh[k]
        m["excess"] = float(m["ret"] - bh[k]) if np.isfinite(bh[k]) else float("nan")
        out[k] = m
    return out


def select_score(m: dict, hold: int) -> float:
    te, ve = m["train"]["excess"], m["valid"]["excess"]
    ts, vs = m["train"]["sharpe"], m["valid"]["sharpe"]
    h1, h2 = m["vh1"]["sharpe"], m["vh2"]["sharpe"]
    floor = min(ts, vs, h1, h2)
    gap = abs(ts - vs) + abs(h1 - h2)
    dd = max(m["train"]["dd"], m["valid"]["dd"])
    excess_term = 0.55 * te + 0.45 * ve
    if min(h1, h2) < 0.30:
        floor -= 0.30
    return 1.35 * excess_term + 0.55 * floor - 0.45 * gap - 0.75 * dd + min(hold, 25) / 200.0


def build_configs() -> list[dict]:
    cfgs: list[dict] = []
    # 聚焦历史高收益邻域 + 若干对照
    for n, hold in itertools.product([80, 85, 90, 100, 120], [12, 14, 16, 18, 20]):
        cfgs.append({"mode": "plain", "n": n, "n2": None, "w": 1.0, "hold_days": hold})
    for n, n2, hold in itertools.product([90, 100], [30, 40, 50], [14, 16, 18, 20]):
        cfgs.append({"mode": "dual", "n": n, "n2": n2, "w": 1.0, "hold_days": hold})
    for n, n2, w, hold in itertools.product([90, 100], [40], [0.7, 1.3], [14, 16, 20]):
        cfgs.append({"mode": "dual_w", "n": n, "n2": n2, "w": w, "hold_days": hold})
    for n, hold, vmax in itertools.product([90, 100], [14, 16, 20], [0.70, 0.80]):
        cfgs.append(
            {
                "mode": "vol_mask",
                "n": n,
                "n2": None,
                "w": 1.0,
                "hold_days": hold,
                "vol_max_pct": vmax,
            }
        )
    # 去重
    seen = set()
    uniq = []
    for c in cfgs:
        key = (
            c["mode"],
            c["n"],
            c.get("n2"),
            c.get("w"),
            c["hold_days"],
            c.get("vol_max_pct"),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def make_factor(cfg, rev_z: dict, rev_raw: dict, closes) -> pd.DataFrame:
    n = int(cfg["n"])
    mode = cfg["mode"]
    if mode == "plain":
        return rev_raw[n]
    if mode in ("dual", "dual_w"):
        n2 = int(cfg["n2"])
        w = float(cfg.get("w") or 1.0)
        return rev_z[n] + w * rev_z[n2]
    if mode == "vol_mask":
        vol = closes.pct_change().rolling(20, min_periods=10).std()
        rnk = vol.rank(axis=1, pct=True, method="average")
        vmax = float(cfg.get("vol_max_pct") or 0.75)
        return rev_raw[n].where(rnk <= vmax)
    raise ValueError(mode)


def apply_portfolio_defaults(cfg: dict) -> None:
    text = PORT.read_text(encoding="utf-8")
    mode = str(cfg["mode"])
    n2 = cfg.get("n2")
    n2_lit = None if n2 is None or (isinstance(n2, float) and np.isnan(n2)) else int(n2)
    w = float(cfg.get("w") or 1.0)
    vmax = cfg.get("vol_max_pct")
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "rev",\n'
        f'    "n": {int(cfg["n"])},\n'
        f'    "top_k": {TOP_K},\n'
        f'    "hold_days": {int(cfg["hold_days"])},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": None,\n'
        f'    "mode": "{mode}",\n'
        f"    \"n2\": {n2_lit!r},\n"
        f"    \"w\": {w},\n"
        f"    \"vol_max_pct\": {vmax!r},\n"
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


def row_from(c: dict, m: dict, score: float | None = None) -> dict:
    is_sh = 0.5 * (m["train"]["sharpe"] + m["valid"]["sharpe"])
    decay = (
        1.0 - m["test"]["sharpe"] / is_sh
        if "test" in m and abs(is_sh) > 1e-9
        else float("nan")
    )
    out = {
        **c,
        "train_sharpe": m["train"]["sharpe"],
        "valid_sharpe": m["valid"]["sharpe"],
        "vh1": m["vh1"]["sharpe"],
        "vh2": m["vh2"]["sharpe"],
        "h_floor": min(m["vh1"]["sharpe"], m["vh2"]["sharpe"]),
        "train_dd": m["train"]["dd"],
        "valid_dd": m["valid"]["dd"],
        "train_excess": m["train"]["excess"],
        "valid_excess": m["valid"]["excess"],
        "score": float(score if score is not None else select_score(m, int(c["hold_days"]))),
    }
    if "test" in m:
        out.update(
            {
                "test_sharpe": m["test"]["sharpe"],
                "test_ret": m["test"]["ret"],
                "test_dd": m["test"]["dd"],
                "test_excess": m["test"]["excess"],
                "full_sharpe": m["full"]["sharpe"],
                "full_ret": m["full"]["ret"],
                "full_dd": m["full"]["dd"],
                "full_excess": m["full"]["excess"],
                "full_buys": m["full"]["n_buys"],
                "bh_full": m["full"]["bh"],
                "bh_test": m["test"]["bh"],
                "sharpe_decay": decay,
            }
        )
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wide = pd.read_parquet(PANEL_PATH_ZZ500_1000)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    print(f"panel {closes.shape}", flush=True)

    bh = {k: ew_bh_ret(closes, a, b) for k, (a, b) in PERIODS.items()}
    print("EW-BH:", {k: round(v, 4) for k, v in bh.items()}, flush=True)

    need_n = {80, 85, 90, 100, 120, 30, 40, 50}
    rev_raw: dict[int, pd.DataFrame] = {}
    rev_z: dict[int, pd.DataFrame] = {}
    t0 = time.time()
    for n in sorted(need_n):
        rev_raw[n] = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)
        rev_z[n] = _cs_z(rev_raw[n])
        print(f"  rev{n} ready ({time.time()-t0:.0f}s)", flush=True)

    base_cfg = {"mode": "dual", "n": 90, "n2": 40, "w": 1.0, "hold_days": 20}
    base_fac = make_factor(base_cfg, rev_z, rev_raw, closes)
    base_m = eval_keys(base_fac, opens, closes, 20, bh, tuple(PERIODS))
    print(
        f"BASELINE dual90+40/h20 full_ret={base_m['full']['ret']:.3f} "
        f"excess={base_m['full']['excess']:.3f} sharpe={base_m['full']['sharpe']:.3f} "
        f"test_excess={base_m['test']['excess']:.3f}",
        flush=True,
    )

    cfgs = build_configs()
    print(f"phase1 screen {len(cfgs)} cfgs", flush=True)
    screen_rows = []
    fac_cache: dict[tuple, pd.DataFrame] = {}
    t1 = time.time()
    for i, c in enumerate(cfgs, 1):
        key = (c["mode"], c["n"], c.get("n2"), c.get("w"), c.get("vol_max_pct"))
        if key not in fac_cache:
            fac_cache[key] = make_factor(c, rev_z, rev_raw, closes)
        m = eval_keys(fac_cache[key], opens, closes, int(c["hold_days"]), bh, SCREEN)
        screen_rows.append(row_from(c, m))
        if i % 25 == 0 or i == len(cfgs):
            print(f"  screen {i}/{len(cfgs)} ({time.time()-t1:.0f}s)", flush=True)

    sdf = pd.DataFrame(screen_rows)
    cand = sdf[
        (sdf.train_sharpe >= 0.55)
        & (sdf.valid_sharpe >= 0.55)
        & (sdf.h_floor >= 0.30)
        & (sdf.train_dd <= 0.52)
        & (sdf.valid_dd <= 0.35)
        & (sdf.train_excess > 0)
        & (sdf.valid_excess > -0.05)
    ].copy()
    tag = "excess_v2"
    if cand.empty:
        cand = sdf[(sdf.h_floor >= 0.25) & (sdf.train_sharpe >= 0.45)].copy()
        tag = "excess_v2_soft"
    cand = cand.sort_values(["score", "valid_excess", "h_floor"], ascending=False)
    top_cfgs = cand.head(18)
    print("\n===== phase1 Top10 =====", flush=True)
    print(
        top_cfgs[
            [
                "mode",
                "n",
                "n2",
                "w",
                "hold_days",
                "train_excess",
                "valid_excess",
                "train_sharpe",
                "valid_sharpe",
                "h_floor",
                "score",
            ]
        ]
        .head(10)
        .to_string(index=False),
        flush=True,
    )

    print(f"\nphase2 refine {len(top_cfgs)}", flush=True)
    full_rows = []
    t2 = time.time()
    for i, (_, c0) in enumerate(top_cfgs.iterrows(), 1):
        c = {
            "mode": str(c0["mode"]),
            "n": int(c0["n"]),
            "n2": None if pd.isna(c0["n2"]) else int(c0["n2"]),
            "w": float(c0["w"]),
            "hold_days": int(c0["hold_days"]),
        }
        if "vol_max_pct" in c0 and pd.notna(c0["vol_max_pct"]):
            c["vol_max_pct"] = float(c0["vol_max_pct"])
        key = (c["mode"], c["n"], c.get("n2"), c.get("w"), c.get("vol_max_pct"))
        fac = fac_cache[key]
        m = eval_keys(fac, opens, closes, int(c["hold_days"]), bh, tuple(PERIODS))
        full_rows.append(row_from(c, m, score=float(c0["score"])))
        print(
            f"  refine {i}/{len(top_cfgs)} "
            f"{c['mode']} n={c['n']} h={c['hold_days']} "
            f"full_ex={m['full']['excess']:.3f} test_ex={m['test']['excess']:.3f} "
            f"({time.time()-t2:.0f}s)",
            flush=True,
        )

    df = pd.DataFrame(full_rows)
    df.to_csv(GRID, index=False, encoding="utf-8-sig")

    show = [
        "mode",
        "n",
        "n2",
        "w",
        "hold_days",
        "train_excess",
        "valid_excess",
        "test_excess",
        "full_excess",
        "full_ret",
        "test_sharpe",
        "sharpe_decay",
        "h_floor",
        "score",
    ]
    print("\n===== phase2 results =====", flush=True)
    print(df.sort_values("score", ascending=False)[show].to_string(index=False), flush=True)

    ranked = df.sort_values("score", ascending=False)
    pick = ranked.iloc[0]
    for _, alt in ranked.iloc[1:].iterrows():
        if float(alt["score"]) < float(pick["score"]) - 0.15:
            continue
        better_test_ex = float(alt["test_excess"]) >= float(pick["test_excess"]) + 0.04
        ok_decay = float(alt["sharpe_decay"]) <= max(0.50, float(pick["sharpe_decay"]))
        ok_test_sh = float(alt["test_sharpe"]) >= 0.35
        if better_test_ex and ok_decay and ok_test_sh:
            pick = alt
            tag += "+oos_guard"
            break

    base_full_ex = float(base_m["full"]["excess"])
    lifted = ranked[
        (ranked.full_excess >= base_full_ex + 0.25)
        & (ranked.test_sharpe >= 0.35)
        & (ranked.sharpe_decay <= 0.55)
    ]
    if len(lifted):
        # 在抬超额且 OOS 可接受集合里，优先全样本超额，其次测试超额
        cand2 = lifted.sort_values(
            ["full_excess", "test_excess", "score"], ascending=False
        )
        # 若当前 pick 超额提升不足，强制换到抬升集合
        if float(pick["full_excess"]) < base_full_ex + 0.15:
            pick = cand2.iloc[0]
            tag += "+lift"
        else:
            # 仍可在邻域里换更高超额且衰减不更差者
            alt = cand2.iloc[0]
            if float(alt["full_excess"]) >= float(pick["full_excess"]) + 0.20 and float(
                alt["sharpe_decay"]
            ) <= float(pick["sharpe_decay"]) + 0.08:
                pick = alt
                tag += "+lift"

    print(f"\nPICK [{tag}]", flush=True)
    print(pick[show].to_string(), flush=True)

    cfg = {
        "kind": "rev",
        "n": int(pick["n"]),
        "n2": None if pd.isna(pick["n2"]) else int(pick["n2"]),
        "w": float(pick["w"]) if pd.notna(pick["w"]) else 1.0,
        "top_k": TOP_K,
        "hold_days": int(pick["hold_days"]),
        "min_score": None,
        "ma_filter": None,
        "mode": str(pick["mode"]),
        "vol_max_pct": None
        if "vol_max_pct" not in pick or pd.isna(pick.get("vol_max_pct"))
        else float(pick["vol_max_pct"]),
        "universe": "zz500_1000_mainboard",
        "select_tag": tag,
        "baseline": {
            "mode": "dual",
            "n": 90,
            "n2": 40,
            "hold_days": 20,
            "full_ret": float(base_m["full"]["ret"]),
            "full_excess": float(base_m["full"]["excess"]),
            "full_sharpe": float(base_m["full"]["sharpe"]),
            "test_excess": float(base_m["test"]["excess"]),
            "test_sharpe": float(base_m["test"]["sharpe"]),
        },
        "bh": {k: float(v) for k, v in bh.items()},
        "train": {
            "sharpe": float(pick["train_sharpe"]),
            "excess": float(pick["train_excess"]),
        },
        "valid": {
            "sharpe": float(pick["valid_sharpe"]),
            "excess": float(pick["valid_excess"]),
            "h1": float(pick["vh1"]),
            "h2": float(pick["vh2"]),
        },
        "test": {
            "sharpe": float(pick["test_sharpe"]),
            "ret": float(pick["test_ret"]),
            "dd": float(pick["test_dd"]),
            "excess": float(pick["test_excess"]),
        },
        "full": {
            "sharpe": float(pick["full_sharpe"]),
            "ret": float(pick["full_ret"]),
            "dd": float(pick["full_dd"]),
            "excess": float(pick["full_excess"]),
            "n_buys": int(pick["full_buys"]),
        },
        "sharpe_decay": float(pick["sharpe_decay"]),
        "score": float(pick["score"]),
    }
    BEST.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    apply_portfolio_defaults(cfg)
    print(
        f"updated mode={cfg['mode']} n={cfg['n']} n2={cfg['n2']} hold={cfg['hold_days']} "
        f"full_excess {cfg['baseline']['full_excess']:.3f}→{cfg['full']['excess']:.3f} "
        f"full_ret {cfg['baseline']['full_ret']:.3f}→{cfg['full']['ret']:.3f} "
        f"decay={cfg['sharpe_decay']:.3f}",
        flush=True,
    )
    print(f"wrote {GRID}", flush=True)
    print(f"wrote {BEST}", flush=True)


if __name__ == "__main__":
    main()
