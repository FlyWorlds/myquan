"""从日线 parquet 重建 strategy3_first_board/bars/*.npz，并重跑组合。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from strategy.strategies.strategy3.first_board import (  # noqa: E402
    OUT,
    UNIV_CACHE,
    limit_ratio,
    load_zz1000,
    run_first_board_promotion_backtest,
)

def export_npz(symbol: str, code: str) -> bool:
    p = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return False
    d = pd.read_parquet(p)
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[d["date"] >= pd.Timestamp("2019-01-01")].reset_index(drop=True)
    if len(d) < 40:
        return False
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    prev = np.roll(c, 1)
    prev[0] = np.nan
    lim = limit_ratio(code)
    out = OUT / "bars" / f"{symbol}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        dates=np.array([str(x.date()) for x in d["date"]]),
        open=o,
        high=h,
        low=l,
        close=c,
        prev_close=prev,
        lim=np.array([lim]),
    )
    return True


def main() -> None:
    univ = load_zz1000()
    ok = 0
    for _, r in univ.iterrows():
        if export_npz(str(r.symbol).lower(), str(r.code).zfill(6)):
            ok += 1
        if ok and ok % 100 == 0:
            print(f"npz {ok}")
    print(f"exported {ok}/{len(univ)} npz -> {OUT / 'bars'}")
    sample = next((OUT / "bars").glob("*.npz"))
    dates = pd.to_datetime(np.load(sample)["dates"])
    print(f"sample {sample.name} {dates.min().date()} -> {dates.max().date()}")
    run_first_board_promotion_backtest(
        start="20200101",
        end="20260831",
        entry_pcts=(0.025, 0.03),
        pool_mode="first_board",
        rebuild_signals=True,
    )


if __name__ == "__main__":
    main()
