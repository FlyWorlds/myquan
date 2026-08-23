"""策略五 · 正式默认 dual Top3：输出最近信号日选股。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

logging.disable(logging.CRITICAL)

from backtest import zz1000_momentum_select as zz  # noqa: E402
from backtest.mine_zz1000_momentum import factor_matrix  # noqa: E402
from strategy.strategies._unreg_s5.portfolio import PORTFOLIO_DEFAULTS as d  # noqa: E402

OUT = Path(__file__).resolve().parent


def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def main() -> None:
    cfg = dict(d)
    univ = zz.load_zz500_1000_mainboard()
    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = zz.load_panel_matrices(
        univ["symbol"].tolist(),
        warm_start=str(cfg["warm_start"]),
        end=pd.Timestamp.today().strftime("%Y%m%d"),
        refresh=False,
        panel_path=zz.PANEL_PATH_ZZ500_1000,
    )
    r1 = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n"]))
    r2 = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n2"]))
    factor = _cs_z(r1) + _cs_z(r2)
    picks = zz.daily_topk(factor, int(cfg["top_k"]))
    dates = sorted(picks.keys())

    print(f"panel_last={closes.index[-1]}")
    print(f"signal_days={len(dates)}")

    recent_rows: list[dict] = []
    for sig in dates[-10:]:
        idx = closes.index.get_loc(sig)
        trade = closes.index[idx + 1] if idx + 1 < len(closes.index) else None
        syms = picks[sig]
        names = [name_map.get(s, s) for s in syms]
        scores = [float(factor.loc[sig, s]) for s in syms]
        sig_s = pd.Timestamp(sig).strftime("%Y-%m-%d")
        trade_s = pd.Timestamp(trade).strftime("%Y-%m-%d") if trade is not None else ""
        recent_rows.append(
            {
                "signal_date": sig_s,
                "trade_date": trade_s,
                "picks": ",".join(syms),
                "pick_names": ",".join(names),
                "scores": ",".join(f"{x:.4f}" for x in scores),
            }
        )
        trade_show = trade_s or "T+1待定"
        detail = ", ".join(
            f"{n}({s[-6:]}) {sc:.4f}" for n, s, sc in zip(names, syms, scores)
        )
        print(f"{sig_s} -> {trade_show}: {detail}")

    latest = dates[-1]
    syms = picks[latest]
    idx = closes.index.get_loc(latest)
    trade = closes.index[idx + 1] if idx + 1 < len(closes.index) else None
    sig_s = pd.Timestamp(latest).strftime("%Y-%m-%d")
    trade_s = pd.Timestamp(trade).strftime("%Y-%m-%d") if trade is not None else "下一交易日"

    lines = [
        f"交易日: {trade_s} 开盘买入（信号日 {sig_s} 收盘）",
        f"因子: dual rev n={cfg['n']}+{cfg['n2']} | 每日Top{cfg['top_k']} | 持有{cfg['hold_days']}日",
        f"池: 中证500+1000主板 | 有效{closes.shape[1]}只",
        "",
    ]
    detail_rows: list[dict] = []
    for i, s in enumerate(syms, 1):
        code = s[-6:]
        name = name_map.get(s, s)
        score = float(factor.loc[latest, s])
        px = float(closes.loc[latest, s])
        lines.append(f"{i}. {code} {name} ({s}) score={score:.4f} 信号收盘={px:.2f}")
        detail_rows.append(
            {
                "rank": i,
                "trade_date": trade_s if trade is not None else "",
                "signal_date": sig_s,
                "symbol": s,
                "code": code,
                "name": name,
                "score": score,
                "signal_close": px,
                "kind": "dual_rev",
                "n": cfg["n"],
                "n2": cfg["n2"],
                "hold_days": cfg["hold_days"],
                "top_k": cfg["top_k"],
            }
        )
    lines.append("")
    lines.append("说明: 策略五正式默认 dual 反转组合；截面打分越高越优先。")

    tag = (
        trade_s.replace("-", "")
        if trade is not None
        else sig_s.replace("-", "") + "_signal"
    )
    txt = OUT / f"picks_{tag}.txt"
    csv = OUT / f"picks_{tag}.csv"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pd.DataFrame(detail_rows).to_csv(csv, index=False, encoding="utf-8-sig")
    pd.DataFrame(recent_rows).to_csv(
        OUT / "daily_topk3_recent.csv", index=False, encoding="utf-8-sig"
    )

    print("---")
    print("\n".join(lines))
    print(f"写入 {txt}")
    print(f"写入 {csv}")


if __name__ == "__main__":
    main()
