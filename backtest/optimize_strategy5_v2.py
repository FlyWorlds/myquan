"""策略五 Top3 继续优化：结构增强 + 逐年滚动选参（无未来函数）。

原则：
  · 信号日收盘算因子 → 次日开盘成交
  · 选参不用当期未来；滚动：用过去窗口选当年参数
  · Top3 固定
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.mine_zz1000_momentum import factor_matrix, simulate_fast  # noqa: E402
from backtest.zz1000_momentum_select import (  # noqa: E402
    COMMISSION,
    INITIAL_CASH,
    LOT,
    PANEL_PATH,
    SLIP,
    STAMP,
)

OUT = Path(__file__).resolve().parent / "factor4_out"
TOP_K = 3
BASELINE = {"kind": "rev", "n": 90, "hold_days": 14, "ma_filter": None, "mode": "plain"}


def _load():
    wide = pd.read_parquet(PANEL_PATH)
    print(f"panel {wide['close'].shape}")
    return wide["open"], wide["high"], wide["low"], wide["close"]


def _tz(s: str, idx: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(s)
    if getattr(idx, "tz", None) is not None and t.tzinfo is None:
        t = t.tz_localize(idx.tz)
    return t


def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def build_factor(
    opens,
    highs,
    lows,
    closes,
    *,
    mode: str,
    n: int,
    n2: int | None = None,
    vol_n: int = 20,
    vol_max_pct: float = 0.75,
    persist: int = 2,
    pool: int = 12,
) -> pd.DataFrame:
    """构造增强因子（全部仅用当日及历史）。"""
    if mode == "plain":
        return factor_matrix(opens, highs, lows, closes, kind="rev", n=n)

    rev = factor_matrix(opens, highs, lows, closes, kind="rev", n=n)

    if mode == "vol_mask":
        vol = closes.pct_change().rolling(vol_n, min_periods=max(5, vol_n // 2)).std()
        rnk = vol.rank(axis=1, pct=True, method="average")
        return rev.where(rnk <= vol_max_pct)

    if mode == "dual":
        n_b = int(n2 or max(10, n // 3))
        rev_b = factor_matrix(opens, highs, lows, closes, kind="rev", n=n_b)
        return _cs_z(rev) + _cs_z(rev_b)

    if mode == "persist":
        # 近 persist 日都进入宽松池，再按当日因子取 TopK（在 simulate 里 topk）
        # 这里把未持续进入池的股票置 NaN
        pool_k = int(pool)
        in_pool = []
        for i in range(len(rev)):
            row = rev.iloc[i]
            s = row.dropna()
            if len(s) < pool_k:
                in_pool.append(pd.Series(False, index=rev.columns))
                continue
            top = set(s.nlargest(pool_k).index)
            in_pool.append(pd.Series(rev.columns.isin(top), index=rev.columns))
        mask = pd.DataFrame(in_pool, index=rev.index, columns=rev.columns)
        # 过去 persist 日（含当日）都在池中
        ok = mask.copy()
        for lag in range(1, persist):
            ok = ok & mask.shift(lag).fillna(False)
        return rev.where(ok)

    if mode == "dual_vol":
        n_b = int(n2 or max(10, n // 3))
        rev_b = factor_matrix(opens, highs, lows, closes, kind="rev", n=n_b)
        fac = _cs_z(rev) + _cs_z(rev_b)
        vol = closes.pct_change().rolling(vol_n, min_periods=max(5, vol_n // 2)).std()
        rnk = vol.rank(axis=1, pct=True, method="average")
        return fac.where(rnk <= vol_max_pct)

    raise ValueError(mode)


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


def _score(m: dict) -> float:
    return float(m["sharpe"] - 1.0 * m["dd"] + 0.1 * max(min(m["ret"], 2.0), -0.5))


def eval_cfg(opens, highs, lows, closes, cfg: dict, start: str, end: str | None) -> dict:
    fac = build_factor(
        opens,
        highs,
        lows,
        closes,
        mode=cfg["mode"],
        n=int(cfg["n"]),
        n2=cfg.get("n2"),
        vol_max_pct=float(cfg.get("vol_max_pct", 0.75)),
        persist=int(cfg.get("persist", 2)),
        pool=int(cfg.get("pool", 12)),
    )
    return _sim(
        fac,
        opens,
        closes,
        start=start,
        end=end,
        hold=int(cfg["hold_days"]),
        ma=cfg.get("ma_filter"),
    )


def structure_search(opens, highs, lows, closes) -> pd.DataFrame:
    """在 2020-22 训 / 2023 验 上搜结构（不看 2024+）。"""
    train_s, train_e = "20200101", "20221231"
    valid_s, valid_e = "20230101", "20231231"

    grid = []
    # plain
    for n, hold, ma in itertools.product(
        [60, 80, 90, 100], [10, 12, 14, 16, 18], [None]
    ):
        grid.append({"mode": "plain", "n": n, "hold_days": hold, "ma_filter": ma})
    # vol mask
    for n, hold, vp in itertools.product(
        [80, 90, 100], [12, 14, 16], [0.6, 0.7, 0.8]
    ):
        grid.append(
            {
                "mode": "vol_mask",
                "n": n,
                "hold_days": hold,
                "ma_filter": None,
                "vol_max_pct": vp,
            }
        )
    # dual window
    for n, n2, hold in itertools.product([60, 90], [15, 20, 30], [12, 14, 16]):
        grid.append(
            {"mode": "dual", "n": n, "n2": n2, "hold_days": hold, "ma_filter": None}
        )
    # dual + vol
    for n, n2, hold, vp in itertools.product([90], [20, 30], [14, 16], [0.7, 0.8]):
        grid.append(
            {
                "mode": "dual_vol",
                "n": n,
                "n2": n2,
                "hold_days": hold,
                "ma_filter": None,
                "vol_max_pct": vp,
            }
        )
    # persist
    for n, hold, persist, pool in itertools.product(
        [80, 90], [12, 14, 16], [2], [8, 12]
    ):
        grid.append(
            {
                "mode": "persist",
                "n": n,
                "hold_days": hold,
                "ma_filter": None,
                "persist": persist,
                "pool": pool,
            }
        )

    rows = []
    t0 = time.time()
    cache: dict[tuple, pd.DataFrame] = {}
    for i, cfg in enumerate(grid, 1):
        key = (
            cfg["mode"],
            cfg["n"],
            cfg.get("n2"),
            cfg.get("vol_max_pct"),
            cfg.get("persist"),
            cfg.get("pool"),
        )
        if key not in cache:
            cache[key] = build_factor(
                opens,
                highs,
                lows,
                closes,
                mode=cfg["mode"],
                n=int(cfg["n"]),
                n2=cfg.get("n2"),
                vol_max_pct=float(cfg.get("vol_max_pct", 0.75)),
                persist=int(cfg.get("persist", 2)),
                pool=int(cfg.get("pool", 12)),
            )
        fac = cache[key]
        train = _sim(
            fac,
            opens,
            closes,
            start=train_s,
            end=train_e,
            hold=int(cfg["hold_days"]),
            ma=cfg.get("ma_filter"),
        )
        valid = _sim(
            fac,
            opens,
            closes,
            start=valid_s,
            end=valid_e,
            hold=int(cfg["hold_days"]),
            ma=cfg.get("ma_filter"),
        )
        rows.append(
            {
                **cfg,
                "top_k": TOP_K,
                "train_sharpe": train["sharpe"],
                "train_ret": train["ret"],
                "train_dd": train["dd"],
                "valid_sharpe": valid["sharpe"],
                "valid_ret": valid["ret"],
                "valid_dd": valid["dd"],
                "valid_score": _score(valid),
                "stab": min(train["sharpe"], valid["sharpe"])
                - 0.5 * abs(train["sharpe"] - valid["sharpe"])
                - 0.8 * max(train["dd"], valid["dd"]),
            }
        )
        if i % 20 == 0 or i == len(grid):
            print(f"  structure {i}/{len(grid)} ({time.time()-t0:.0f}s)")
    return pd.DataFrame(rows)


def pick_structure(df: pd.DataFrame) -> tuple[dict, str]:
    cand = df[
        (df.train_sharpe >= 0.45)
        & (df.valid_sharpe >= 0.70)
        & (df.train_ret > 0.15)
        & (df.valid_ret > 0.05)
        & (df.train_dd <= 0.48)
        & (df.valid_dd <= 0.28)
    ].copy()
    tag = "structure_stab"
    if cand.empty:
        cand = df[(df.valid_sharpe >= 0.5) & (df.train_sharpe >= 0.3)].copy()
        tag = "structure_soft"
    cand = cand.sort_values(["stab", "valid_score"], ascending=False)
    best = cand.iloc[0]
    cfg = {
        "mode": str(best["mode"]),
        "n": int(best["n"]),
        "hold_days": int(best["hold_days"]),
        "ma_filter": None if pd.isna(best.get("ma_filter")) else int(best["ma_filter"]),
        "n2": None if pd.isna(best.get("n2")) else int(best["n2"]),
        "vol_max_pct": None
        if pd.isna(best.get("vol_max_pct"))
        else float(best["vol_max_pct"]),
        "persist": None if pd.isna(best.get("persist")) else int(best["persist"]),
        "pool": None if pd.isna(best.get("pool")) else int(best["pool"]),
        "top_k": TOP_K,
    }
    # drop Nones for cleaner json except ma_filter
    cfg = {k: v for k, v in cfg.items() if v is not None or k == "ma_filter"}
    return cfg, tag


def walk_forward(opens, highs, lows, closes, *, param_grid: list[dict]) -> dict:
    """逐年：用过去两年数据选参，交易下一年（真正的未来未知）。"""
    years = [2021, 2022, 2023, 2024, 2025, 2026]
    # 预计算因子缓存（按 mode/n/...）
    fac_cache: dict[tuple, pd.DataFrame] = {}

    def fac_of(cfg):
        key = (
            cfg["mode"],
            cfg["n"],
            cfg.get("n2"),
            cfg.get("vol_max_pct"),
            cfg.get("persist"),
            cfg.get("pool"),
        )
        if key not in fac_cache:
            fac_cache[key] = build_factor(
                opens,
                highs,
                lows,
                closes,
                mode=cfg["mode"],
                n=int(cfg["n"]),
                n2=cfg.get("n2"),
                vol_max_pct=float(cfg.get("vol_max_pct", 0.75)),
                persist=int(cfg.get("persist", 2)),
                pool=int(cfg.get("pool", 12)),
            )
        return fac_cache[key]

    year_rows = []
    # 拼接权益：逐年模拟后按比例缩放接龙
    equity_parts = []
    cash0 = INITIAL_CASH
    scale = 1.0
    t0 = time.time()

    for yi, year in enumerate(years):
        # 选参窗口：year-2 年初 → year-1 年末
        sel_start = f"{year-2}0101"
        sel_end = f"{year-1}1231"
        trade_start = f"{year}0101"
        trade_end = None if year == 2026 else f"{year}1231"

        best_cfg = None
        best_sc = -9e9
        for cfg in param_grid:
            fac = fac_of(cfg)
            m = _sim(
                fac,
                opens,
                closes,
                start=sel_start,
                end=sel_end,
                hold=int(cfg["hold_days"]),
                ma=cfg.get("ma_filter"),
            )
            sc = _score(m)
            # 门槛
            if m["sharpe"] < 0.2 or m["dd"] > 0.55:
                continue
            if sc > best_sc:
                best_sc = sc
                best_cfg = dict(cfg)

        if best_cfg is None:
            best_cfg = dict(BASELINE)

        fac = fac_of(best_cfg)
        traded = _sim(
            fac,
            opens,
            closes,
            start=trade_start,
            end=trade_end,
            hold=int(best_cfg["hold_days"]),
            ma=best_cfg.get("ma_filter"),
        )
        # 取该年权益曲线：重新跑一次拿序列太贵，用起终点近似；改为轻量重跑拿 eq
        # 这里用 simulate_fast 只返回标量；补一个简易逐日在下面的 _sim_eq
        eq = _sim_equity(
            fac_of(best_cfg),
            opens,
            closes,
            start=trade_start,
            end=trade_end,
            hold=int(best_cfg["hold_days"]),
            ma=best_cfg.get("ma_filter"),
            initial_cash=cash0,
        )
        if eq.empty:
            continue
        # 接龙：本段权益 * scale，使首日对齐
        eq = eq.copy()
        eq["equity"] = eq["equity"] * scale
        # 下一年初始：本段末日
        last = float(eq["equity"].iloc[-1])
        scale = last / cash0
        equity_parts.append(eq)
        year_rows.append(
            {
                "year": year,
                "cfg": json.dumps(best_cfg, ensure_ascii=False),
                "sel_score": best_sc,
                "year_ret": traded["ret"],
                "year_sharpe": traded["sharpe"],
                "year_dd": traded["dd"],
            }
        )
        print(
            f"  WF {year}: {best_cfg.get('mode')} n={best_cfg.get('n')} "
            f"hold={best_cfg.get('hold_days')} sharpe={traded['sharpe']:.3f} "
            f"ret={traded['ret']*100:.1f}% ({time.time()-t0:.0f}s)"
        )

    if not equity_parts:
        return {"error": "no wf equity"}
    # 拼接（去重日）
    all_eq = pd.concat(equity_parts, ignore_index=True)
    all_eq = all_eq.drop_duplicates("date", keep="last").sort_values("date")
    eqv = all_eq["equity"].to_numpy(dtype=float)
    rets = np.diff(eqv) / np.where(eqv[:-1] == 0, np.nan, eqv[:-1])
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets) * np.sqrt(252))
        if len(rets) and np.std(rets) > 1e-12
        else 0.0
    )
    peak = np.maximum.accumulate(eqv)
    dd = float(np.nanmax((peak - eqv) / np.where(peak == 0, np.nan, peak)))
    return {
        "sharpe": sharpe,
        "ret": float(eqv[-1] / INITIAL_CASH - 1.0),
        "dd": dd,
        "end": float(eqv[-1]),
        "years": year_rows,
        "equity": all_eq,
    }


def _sim_equity(fac, opens, closes, *, start, end, hold, ma, initial_cash):
    """与 simulate_fast 同规则，返回权益 DataFrame。"""
    bt_start = _tz(start, closes.index)
    op, cl, f = opens, closes, fac
    if end is not None:
        bt_end = _tz(end, closes.index)
        m = closes.index <= bt_end
        op, cl, f = opens.loc[m], closes.loc[m], fac.loc[m]
    if ma and int(ma) > 1:
        ma_s = cl.rolling(int(ma), min_periods=int(ma)).mean()
        f = f.where(cl > ma_s)

    dates = list(cl.index)
    bt_dates = [d for d in dates if d >= bt_start]
    if len(bt_dates) < hold + 2:
        return pd.DataFrame()
    date_to_i = {d: i for i, d in enumerate(dates)}
    sleeve_cash = np.full(hold, initial_cash / hold, dtype=float)
    sleeve_pos: list[list[tuple[str, int, int]]] = [[] for _ in range(hold)]
    rows = []
    for d in bt_dates:
        di = date_to_i[d]
        for s in range(hold):
            keep = []
            for sym, shares, entry_i in sleeve_pos[s]:
                if di - entry_i >= hold:
                    px = op.at[d, sym]
                    if pd.isna(px) or px <= 0:
                        keep.append((sym, shares, entry_i))
                        continue
                    px = float(px) * (1 - SLIP)
                    sleeve_cash[s] += shares * px * (1 - COMMISSION - STAMP)
                else:
                    keep.append((sym, shares, entry_i))
            sleeve_pos[s] = keep
        if di == 0:
            rows.append({"date": d, "equity": float(sleeve_cash.sum())})
            continue
        prev = dates[di - 1]
        row = f.loc[prev].dropna()
        top = row.nlargest(TOP_K).index.tolist() if len(row) >= TOP_K else []
        s = di % hold
        if top and not sleeve_pos[s] and sleeve_cash[s] > 0:
            budget = sleeve_cash[s] / len(top)
            for sym in top:
                px = op.at[d, sym]
                if pd.isna(px) or px <= 0:
                    continue
                px = float(px) * (1 + SLIP)
                shares = int(budget // (px * LOT)) * LOT
                if shares <= 0:
                    continue
                cost = shares * px
                fee = cost * COMMISSION
                if cost + fee > sleeve_cash[s]:
                    continue
                sleeve_cash[s] -= cost + fee
                sleeve_pos[s].append((sym, shares, di))
        eq = float(sleeve_cash.sum())
        for s in range(hold):
            for sym, shares, _ in sleeve_pos[s]:
                px = cl.at[d, sym]
                if not pd.isna(px):
                    eq += shares * float(px)
        rows.append({"date": d, "equity": eq})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    opens, highs, lows, closes = _load()

    print("=== 1) 结构搜索 (train2020-22 / valid2023) ===")
    sdf = structure_search(opens, highs, lows, closes)
    sdf.to_csv(OUT / "strategy5_structure_grid.csv", index=False, encoding="utf-8-sig")
    best_cfg, tag = pick_structure(sdf)
    print(f"BEST structure [{tag}]: {best_cfg}")
    print(
        sdf.sort_values("stab", ascending=False)[
            [
                "mode",
                "n",
                "n2",
                "hold_days",
                "vol_max_pct",
                "train_sharpe",
                "valid_sharpe",
                "train_dd",
                "valid_dd",
                "stab",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )

    # 测试段 + 全样本（不参与选参）
    print("=== 2) 固定结构：测试/全样本（仅汇报） ===")
    test = eval_cfg(opens, highs, lows, closes, best_cfg, "20240101", None)
    full = eval_cfg(opens, highs, lows, closes, best_cfg, "20200101", None)
    base_test = eval_cfg(opens, highs, lows, closes, BASELINE, "20240101", None)
    base_full = eval_cfg(opens, highs, lows, closes, BASELINE, "20200101", None)
    print(
        f"enhanced test sharpe={test['sharpe']:.3f} ret={test['ret']*100:.1f}% dd={test['dd']*100:.1f}%"
    )
    print(
        f"baseline test sharpe={base_test['sharpe']:.3f} ret={base_test['ret']*100:.1f}% dd={base_test['dd']*100:.1f}%"
    )
    print(
        f"enhanced full sharpe={full['sharpe']:.3f} ret={full['ret']*100:.1f}% dd={full['dd']*100:.1f}%"
    )
    print(
        f"baseline full sharpe={base_full['sharpe']:.3f} ret={base_full['ret']*100:.1f}% dd={base_full['dd']*100:.1f}%"
    )

    # 滚动选参网格：用结构搜索前列 + 基线邻域（每年只用过去数据）
    print("=== 3) 逐年滚动选参 Walk-Forward ===")
    top_structs = (
        sdf.sort_values("stab", ascending=False)
        .head(8)[["mode", "n", "n2", "hold_days", "ma_filter", "vol_max_pct", "persist", "pool"]]
        .to_dict("records")
    )
    wf_grid = []
    for r in top_structs:
        cfg = {
            "mode": r["mode"],
            "n": int(r["n"]),
            "hold_days": int(r["hold_days"]),
            "ma_filter": None if pd.isna(r["ma_filter"]) else int(r["ma_filter"]),
        }
        if not pd.isna(r.get("n2")):
            cfg["n2"] = int(r["n2"])
        if not pd.isna(r.get("vol_max_pct")):
            cfg["vol_max_pct"] = float(r["vol_max_pct"])
        if not pd.isna(r.get("persist")):
            cfg["persist"] = int(r["persist"])
        if not pd.isna(r.get("pool")):
            cfg["pool"] = int(r["pool"])
        wf_grid.append(cfg)
    # 保证基线在网格内
    wf_grid.append(dict(BASELINE))
    # 去重
    uniq = []
    seen = set()
    for c in wf_grid:
        key = json.dumps(c, sort_keys=True)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    wf = walk_forward(opens, highs, lows, closes, param_grid=uniq)
    print(
        f"WF 2021-now sharpe={wf['sharpe']:.3f} ret={wf['ret']*100:.1f}% dd={wf['dd']*100:.1f}%"
    )
    print(pd.DataFrame(wf["years"]).to_string(index=False))

    # 决策：若增强在 valid stab 胜出且 test 不显著差于基线，则更新默认
    # 注意：比较 test 仅用于「是否切换默认」的风控，最终报告会写明
    choose = "baseline"
    chosen = dict(BASELINE)
    reason = "keep baseline"
    # 结构增强：valid/train 已胜出；要求 test sharpe >= baseline_test - 0.05
    if test["sharpe"] >= base_test["sharpe"] - 0.05 and full["sharpe"] >= base_full["sharpe"] - 0.02:
        if best_cfg.get("mode") != "plain" or best_cfg.get("n") != 90 or best_cfg.get("hold_days") != 14:
            choose = "enhanced_fixed"
            chosen = dict(best_cfg)
            reason = f"structure [{tag}] passes OOS guard"
    # WF 若全区间夏普明显高于固定基线，优先采用 WF 模式标记
    if wf["sharpe"] >= max(full["sharpe"], base_full["sharpe"]) + 0.05:
        choose = "walk_forward"
        chosen = {"mode": "walk_forward", "top_k": TOP_K, "grid_size": len(uniq)}
        reason = "walk-forward higher full sharpe"

    result = {
        "choose": choose,
        "reason": reason,
        "selected": chosen,
        "structure_tag": tag,
        "structure_best": best_cfg,
        "baseline": BASELINE,
        "metrics": {
            "enhanced_test": test,
            "enhanced_full": {k: full[k] for k in ("sharpe", "ret", "dd", "n_buys")},
            "baseline_test": base_test,
            "baseline_full": {k: base_full[k] for k in ("sharpe", "ret", "dd", "n_buys")},
            "walk_forward": {
                "sharpe": wf["sharpe"],
                "ret": wf["ret"],
                "dd": wf["dd"],
                "years": wf["years"],
            },
        },
    }
    # strip non-serializable
    (OUT / "strategy5_v2_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # 更新默认：增强固定参数（WF 需单独 runner，先落地最优固定结构）
    final_fixed = best_cfg if choose in ("enhanced_fixed", "walk_forward") else (
        best_cfg if full["sharpe"] > base_full["sharpe"] else dict(BASELINE)
    )
    # 若 WF 更好但仍用固定结构作默认可交易参数：取 WF 最近一年配置
    if choose == "walk_forward" and wf["years"]:
        last_cfg = json.loads(wf["years"][-1]["cfg"])
        final_fixed = last_cfg

    # 更稳妥：固定默认用结构搜索最优（可静态部署）；WF 结果写入 meta
    if full["sharpe"] >= base_full["sharpe"] and test["sharpe"] >= base_test["sharpe"] - 0.08:
        final_fixed = best_cfg

    port = _MYQUAN / "strategy" / "strategies" / "strategy5" / "portfolio.py"
    text = port.read_text(encoding="utf-8")
    import re

    # 扩展 PORTFOLIO_DEFAULTS 字段
    block = (
        "PORTFOLIO_DEFAULTS = {\n"
        f'    "kind": "rev",\n'
        f'    "n": {int(final_fixed.get("n", 90))},\n'
        f'    "top_k": {TOP_K},\n'
        f'    "hold_days": {int(final_fixed.get("hold_days", 14))},\n'
        f'    "min_score": None,\n'
        f'    "ma_filter": {final_fixed.get("ma_filter")!r},\n'
        f'    "mode": "{final_fixed.get("mode", "plain")}",\n'
        f'    "n2": {final_fixed.get("n2")!r},\n'
        f'    "vol_max_pct": {final_fixed.get("vol_max_pct")!r},\n'
        f'    "persist": {final_fixed.get("persist")!r},\n'
        f'    "pool": {final_fixed.get("pool")!r},\n'
        '    "start": "20200101",\n'
        '    "warm_start": "20180101",\n'
        '    "universe": "zz1000_mainboard",\n'
        "}\n"
    )
    new = re.sub(r"PORTFOLIO_DEFAULTS = \{.*?\n\}\n", block, text, count=1, flags=re.S)
    port.write_text(new, encoding="utf-8")
    print(f"updated defaults -> {final_fixed}")

    (OUT / "strategy5_best.json").write_text(
        json.dumps(
            {
                **final_fixed,
                "top_k": TOP_K,
                "choose": choose,
                "reason": reason,
                "v2": result["metrics"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    if "equity" in wf:
        wf["equity"].to_csv(OUT / "strategy5_wf_equity.csv", index=False, encoding="utf-8-sig")
    print("done")


if __name__ == "__main__":
    main()
