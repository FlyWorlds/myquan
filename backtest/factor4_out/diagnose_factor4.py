"""诊断：为何 factor4/dist_hl Top5 截面回测极差。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest import zz1000_momentum_select as zz  # noqa: E402

PANEL = Path(__file__).resolve().parents[1] / "zz1000_momentum_select" / "panel_ohlc.parquet"
OUT = Path(__file__).resolve().parent / "diagnosis.json"
BT_START = "20200102"


def _ic_series(fac: pd.DataFrame, fwd: pd.DataFrame, start: pd.Timestamp) -> pd.Series:
    rows: list[tuple[pd.Timestamp, float]] = []
    for d in fac.index:
        if d < start:
            continue
        if d not in fwd.index:
            continue
        x = fac.loc[d]
        y = fwd.loc[d]
        m = x.notna() & y.notna()
        if int(m.sum()) < 50:
            continue
        ic = float(x[m].corr(y[m], method="spearman"))
        if np.isfinite(ic):
            rows.append((pd.Timestamp(d), ic))
    return pd.Series({d: v for d, v in rows})


def _summ_ic(s: pd.Series, label: str) -> dict:
    arr = s.to_numpy(dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    ir = mean / std if std > 1e-12 else 0.0
    pos = float((arr > 0).mean())
    print(f"{label}: n={len(arr)} IC_mean={mean:.4f} IC_IR={ir:.3f} IC>0={pos:.1%}")
    return {"label": label, "n": len(arr), "IC_mean": mean, "IC_IR": ir, "IC_pos": pos}


def _run(fac: pd.DataFrame, opens, closes, *, top_k: int, hold_days: int, bt_start, label: str, invert: bool):
    picks = zz.daily_topk((-fac) if invert else fac, top_k)
    lab = f"{label} {'Bottom' if invert else 'Top'}{top_k}"
    eq_df, tr_df, stats = zz.simulate(
        factor=fac,
        opens=opens,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=hold_days,
        top_k=top_k,
        initial_cash=1_000_000.0,
        factor_label=lab,
    )
    print(
        f"{lab}: ret={stats['total_return_pct']:.2f}% "
        f"dd={stats['max_drawdown_pct']:.2f}% "
        f"sharpe={stats['sharpe']:.3f} buys={stats['n_buys']}"
    )
    return stats, eq_df, tr_df


def main() -> None:
    wide = pd.read_parquet(PANEL)
    opens, highs, lows, closes = wide["open"], wide["high"], wide["low"], wide["close"]
    print("panel", closes.shape)

    bt_start = pd.Timestamp(BT_START)
    if getattr(closes.index, "tz", None) is not None:
        bt_start = bt_start.tz_localize(closes.index.tz)

    fac_mom = zz.compute_factor(
        opens, highs, lows, closes, kind="dist_hl", n=120, min_score=None, ma_filter=None
    )
    fac_rev = zz.compute_factor(
        opens, highs, lows, closes, kind="rev", n=60, min_score=None, ma_filter=None
    )
    fac_roc = zz.compute_factor(
        opens, highs, lows, closes, kind="roc", n=60, min_score=None, ma_filter=None
    )

    # 次日开盘买入、持有5日开盘卖出的近似远期收益
    fwd = opens.shift(-5) / opens.shift(-1) - 1.0

    ics: list[dict] = []
    yearly: list[dict] = []
    for name, fac in [("dist_hl120", fac_mom), ("roc60", fac_roc), ("rev60", fac_rev)]:
        s = _ic_series(fac, fwd, bt_start)
        ics.append(_summ_ic(s, name))
        years = s.index.tz_convert("Asia/Shanghai").year if getattr(s.index, "tz", None) else s.index.year
        for y, g in s.groupby(years):
            row = _summ_ic(g, f"{name} {y}")
            yearly.append(row)

    sides: list[dict] = []
    trades_meta: dict = {}
    for fac, name in [(fac_mom, "dist_hl120"), (fac_rev, "rev60")]:
        for invert in (False, True):
            st, eq, tr = _run(
                fac, opens, closes, top_k=5, hold_days=5, bt_start=bt_start, label=name, invert=invert
            )
            sides.append(
                {
                    k: st[k]
                    for k in (
                        "factor",
                        "total_return_pct",
                        "max_drawdown_pct",
                        "sharpe",
                        "n_buys",
                        "end_equity",
                    )
                }
            )
            if name == "dist_hl120" and not invert:
                buys = tr[tr.side == "buy"]
                sells = tr[tr.side == "sell"]
                buy_notional = float((buys.shares * buys.price).sum())
                sell_notional = float((sells.shares * sells.price).sum())
                fee_buy = buy_notional * zz.COMMISSION
                fee_sell = sell_notional * (zz.COMMISSION + zz.STAMP)
                slip_drag = (buy_notional + sell_notional) * zz.SLIP
                trades_meta = {
                    "buy_notional_m": buy_notional / 1e6,
                    "sell_notional_m": sell_notional / 1e6,
                    "fee_est": fee_buy + fee_sell,
                    "slip_est": slip_drag,
                    "cost_drag_pct_of_initial": (fee_buy + fee_sell + slip_drag) / 1e6 * 100,
                    "n_days": int(len(eq)),
                    "buys_per_day": float(len(buys) / max(len(eq), 1)),
                }

    picks = zz.daily_topk(fac_mom, 5)
    dates = sorted(d for d in picks if d >= bt_start)
    overlaps = []
    for i in range(1, len(dates)):
        a = set(picks[dates[i - 1]])
        b = set(picks[dates[i]])
        overlaps.append(len(a & b) / 5.0)
    overlap_mean = float(np.mean(overlaps)) if overlaps else 0.0
    print(f"top5 day-overlap mean={overlap_mean:.2%}")
    print("cost", trades_meta)

    OUT.write_text(
        json.dumps(
            {
                "ics": ics,
                "yearly_ics": yearly,
                "sides": sides,
                "overlap_mean": overlap_mean,
                "trades_meta": trades_meta,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
