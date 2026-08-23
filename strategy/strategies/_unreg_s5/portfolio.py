"""策略五 · 动量因子组合：中证500+1000主板截面回测。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

# 挖参后写入；未挖参前用诊断验证过的反转默认（同口径优于 dist_hl Top5）
PORTFOLIO_DEFAULTS = {
    "kind": "rev",
    "n": 90,
    "top_k": 3,
    "hold_days": 20,
    "min_score": None,
    "ma_filter": None,
    "mode": "dual",
    "n2": 40,
    "w": 1.0,
    "vol_max_pct": None,
    "persist": None,
    "pool": None,
    "start": "20200101",
    "warm_start": "20180101",
    "universe": "zz500_1000_mainboard",
}


@dataclass
class PortfolioResult:
    stats: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    picks: pd.DataFrame
    yearly: pd.DataFrame
    name_map: dict[str, str]
    config: dict[str, Any]


def portfolio_config(**overrides: Any) -> dict[str, Any]:
    cfg = dict(PORTFOLIO_DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def run_momentum_portfolio(
    *,
    kind: str | None = None,
    n: int | None = None,
    top_k: int | None = None,
    hold_days: int | None = None,
    min_score: float | None = None,
    ma_filter: int | None = None,
    start: str | None = None,
    end: str | None = None,
    warm_start: str | None = None,
    universe: str | None = None,
    refresh: bool = False,
    initial_cash: float | None = None,
    verbose: bool = True,
) -> PortfolioResult:
    """中证500+1000（或指定池）主板 · 收盘截面 TopK → 次日开盘 · 袖套持有。"""
    from backtest import zz1000_momentum_select as zz
    from strategy.dd_alert import max_drawdown_pct

    cfg = portfolio_config(
        kind=kind,
        n=n,
        top_k=top_k,
        hold_days=hold_days,
        ma_filter=ma_filter,
        start=start,
        warm_start=warm_start,
        universe=universe,
    )
    # min_score 允许显式 None（不过滤）
    if min_score is not None or "min_score" in PORTFOLIO_DEFAULTS:
        cfg["min_score"] = (
            min_score if min_score is not None else PORTFOLIO_DEFAULTS.get("min_score")
        )

    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    cash = float(initial_cash if initial_cash is not None else zz.INITIAL_CASH)
    univ_key = str(cfg.get("universe") or "zz500_1000_mainboard")

    if verbose:
        print(
            f"[动量因子组合] pool={univ_key} mode={cfg.get('mode','plain')} "
            f"kind={cfg['kind']} n={cfg['n']} n2={cfg.get('n2')} "
            f"top_k={cfg['top_k']} hold_days={cfg['hold_days']} "
            f"ma={cfg['ma_filter']} min_score={cfg['min_score']}  "
            f"{cfg['start']}→{end}"
        )

    if univ_key in ("zz500_1000_mainboard", "zz500_1000", "500+1000"):
        univ = zz.load_zz500_1000_mainboard()
        panel_path = zz.PANEL_PATH_ZZ500_1000
    elif univ_key in ("zz1000_mainboard", "zz1000"):
        univ = zz.load_zz1000_mainboard()
        panel_path = zz.PANEL_PATH
    elif univ_key in ("zz500_mainboard", "zz500"):
        univ = zz.load_zz500_mainboard()
        panel_path = zz.OUT_DIR / "panel_ohlc_zz500.parquet"
    else:
        raise ValueError(f"未知股票池: {univ_key}")

    name_map = dict(zip(univ["symbol"], univ["name"]))
    opens, highs, lows, closes = zz.load_panel_matrices(
        univ["symbol"].tolist(),
        warm_start=str(cfg["warm_start"]),
        end=end,
        refresh=refresh,
        panel_path=panel_path,
    )
    if verbose:
        print(f"面板 close={closes.shape}")

    mode = str(cfg.get("mode") or "plain")
    if mode in ("dual", "dual_w") and cfg.get("n2"):
        from backtest.mine_zz1000_momentum import factor_matrix
        import numpy as np

        r1 = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n"]))
        r2 = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n2"]))

        def _cs_z(df: pd.DataFrame) -> pd.DataFrame:
            mu = df.mean(axis=1)
            sd = df.std(axis=1).replace(0, np.nan)
            return df.sub(mu, axis=0).div(sd, axis=0)

        w = float(cfg.get("w") or 1.0)
        factor = _cs_z(r1) + w * _cs_z(r2)
        label = (
            f"portfolio/{univ_key}/dual{{n={cfg['n']}+{cfg['n2']}*w{w:g},"
            f"top={cfg['top_k']},hold={cfg['hold_days']}}}"
        )
    elif mode == "vol_mask":
        from backtest.mine_zz1000_momentum import factor_matrix

        rev = factor_matrix(opens, highs, lows, closes, kind="rev", n=int(cfg["n"]))
        vol = closes.pct_change().rolling(20, min_periods=10).std()
        rnk = vol.rank(axis=1, pct=True, method="average")
        vmax = float(cfg.get("vol_max_pct") or 0.75)
        factor = rev.where(rnk <= vmax)
        label = (
            f"portfolio/{univ_key}/vol_mask{{n={cfg['n']},vmax={vmax},"
            f"top={cfg['top_k']},hold={cfg['hold_days']}}}"
        )
    else:
        factor = zz.compute_factor(
            opens,
            highs,
            lows,
            closes,
            kind=str(cfg["kind"]),
            n=int(cfg["n"]),
            min_score=cfg["min_score"],
            ma_filter=cfg["ma_filter"],
        )
        label = (
            f"portfolio/{univ_key}/{cfg['kind']}{{n={cfg['n']},top={cfg['top_k']},"
            f"hold={cfg['hold_days']},ma={cfg['ma_filter']}}}"
        )
    picks = zz.daily_topk(factor, int(cfg["top_k"]))
    bt_start = pd.Timestamp(str(cfg["start"]))
    idx_tz = getattr(factor.index, "tz", None)
    if idx_tz is not None and bt_start.tzinfo is None:
        bt_start = bt_start.tz_localize(idx_tz)

    eq_df, tr_df, stats = zz.simulate(
        factor=factor,
        opens=opens,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=int(cfg["hold_days"]),
        top_k=int(cfg["top_k"]),
        initial_cash=cash,
        factor_label=label,
    )
    if eq_df is None or eq_df.empty:
        raise RuntimeError("动量因子组合：无权益曲线")

    eq = eq_df.set_index("date")["equity"].astype(float).sort_index()
    yearly_rows: list[dict[str, Any]] = []
    years = (
        eq.index.tz_convert("Asia/Shanghai").year
        if getattr(eq.index, "tz", None)
        else eq.index.year
    )
    for y, g in eq.groupby(years):
        prev = eq[eq.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else cash
        yearly_rows.append(
            {
                "year": int(y),
                "return_pct": float(g.iloc[-1] / base - 1.0) * 100,
                "max_dd_pct": max_drawdown_pct(g) * 100 if len(g) > 1 else 0.0,
            }
        )
    yearly = pd.DataFrame(yearly_rows)
    pk = stats.get("picks")
    if not isinstance(pk, pd.DataFrame):
        pk = pd.DataFrame()

    return PortfolioResult(
        stats=stats,
        equity=eq_df,
        trades=tr_df if isinstance(tr_df, pd.DataFrame) else pd.DataFrame(),
        picks=pk,
        yearly=yearly,
        name_map=name_map,
        config=cfg,
    )


def apply_best_config(best: dict[str, Any]) -> None:
    """运行时覆盖默认（挖参脚本写入后再 import 也可直接改 PORTFOLIO_DEFAULTS）。"""
    for k in ("kind", "n", "top_k", "hold_days", "min_score", "ma_filter"):
        if k in best:
            PORTFOLIO_DEFAULTS[k] = best[k]


__all__ = [
    "PORTFOLIO_DEFAULTS",
    "PortfolioResult",
    "portfolio_config",
    "run_momentum_portfolio",
    "apply_best_config",
]
