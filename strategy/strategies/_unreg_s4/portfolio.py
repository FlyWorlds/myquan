"""策略四 · 因子1 滚动12月评分 Top3 池 × 池内反转选股。

默认（挖参较优）:
  score_mode=roll12, pool_n=3, pool 内 rev(20) 选 Top1, 持有 10 日
  收盘信号 → 次日开盘；袖套轮动
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]

PORTFOLIO_DEFAULTS: dict[str, Any] = {
    "score_mode": "roll12",
    "pool_n": 3,
    "kind": "rev",
    "n": 20,
    "top_k": 1,
    "hold_days": 10,
    "select_mode": "pool",  # pool | blend
    "w_f1": 0.0,
    "w_mom": 1.0,
    "start": "20200201",
    "warm_start": "20190101",
    "universe": "zz1000_mainboard",
    "initial_cash": 1_000_000.0,
}


@dataclass
class Strategy4Result:
    stats: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    picks: pd.DataFrame
    pool: pd.DataFrame
    yearly: pd.DataFrame
    config: dict[str, Any]


def portfolio_config(**overrides: Any) -> dict[str, Any]:
    cfg = dict(PORTFOLIO_DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def _build_trade_pool(score_mode: str, pool_n: int, have: set[str]):
    from backtest.top20_momentum_dig import build_monthly_top_pool

    trade_pool, score_by_trade = build_monthly_top_pool(score_mode, int(pool_n))
    trade_pool = {m: [s for s in syms if s in have] for m, syms in trade_pool.items()}
    score_by_trade = {
        m: {s: v for s, v in mp.items() if s in have} for m, mp in score_by_trade.items()
    }
    return trade_pool, score_by_trade


def run_strategy4_portfolio(**overrides: Any) -> Strategy4Result:
    """回测：滚动12月（可覆盖）因子1 TopN 池 × 池内动量/反转。"""
    from backtest.top20_momentum_dig import (
        blend_factor,
        build_panel,
        mask_factor_to_pool,
    )
    from backtest.top3_momentum_dig import mask_factor_to_pool_fast
    from backtest.zz1000_momentum_select import (
        INITIAL_CASH,
        compute_factor,
        load_zz1000_mainboard,
        simulate,
    )

    cfg = portfolio_config(**overrides)
    verbose = bool(overrides.get("verbose", True))
    refresh = bool(overrides.get("refresh", False))

    univ = load_zz1000_mainboard()
    symbols = univ["symbol"].tolist()
    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = build_panel(symbols, refresh=refresh)
    have = set(closes.columns)

    trade_pool, score_by_trade = _build_trade_pool(
        str(cfg["score_mode"]), int(cfg["pool_n"]), have
    )
    pool_rows = []
    for m, syms in sorted(trade_pool.items()):
        for i, s in enumerate(syms, 1):
            pool_rows.append(
                {
                    "trade_month": m,
                    "rank": i,
                    "symbol": s,
                    "name": name_map.get(s, ""),
                    "score": score_by_trade.get(m, {}).get(s),
                }
            )
    pool_df = pd.DataFrame(pool_rows)

    fac = compute_factor(
        opens,
        highs,
        lows,
        closes,
        kind=str(cfg["kind"]),
        n=int(cfg["n"]),
        min_score=None,
        ma_filter=None,
    )
    select_mode = str(cfg.get("select_mode") or "pool")
    if select_mode == "blend":
        use = blend_factor(
            fac,
            score_by_trade,
            trade_pool,
            float(cfg.get("w_f1") or 0.4),
            float(cfg.get("w_mom") or 0.6),
        )
    else:
        try:
            use = mask_factor_to_pool_fast(fac, trade_pool)
        except Exception:
            use = mask_factor_to_pool(fac, trade_pool)

    top_k = int(cfg["top_k"])
    hold_days = int(cfg["hold_days"])
    picks: dict[pd.Timestamp, list[str]] = {}
    pick_rows = []
    for dt_idx, row in use.iterrows():
        s = row.dropna()
        if len(s) < top_k:
            continue
        chosen = s.nlargest(top_k).index.tolist()
        picks[pd.Timestamp(dt_idx)] = chosen
        pick_rows.append(
            {
                "signal_date": pd.Timestamp(dt_idx),
                "picks": ",".join(chosen),
                "pick_names": ",".join(name_map.get(x, x) for x in chosen),
                "scores": ",".join(f"{float(s[x]):.4f}" for x in chosen),
            }
        )

    bt_start = pd.Timestamp(str(cfg["start"]))
    if closes.index.tz is not None and bt_start.tzinfo is None:
        bt_start = bt_start.tz_localize(closes.index.tz)
    cash = float(cfg.get("initial_cash") or INITIAL_CASH)

    if verbose:
        print(
            f"[策略四] score={cfg['score_mode']} pool_n={cfg['pool_n']} "
            f"{select_mode} {cfg['kind']}(n={cfg['n']}) Top{top_k} "
            f"持有{hold_days}日  {cfg['start']}→ 池月数={len(trade_pool)}"
        )

    eq, tr, summary = simulate(
        factor=use,
        opens=opens,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=hold_days,
        top_k=top_k,
        initial_cash=cash,
        factor_label=(
            f"s4/{cfg['score_mode']}/top{cfg['pool_n']}/"
            f"{cfg['kind']}{cfg['n']}_k{top_k}_h{hold_days}"
        ),
    )
    if eq is None or eq.empty:
        raise RuntimeError("策略四：无权益曲线")

    e = eq.set_index("date")["equity"].astype(float).sort_index()
    yearly_rows = []
    years = e.index.year if e.index.tz is None else e.index.tz_convert(None).year
    for y, g in e.groupby(years):
        prev = e[e.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else cash
        yearly_rows.append(
            {
                "year": int(y),
                "return_pct": float(g.iloc[-1] / base - 1) * 100,
            }
        )
    picks_df = pd.DataFrame(pick_rows)
    stats = dict(summary)
    stats["score_mode"] = cfg["score_mode"]
    stats["pool_n"] = cfg["pool_n"]
    return Strategy4Result(
        stats=stats,
        equity=eq,
        trades=tr if isinstance(tr, pd.DataFrame) else pd.DataFrame(),
        picks=picks_df,
        pool=pool_df,
        yearly=pd.DataFrame(yearly_rows),
        config=cfg,
    )


def current_picks(**overrides: Any) -> pd.DataFrame:
    """最新信号日：roll12 Top3 池内反转选股。"""
    from backtest.top20_momentum_dig import build_panel
    from backtest.top3_momentum_dig import mask_factor_to_pool_fast
    from backtest.zz1000_momentum_select import compute_factor, load_zz1000_mainboard

    cfg = portfolio_config(**overrides)
    univ = load_zz1000_mainboard()
    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = build_panel(univ["symbol"].tolist(), refresh=False)
    have = set(closes.columns)
    trade_pool, _ = _build_trade_pool(str(cfg["score_mode"]), int(cfg["pool_n"]), have)

    fac = compute_factor(
        opens, highs, lows, closes,
        kind=str(cfg["kind"]), n=int(cfg["n"]), min_score=None, ma_filter=None,
    )
    use = mask_factor_to_pool_fast(fac, trade_pool)
    dt = use.index.max()
    month = str(pd.Timestamp(dt).tz_localize(None).to_period("M")) if getattr(dt, "tzinfo", None) else str(pd.Timestamp(dt).to_period("M"))
    # 兼容 tz
    try:
        month = str(pd.Timestamp(dt).tz_convert("Asia/Shanghai").tz_localize(None).to_period("M"))
    except Exception:
        month = str(pd.Timestamp(str(dt)[:10]).to_period("M"))

    pool = trade_pool.get(month, [])
    row = use.loc[dt].dropna()
    top_k = int(cfg["top_k"])
    chosen = row.nlargest(top_k) if len(row) >= top_k else row.sort_values(ascending=False)

    rows = []
    for rank, (sym, score) in enumerate(chosen.items(), 1):
        rows.append(
            {
                "signal_date": str(pd.Timestamp(dt).date()) if not hasattr(dt, "date") else str(pd.Timestamp(dt).date()),
                "trade_month": month,
                "pool": ",".join(pool),
                "rank": rank,
                "symbol": sym,
                "name": name_map.get(sym, ""),
                "score": float(score),
                "close": float(closes.at[dt, sym]) if sym in closes.columns else np.nan,
            }
        )
    # also list full pool for the month
    for i, sym in enumerate(pool, 1):
        if any(r["symbol"] == sym for r in rows):
            continue
        rows.append(
            {
                "signal_date": str(pd.Timestamp(dt).date()),
                "trade_month": month,
                "pool": ",".join(pool),
                "rank": None,
                "symbol": sym,
                "name": name_map.get(sym, ""),
                "score": float(row[sym]) if sym in row.index else np.nan,
                "close": float(closes.at[dt, sym]) if sym in closes.columns else np.nan,
                "in_trade_pick": False,
            }
        )
    for r in rows:
        r.setdefault("in_trade_pick", r.get("rank") is not None)
    return pd.DataFrame(rows)
