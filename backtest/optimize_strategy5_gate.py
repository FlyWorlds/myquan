"""在 Top3 基线上试：市场波动门控 / 离散度门控（无未来函数）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.mine_zz1000_momentum import factor_matrix  # noqa: E402
from backtest.optimize_strategy5_v2 import TOP_K, _sim_equity, _tz  # noqa: E402
from backtest.zz1000_momentum_select import (  # noqa: E402
    COMMISSION,
    INITIAL_CASH,
    LOT,
    PANEL_PATH,
    SLIP,
    STAMP,
)

OUT = Path(__file__).resolve().parent / "factor4_out"


def metrics_from_eq(eq: pd.Series, initial: float = INITIAL_CASH) -> dict:
    v = eq.to_numpy(dtype=float)
    rets = np.diff(v) / np.where(v[:-1] == 0, np.nan, v[:-1])
    rets = rets[np.isfinite(rets)]
    sharpe = (
        float(np.mean(rets) / np.std(rets) * np.sqrt(252))
        if len(rets) and np.std(rets) > 1e-12
        else 0.0
    )
    peak = np.maximum.accumulate(v)
    dd = float(np.nanmax((peak - v) / np.where(peak == 0, np.nan, peak)))
    return {"sharpe": sharpe, "ret": float(v[-1] / initial - 1.0), "dd": dd, "end": float(v[-1])}


def simulate_gated(
    fac: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    start: str,
    end: str | None,
    hold: int,
    allow_buy: pd.Series,
    initial_cash: float = INITIAL_CASH,
) -> tuple[pd.DataFrame, dict]:
    """allow_buy: 信号日索引上的 bool（用信号日已知信息决定次日是否开仓）。"""
    bt_start = _tz(start, closes.index)
    op, cl, f = opens, closes, fac
    if end is not None:
        bt_end = _tz(end, closes.index)
        m = closes.index <= bt_end
        op, cl, f = opens.loc[m], closes.loc[m], fac.loc[m]
        allow_buy = allow_buy.reindex(f.index)

    dates = list(cl.index)
    bt_dates = [d for d in dates if d >= bt_start]
    date_to_i = {d: i for i, d in enumerate(dates)}
    sleeve_cash = np.full(hold, initial_cash / hold, dtype=float)
    sleeve_pos: list[list[tuple[str, int, int]]] = [[] for _ in range(hold)]
    rows = []
    n_buys = 0
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
        gated = bool(allow_buy.get(prev, True)) if prev in allow_buy.index else True
        row = f.loc[prev].dropna()
        top = row.nlargest(TOP_K).index.tolist() if len(row) >= TOP_K else []
        s = di % hold
        if gated and top and not sleeve_pos[s] and sleeve_cash[s] > 0:
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
                n_buys += 1

        eq = float(sleeve_cash.sum())
        for s in range(hold):
            for sym, shares, _ in sleeve_pos[s]:
                px = cl.at[d, sym]
                if not pd.isna(px):
                    eq += shares * float(px)
        rows.append({"date": d, "equity": eq})
    eq_df = pd.DataFrame(rows)
    m = metrics_from_eq(eq_df.set_index("date")["equity"])
    m["n_buys"] = n_buys
    return eq_df, m


def main() -> None:
    wide = pd.read_parquet(PANEL_PATH)
    opens, closes = wide["open"], wide["close"]
    fac = factor_matrix(opens, wide["high"], wide["low"], closes, kind="rev", n=90)
    hold = 14

    # 市场等权收益波动（仅历史）
    mkt_ret = closes.pct_change().mean(axis=1)
    mkt_vol20 = mkt_ret.rolling(20, min_periods=10).std() * np.sqrt(252)
    # 截面离散度：日收益截面标准差
    disp = closes.pct_change().std(axis=1)
    disp_ma = disp.rolling(60, min_periods=20).mean()

    gates = {
        "always": pd.Series(True, index=closes.index),
        "vol<0.30": mkt_vol20 < 0.30,
        "vol<0.25": mkt_vol20 < 0.25,
        "vol<0.22": mkt_vol20 < 0.22,
        "vol_pct<0.8": mkt_vol20.rank(pct=True) < 0.80,  # wrong - uses full sample!
    }
    # 修正：用滚动分位，避免全样本偷看
    vol_roll_q = mkt_vol20.rolling(252, min_periods=60).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    gates["vol_rollq<0.85"] = vol_roll_q < 0.85
    gates["vol_rollq<0.70"] = vol_roll_q < 0.70
    gates["disp>ma"] = disp > disp_ma  # 有机会时才做反转
    gates["vol<0.25 & disp>ma"] = (mkt_vol20 < 0.25) & (disp > disp_ma)

    # 去掉偷看的全样本 rank
    del gates["vol_pct<0.8"]

    rows = []
    for name, gate in gates.items():
        gate = gate.fillna(False)
        for start, end, tag in [
            ("20200101", "20221231", "train"),
            ("20230101", "20231231", "valid"),
            ("20240101", None, "test"),
            ("20200101", None, "full"),
        ]:
            _eq, m = simulate_gated(
                fac, opens, closes, start=start, end=end, hold=hold, allow_buy=gate
            )
            rows.append({"gate": name, "period": tag, **m})
            print(f"{name:22s} {tag:5s} sharpe={m['sharpe']:.3f} ret={m['ret']*100:6.1f}% dd={m['dd']*100:5.1f}% buys={m['n_buys']}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "strategy5_gate_grid.csv", index=False, encoding="utf-8-sig")

    # 选参：只用 train+valid
    piv = df.pivot(index="gate", columns="period")
    score = []
    for g in df["gate"].unique():
        tr = df[(df.gate == g) & (df.period == "train")].iloc[0]
        va = df[(df.gate == g) & (df.period == "valid")].iloc[0]
        te = df[(df.gate == g) & (df.period == "test")].iloc[0]
        fu = df[(df.gate == g) & (df.period == "full")].iloc[0]
        sc = min(tr.sharpe, va.sharpe) - 0.5 * abs(tr.sharpe - va.sharpe) - 0.7 * max(tr.dd, va.dd)
        score.append(
            {
                "gate": g,
                "stab": sc,
                "train_sharpe": tr.sharpe,
                "valid_sharpe": va.sharpe,
                "test_sharpe": te.sharpe,
                "full_sharpe": fu.sharpe,
                "full_ret": fu.ret,
                "full_dd": fu.dd,
            }
        )
    scdf = pd.DataFrame(score).sort_values("stab", ascending=False)
    print("\n=== rank by train/valid stability ===")
    print(scdf.to_string(index=False))
    best = scdf.iloc[0].to_dict()
    (OUT / "strategy5_gate_best.json").write_text(
        json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("BEST gate", best)


if __name__ == "__main__":
    main()
