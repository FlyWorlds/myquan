"""因子7：行业 ETF 普通动量 + 改进残差动量。

月末使用当时可见数据打分，下一交易日开盘等权持有 Top3 至下次月度调仓。
本模块仅用于历史研究与模拟，不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from strategy.etf_combo_momentum import (
    COMMISSION,
    INITIAL_CASH,
    LOT,
    SLIP,
    STAMP,
    _panel_from_dailies,
    load_etf_dailies,
)


@dataclass
class IndustryMomentumResult:
    stats: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    picks: pd.DataFrame
    yearly: pd.DataFrame
    name_map: dict[str, str]
    config: dict[str, Any]


# 可交易代理池；研究者可通过 universe 参数替换成自己的行业指数/ETF 映射。
DEFAULT_UNIVERSE: tuple[tuple[str, str], ...] = (
    ("sh515000", "科技ETF"),
    ("sh512480", "半导体ETF"),
    ("sh512880", "证券ETF"),
    ("sh512800", "银行ETF"),
    ("sh512070", "非银ETF"),
    ("sh512170", "医疗ETF"),
    ("sh512010", "医药ETF"),
    ("sz159992", "创新药ETF"),
    ("sh512660", "军工ETF"),
    ("sh512400", "有色金属ETF"),
    ("sh515220", "煤炭ETF"),
    ("sz159930", "能源ETF"),
    ("sh512690", "酒ETF"),
    ("sz159928", "消费ETF"),
    ("sh512200", "房地产ETF"),
)

# 全球股、债、商品的 A 股场内代理。PCA 输入并不限定为这组资产。
DEFAULT_COMMON_UNIVERSE: tuple[tuple[str, str], ...] = (
    ("sh510300", "沪深300ETF"),
    ("sh510500", "中证500ETF"),
    ("sz159915", "创业板ETF"),
    ("sh513100", "纳指ETF"),
    ("sh513500", "标普500ETF"),
    ("sh511010", "国债ETF"),
    ("sh511260", "十年国债ETF"),
    ("sh511220", "城投债ETF"),
    ("sh518880", "黄金ETF"),
    ("sz159980", "有色期货ETF"),
    ("sz159981", "能源化工ETF"),
)

DEFAULT_PARAMS: dict[str, Any] = {
    "momentum_months": 12,
    "pca_window_months": 100,
    "n_components": 6,
    "top_k": 3,
    "ordinary_weight": 0.5,
    "residual_weight": 0.5,
    "start": "20240206",
    "warm_start": "20140101",
}


def industry_residual_momentum_rules_text(
    params: Mapping[str, Any] | None = None,
    universe: Sequence[tuple[str, str]] | None = None,
) -> str:
    p = {**DEFAULT_PARAMS, **dict(params or {})}
    names = "、".join(name for _, name in (universe or DEFAULT_UNIVERSE))
    return f"""\
================================================================================
  因子7 · 行业ETF双动量
================================================================================
  · 行业池：{names}
  · 普通动量：最近 {p['momentum_months']} 个月月度对数收益之和
  · 改进残差动量：用最近 {p['pca_window_months']} 个月股债商品同比收益做 PCA，
    保留 {p['n_components']} 个共同因子；行业月收益对共同因子做无截距回归，
    最近 {p['momentum_months']} 个月残差求和，并反转其中日波动最高月份的残差
  · 合成：两因子先做行业截面百分位，再按
    {p['ordinary_weight']:.0%}/{p['residual_weight']:.0%} 加权
  · 组合：每月末选 Top{p['top_k']}，下一交易日开盘等权调仓，整月满仓
  · 时点：所有特征只使用信号月末及以前数据，不使用未来信息
  · 成本：佣金 {COMMISSION}、滑点 {SLIP}、ETF 印花税 {STAMP}
================================================================================
""".strip()


def _month_end_prices(closes: pd.DataFrame) -> pd.DataFrame:
    c = closes.astype(float).sort_index()
    c.index = pd.to_datetime(c.index)
    return c.groupby(c.index.to_period("M")).last()


def monthly_log_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """由日收盘生成月频对数收益，索引为 Period[M]。"""
    prices = _month_end_prices(closes)
    return np.log(prices / prices.shift(1))


def monthly_daily_volatility(closes: pd.DataFrame) -> pd.DataFrame:
    """每只行业 ETF 在各自然月内的日对数收益标准差。"""
    c = closes.astype(float).sort_index()
    c.index = pd.to_datetime(c.index)
    daily = np.log(c / c.shift(1))
    return daily.groupby(daily.index.to_period("M")).std(ddof=1)


def ordinary_momentum(
    industry_monthly_returns: pd.DataFrame, *, lookback: int = 12
) -> pd.DataFrame:
    return industry_monthly_returns.rolling(
        int(lookback), min_periods=int(lookback)
    ).sum()


def _pca_loadings(annual_returns: np.ndarray, n_components: int) -> np.ndarray | None:
    """用窗口内同比收益估计稳定 PCA 权重。"""
    x = np.asarray(annual_returns, dtype=float)
    if x.ndim != 2 or x.shape[0] < 2 or x.shape[1] < 1 or not np.isfinite(x).all():
        return None
    x = x - x.mean(axis=0, keepdims=True)
    scale = x.std(axis=0, ddof=1)
    keep = np.isfinite(scale) & (scale > 1e-12)
    if not keep.any():
        return None
    z = x[:, keep] / scale[keep]
    try:
        _, _, vt = np.linalg.svd(z, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    k = min(int(n_components), vt.shape[0], int(keep.sum()))
    if k < 1:
        return None
    loadings = np.zeros((x.shape[1], k), dtype=float)
    loadings[keep, :] = vt[:k].T / scale[keep, None]
    return loadings


def rolling_residual_returns(
    industry_monthly_returns: pd.DataFrame,
    common_monthly_returns: pd.DataFrame,
    *,
    pca_window: int = 100,
    n_components: int = 6,
) -> pd.DataFrame:
    """逐月、点时滚动估计行业残差月收益。

    PCA 权重由共同资产的 12 个月同比对数收益估计，再作用于同一窗口的
    1 个月环比对数收益。行业收益对这些共同因子做无截距最小二乘。
    """
    industry, common = industry_monthly_returns.align(
        common_monthly_returns, join="inner", axis=0
    )
    industry = industry.sort_index()
    common = common.sort_index()
    annual_common = common.rolling(12, min_periods=12).sum()
    out = pd.DataFrame(np.nan, index=industry.index, columns=industry.columns)
    window = int(pca_window)

    for end_i in range(window - 1, len(industry)):
        sl = slice(end_i - window + 1, end_i + 1)
        ann = annual_common.iloc[sl]
        mon = common.iloc[sl]
        valid_common = ann.notna().all(axis=0) & mon.notna().all(axis=0)
        if int(valid_common.sum()) < 2:
            continue
        loadings = _pca_loadings(
            ann.loc[:, valid_common].to_numpy(), int(n_components)
        )
        if loadings is None:
            continue
        factors = mon.loc[:, valid_common].to_numpy() @ loadings
        valid_rows = np.isfinite(factors).all(axis=1)
        if int(valid_rows.sum()) <= factors.shape[1]:
            continue
        x = factors[valid_rows]
        for symbol in industry.columns:
            y_all = industry[symbol].iloc[sl].to_numpy(dtype=float)
            rows = valid_rows & np.isfinite(y_all)
            if int(rows.sum()) <= factors.shape[1]:
                continue
            try:
                beta, *_ = np.linalg.lstsq(factors[rows], y_all[rows], rcond=None)
            except np.linalg.LinAlgError:
                continue
            if np.isfinite(y_all[-1]) and np.isfinite(factors[-1]).all():
                out.iat[end_i, out.columns.get_loc(symbol)] = (
                    y_all[-1] - factors[-1] @ beta
                )
    return out


def improved_residual_momentum(
    residual_returns: pd.DataFrame,
    monthly_volatility: pd.DataFrame,
    *,
    lookback: int = 12,
) -> pd.DataFrame:
    """残差总和减去两倍“最吵月份”残差，即把该月残差符号反转。"""
    residual, volatility = residual_returns.align(
        monthly_volatility, join="left", axis=0
    )
    out = pd.DataFrame(np.nan, index=residual.index, columns=residual.columns)
    n = int(lookback)
    for end_i in range(n - 1, len(residual)):
        sl = slice(end_i - n + 1, end_i + 1)
        eps = residual.iloc[sl]
        vol = volatility.iloc[sl]
        for symbol in residual.columns:
            e = eps[symbol]
            v = vol[symbol]
            if e.notna().sum() != n or v.notna().sum() != n:
                continue
            loudest_month = v.idxmax()
            out.at[residual.index[end_i], symbol] = (
                float(e.sum()) - 2.0 * float(e.loc[loudest_month])
            )
    return out


def composite_scores(
    ordinary: pd.DataFrame,
    improved_residual: pd.DataFrame,
    *,
    ordinary_weight: float = 0.5,
    residual_weight: float = 0.5,
) -> pd.DataFrame:
    """两路因子各自在当月行业截面排百分位后合成。"""
    ordinary, improved_residual = ordinary.align(
        improved_residual, join="inner", axis=0
    )
    ordinary, improved_residual = ordinary.align(
        improved_residual, join="inner", axis=1
    )
    ordinary_pct = ordinary.rank(axis=1, pct=True, method="average")
    residual_pct = improved_residual.rank(axis=1, pct=True, method="average")
    return (
        float(ordinary_weight) * ordinary_pct
        + float(residual_weight) * residual_pct
    )


def build_factor_panels(
    industry_closes: pd.DataFrame,
    common_closes: pd.DataFrame,
    *,
    momentum_months: int = 12,
    pca_window_months: int = 100,
    n_components: int = 6,
    ordinary_weight: float = 0.5,
    residual_weight: float = 0.5,
) -> dict[str, pd.DataFrame]:
    industry_monthly = monthly_log_returns(industry_closes)
    common_monthly = monthly_log_returns(common_closes)
    volatility = monthly_daily_volatility(industry_closes)
    ordinary = ordinary_momentum(industry_monthly, lookback=momentum_months)
    residual_returns = rolling_residual_returns(
        industry_monthly,
        common_monthly,
        pca_window=pca_window_months,
        n_components=n_components,
    )
    improved = improved_residual_momentum(
        residual_returns, volatility, lookback=momentum_months
    )
    composite = composite_scores(
        ordinary,
        improved,
        ordinary_weight=ordinary_weight,
        residual_weight=residual_weight,
    )
    return {
        "industry_monthly_returns": industry_monthly,
        "common_monthly_returns": common_monthly,
        "monthly_volatility": volatility,
        "ordinary_momentum": ordinary,
        "residual_returns": residual_returns,
        "improved_residual_momentum": improved,
        "composite_score": composite,
    }


def monthly_topk_targets(
    composite_score: pd.DataFrame, *, top_k: int = 3
) -> dict[pd.Timestamp, list[str]]:
    """把月频分数映射到真实月末交易日信号。"""
    out: dict[pd.Timestamp, list[str]] = {}
    k = max(int(top_k), 1)
    for period, row in composite_score.iterrows():
        valid = row.dropna().sort_values(ascending=False)
        if valid.empty:
            continue
        out[pd.Period(period, freq="M").to_timestamp("M").normalize()] = [
            str(symbol) for symbol in valid.index[:k]
        ]
    return out


def _target_for_month(
    targets: Mapping[pd.Timestamp, list[str]], period: pd.Period
) -> list[str] | None:
    same_month = [
        (pd.Timestamp(signal_day), symbols)
        for signal_day, symbols in targets.items()
        if pd.Timestamp(signal_day).to_period("M") == period
    ]
    return list(max(same_month, key=lambda item: item[0])[1]) if same_month else None


def simulate_monthly_topk(
    *,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: Mapping[pd.Timestamp, list[str]],
    bt_start: pd.Timestamp,
    initial_cash: float = INITIAL_CASH,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """月末信号在下一根日线开盘执行，组合等权且始终满仓。"""
    dates = list(pd.DatetimeIndex(closes.index).sort_values())
    cash = float(initial_cash)
    positions: dict[str, int] = {}
    last_prices: dict[str, float] = {}
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    last_signal_month: pd.Period | None = None

    def equity_at(day: pd.Timestamp) -> float:
        value = cash
        for symbol, shares in positions.items():
            px = closes.at[day, symbol] if symbol in closes.columns else np.nan
            if pd.notna(px):
                last_prices[symbol] = float(px)
            value += shares * last_prices.get(symbol, 0.0)
        return value

    for i, day in enumerate(dates):
        if day < bt_start:
            continue
        if i > 0:
            prev = dates[i - 1]
            previous_bar_month = prev.to_period("M")
            current_month = day.to_period("M")
            is_first_bar_of_month = current_month != previous_bar_month
            signal_month = (
                previous_bar_month
                if is_first_bar_of_month
                else current_month - 1
            )
            should_initialize = last_signal_month is None
            desired = (
                _target_for_month(targets, signal_month)
                if is_first_bar_of_month or should_initialize
                else None
            )
            if desired is not None and signal_month != last_signal_month:
                for symbol, shares in list(positions.items()):
                    if symbol not in opens.columns or pd.isna(opens.at[day, symbol]):
                        continue
                    px = float(opens.at[day, symbol]) * (1.0 - SLIP)
                    proceeds = shares * px
                    cash += proceeds * (1.0 - COMMISSION - STAMP)
                    trade_rows.append(
                        {
                            "date": day,
                            "symbol": symbol,
                            "side": "sell",
                            "shares": shares,
                            "price": px,
                            "reason": "monthly_rebalance",
                        }
                    )
                    del positions[symbol]
                available = [
                    s
                    for s in desired
                    if s in opens.columns
                    and pd.notna(opens.at[day, s])
                    and float(opens.at[day, s]) > 0
                ]
                if available:
                    budget = cash / (len(available) * (1.0 + COMMISSION))
                    for symbol in available:
                        px = float(opens.at[day, symbol]) * (1.0 + SLIP)
                        shares = int(budget // (px * LOT)) * LOT
                        if shares <= 0:
                            continue
                        cost = shares * px
                        fee = cost * COMMISSION
                        if cost + fee > cash:
                            continue
                        cash -= cost + fee
                        positions[symbol] = shares
                        last_prices[symbol] = px
                        trade_rows.append(
                            {
                                "date": day,
                                "symbol": symbol,
                                "side": "buy",
                                "shares": shares,
                                "price": px,
                                "reason": "monthly_top3",
                            }
                        )
                last_signal_month = signal_month
        equity_rows.append(
            {
                "date": day,
                "equity": equity_at(day),
                "cash": cash,
                "holdings": ",".join(sorted(positions)),
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    end_equity = (
        float(equity["equity"].iloc[-1]) if not equity.empty else float(initial_cash)
    )
    stats = {
        "label": "strategy8/industry_etf_dual_momentum",
        "start": str(bt_start.date()),
        "end": str(equity["date"].iloc[-1].date()) if not equity.empty else "",
        "total_return_pct": (end_equity / float(initial_cash) - 1.0) * 100.0,
        "final_equity": end_equity,
        "n_buys": int((trades["side"] == "buy").sum()) if not trades.empty else 0,
        "n_sells": int((trades["side"] == "sell").sum()) if not trades.empty else 0,
    }
    return equity, trades, stats


def run_industry_residual_momentum(
    *,
    start: str | None = None,
    end: str | None = None,
    warm_start: str | None = None,
    momentum_months: int | None = None,
    pca_window_months: int | None = None,
    n_components: int | None = None,
    top_k: int | None = None,
    ordinary_weight: float | None = None,
    residual_weight: float | None = None,
    universe: Sequence[tuple[str, str]] | None = None,
    common_universe: Sequence[tuple[str, str]] | None = None,
    dailies: Mapping[str, pd.DataFrame] | None = None,
    common_dailies: Mapping[str, pd.DataFrame] | None = None,
    refresh: bool = False,
    initial_cash: float = INITIAL_CASH,
    verbose: bool = True,
) -> IndustryMomentumResult:
    cfg = dict(DEFAULT_PARAMS)
    for key, value in {
        "start": start,
        "warm_start": warm_start,
        "momentum_months": momentum_months,
        "pca_window_months": pca_window_months,
        "n_components": n_components,
        "top_k": top_k,
        "ordinary_weight": ordinary_weight,
        "residual_weight": residual_weight,
    }.items():
        if value is not None:
            cfg[key] = value
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    industry_universe = tuple(universe or DEFAULT_UNIVERSE)
    common_assets = tuple(common_universe or DEFAULT_COMMON_UNIVERSE)
    industry_symbols = [code for code, _ in industry_universe]
    common_symbols = [code for code, _ in common_assets]
    if verbose:
        print(
            f"[策略8 行业ETF双动量] Top{cfg['top_k']} 月频 "
            f"PCA={cfg['pca_window_months']}m/{cfg['n_components']}PC "
            f"{cfg['start']}→{end}"
        )
    loaded = (
        dict(dailies)
        if dailies is not None
        else load_etf_dailies(
            industry_symbols,
            start=str(cfg["warm_start"]),
            end=end,
            refresh=refresh,
        )
    )
    loaded_common = (
        dict(common_dailies)
        if common_dailies is not None
        else load_etf_dailies(
            common_symbols,
            start=str(cfg["warm_start"]),
            end=end,
            refresh=refresh,
        )
    )
    opens = _panel_from_dailies(loaded, "open")
    closes = _panel_from_dailies(loaded, "close")
    common_closes = _panel_from_dailies(loaded_common, "close")
    if opens.empty or closes.empty or common_closes.empty:
        raise RuntimeError("因子7：行业或共同资产 ETF 面板为空")
    panels = build_factor_panels(
        closes,
        common_closes,
        momentum_months=int(cfg["momentum_months"]),
        pca_window_months=int(cfg["pca_window_months"]),
        n_components=int(cfg["n_components"]),
        ordinary_weight=float(cfg["ordinary_weight"]),
        residual_weight=float(cfg["residual_weight"]),
    )
    targets = monthly_topk_targets(
        panels["composite_score"], top_k=int(cfg["top_k"])
    )
    bt_start = pd.Timestamp(str(cfg["start"]))
    equity, trades, stats = simulate_monthly_topk(
        opens=opens,
        closes=closes,
        targets=targets,
        bt_start=bt_start,
        initial_cash=float(initial_cash),
    )
    if equity.empty:
        raise RuntimeError("因子7：无权益曲线")
    eq = equity.set_index("date")["equity"].astype(float)
    running_max = eq.cummax()
    stats["max_drawdown_pct"] = float((eq / running_max - 1.0).min() * -100.0)
    days = max((eq.index[-1] - eq.index[0]).days, 1)
    stats["annual_return_pct"] = (
        (float(eq.iloc[-1] / eq.iloc[0])) ** (365.25 / days) - 1.0
    ) * 100.0
    yearly_rows = []
    for year, group in eq.groupby(eq.index.year):
        previous = eq[eq.index < group.index[0]]
        base = float(previous.iloc[-1]) if len(previous) else float(initial_cash)
        yearly_rows.append(
            {
                "year": int(year),
                "return_pct": float(group.iloc[-1] / base - 1.0) * 100.0,
            }
        )
    picks = pd.DataFrame(
        [
            {
                "signal_date": signal_day,
                "target": ",".join(symbols),
            }
            for signal_day, symbols in targets.items()
            if signal_day >= bt_start
        ]
    )
    cfg["common_universe"] = common_symbols
    return IndustryMomentumResult(
        stats=stats,
        equity=equity,
        trades=trades,
        picks=picks,
        yearly=pd.DataFrame(yearly_rows),
        name_map={code: name for code, name in industry_universe},
        config=cfg,
    )


def factor7_signal(**kwargs: Any) -> dict[str, Any]:
    industry_closes = kwargs.get("closes")
    common_closes = kwargs.get("common_closes")
    if industry_closes is None or common_closes is None:
        return {
            "factor_id": "factor7",
            "action": "industry_etf_dual_momentum",
            "universe": [code for code, _ in DEFAULT_UNIVERSE],
            "common_universe": [code for code, _ in DEFAULT_COMMON_UNIVERSE],
            "params": dict(DEFAULT_PARAMS),
        }
    panels = build_factor_panels(
        industry_closes,
        common_closes,
        momentum_months=int(kwargs.get("momentum_months", 12)),
        pca_window_months=int(kwargs.get("pca_window_months", 100)),
        n_components=int(kwargs.get("n_components", 6)),
        ordinary_weight=float(kwargs.get("ordinary_weight", 0.5)),
        residual_weight=float(kwargs.get("residual_weight", 0.5)),
    )
    score = panels["composite_score"]
    valid = score.dropna(how="all")
    if valid.empty:
        return {
            "factor_id": "factor7",
            "action": "industry_etf_dual_momentum",
            "asof": None,
            "target": [],
            "scores": {},
        }
    last_period = valid.index[-1]
    row = valid.loc[last_period].dropna().sort_values(ascending=False)
    top_k = int(kwargs.get("top_k", 3))
    return {
        "factor_id": "factor7",
        "action": "industry_etf_dual_momentum",
        "asof": str(pd.Period(last_period, freq="M")),
        "target": [str(symbol) for symbol in row.index[:top_k]],
        "scores": {str(symbol): float(value) for symbol, value in row.items()},
    }


__all__ = [
    "DEFAULT_UNIVERSE",
    "DEFAULT_COMMON_UNIVERSE",
    "DEFAULT_PARAMS",
    "IndustryMomentumResult",
    "monthly_log_returns",
    "monthly_daily_volatility",
    "ordinary_momentum",
    "rolling_residual_returns",
    "improved_residual_momentum",
    "composite_scores",
    "build_factor_panels",
    "monthly_topk_targets",
    "simulate_monthly_topk",
    "run_industry_residual_momentum",
    "factor7_signal",
    "industry_residual_momentum_rules_text",
]
