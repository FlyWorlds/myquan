"""策略二的日线截面事件回测（30分钟只用于小转大买点）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from strategy.chan.config import DEFAULT_CONFIG, ChanStrategyConfig
from strategy.chan.signals import ChanSignalSnapshot
from strategy.chan.state_machine import ChanStateMachine


ANNUAL_BARS = 244


@dataclass
class ChanBacktestResult:
    stats: dict[str, float]
    equity: pd.DataFrame
    weights: pd.DataFrame
    trades: pd.DataFrame
    picks: pd.DataFrame
    yearly: pd.DataFrame
    config: dict[str, Any]


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    return float((nav / nav.cummax() - 1.0).min())


def _performance(returns: pd.Series, turnover: pd.Series) -> dict[str, float]:
    clean = returns.fillna(0.0)
    nav = (1.0 + clean).cumprod()
    years = max(len(clean) / ANNUAL_BARS, 1.0 / ANNUAL_BARS)
    ann_return = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if len(nav) else 0.0
    ann_vol = float(clean.std(ddof=1) * np.sqrt(ANNUAL_BARS)) if len(clean) > 1 else 0.0
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    mdd = _max_drawdown(nav)
    return {
        "total_return": float(nav.iloc[-1] - 1.0) if len(nav) else 0.0,
        "annual_return": ann_return,
        "annual_volatility": ann_vol,
        "sharpe": float(sharpe),
        "max_drawdown": mdd,
        "calmar": float(ann_return / abs(mdd)) if mdd < 0 else 0.0,
        "annual_turnover": float(turnover.mean() * ANNUAL_BARS),
        "hit_rate": float((clean > 0).mean()),
        "bars": float(len(clean)),
    }


def derive_eligibility(
    panel: pd.DataFrame,
    *,
    candidate_timeout_bars: int = 160,
) -> pd.DataFrame:
    """逐标的运行状态机，返回每根信号K线后的可持仓状态。"""
    if panel.empty:
        return panel.assign(
            eligible_long=pd.Series(dtype=bool),
            chan_action=pd.Series(dtype=str),
            chan_reason=pd.Series(dtype=str),
        )
    data = panel.sort_values(["symbol", "dt"]).copy()
    eligible = np.zeros(len(data), dtype=bool)
    actions = np.empty(len(data), dtype=object)
    reasons = np.empty(len(data), dtype=object)

    def _flag(frame: pd.DataFrame, name: str) -> np.ndarray:
        if name not in frame.columns:
            return np.zeros(len(frame), dtype=bool)
        return frame[name].fillna(False).to_numpy(dtype=bool)

    offset = 0
    for _, group in data.groupby("symbol", sort=False):
        n = len(group)
        machine = ChanStateMachine(candidate_timeout_bars=candidate_timeout_bars)
        dts = pd.to_datetime(group["dt"]).to_numpy()
        buy1 = _flag(group, "buy1")
        buy2 = _flag(group, "buy2")
        buy3 = _flag(group, "buy3")
        sell1 = _flag(group, "sell1")
        sell2 = _flag(group, "sell2")
        sell3 = _flag(group, "sell3")
        limit_up = _flag(group, "limit_up")
        limit_down = _flag(group, "limit_down")
        suspended = _flag(group, "suspended")
        active = False
        entry_exec_date = None
        for i in range(n):
            when = pd.Timestamp(dts[i])
            can_sell = entry_exec_date is None or when.date() > entry_exec_date.date()
            transition = machine.update(
                when,
                ChanSignalSnapshot(
                    buy1=bool(buy1[i]),
                    buy2=bool(buy2[i]),
                    buy3=bool(buy3[i]),
                    sell1=bool(sell1[i]),
                    sell2=bool(sell2[i]),
                    sell3=bool(sell3[i]),
                    limit_up=bool(limit_up[i]),
                    limit_down=bool(limit_down[i]),
                    suspended=bool(suspended[i]),
                ),
                can_sell=can_sell,
            )
            if transition.action == "buy":
                active = True
                if i + 1 < n:
                    entry_exec_date = pd.Timestamp(dts[i + 1])
                    machine.entry_date = entry_exec_date
            elif transition.action == "sell":
                active = False
                entry_exec_date = None
            eligible[offset + i] = active
            actions[offset + i] = transition.action
            reasons[offset + i] = transition.reason
        offset += n
    data["eligible_long"] = eligible
    data["chan_action"] = actions
    data["chan_reason"] = reasons
    return data.sort_values(["dt", "symbol"])


def _apply_limit_constraints(
    weights: pd.DataFrame,
    open_px: pd.DataFrame,
    close_px: pd.DataFrame,
) -> pd.DataFrame:
    """涨停买不进、跌停卖不出：用 t 收盘对照 t+1 开盘近似涨跌停。"""
    aligned_open = open_px.reindex(index=weights.index, columns=weights.columns)
    aligned_close = close_px.reindex(index=weights.index, columns=weights.columns)
    exec_open = aligned_open.shift(-1)
    limit_up = (exec_open >= aligned_close * 1.095).fillna(False).to_numpy()
    limit_down = (exec_open <= aligned_close * 0.905).fillna(False).to_numpy()
    raw = weights.fillna(0.0).to_numpy(dtype=float)
    out = np.zeros_like(raw)
    prev = np.zeros(raw.shape[1], dtype=float)
    for i in range(raw.shape[0]):
        w = raw[i].copy()
        w = np.where((w > prev) & limit_up[i], prev, w)
        w = np.where((w < prev) & limit_down[i], prev, w)
        total = w.sum()
        if total > 0:
            w = w / total
        out[i] = w
        prev = w
    return pd.DataFrame(out, index=weights.index, columns=weights.columns)


def run_chan_backtest(
    panel: pd.DataFrame,
    *,
    factor_column: str | None = None,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    start: str | None = None,
    end: str | None = None,
    fee_rate: float | None = None,
) -> ChanBacktestResult:
    required = {"dt", "symbol", "open", "close", "buy1", "buy2", "sell2", "sell3"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"策略二回测缺少字段: {sorted(missing)}")
    data = panel.copy()
    data["dt"] = pd.to_datetime(data["dt"])
    data = data.sort_values(["symbol", "dt"])
    if start:
        data = data[data["dt"] >= pd.Timestamp(start)]
    if end:
        data = data[data["dt"] <= pd.Timestamp(end) + pd.Timedelta(days=1)]
    if "eligible_long" not in data.columns:
        data = derive_eligibility(
            data, candidate_timeout_bars=config.candidate_timeout_bars
        )
    if data.empty:
        raise ValueError("策略二回测没有可用数据")

    if factor_column and factor_column in data:
        data["_score"] = pd.to_numeric(data[factor_column], errors="coerce")
    else:
        data["_score"] = 0.0
    buy3 = (
        data["buy3"].astype(float)
        if "buy3" in data
        else pd.Series(0.0, index=data.index)
    )
    data["_score"] = data["_score"].fillna(0.0) + buy3 * 0.10

    open_px = data.pivot(index="dt", columns="symbol", values="open").sort_index()
    score = data.pivot(index="dt", columns="symbol", values="_score").reindex(
        index=open_px.index, columns=open_px.columns
    )
    eligible = (
        data.pivot(index="dt", columns="symbol", values="eligible_long")
        .reindex(index=open_px.index, columns=open_px.columns)
        .fillna(False)
    )
    ranks = score.where(eligible).rank(axis=1, ascending=False, method="first")
    selected = ranks.le(int(config.top_k))
    counts = selected.sum(axis=1).replace(0, np.nan)
    weights = selected.astype(float).div(counts, axis=0).fillna(0.0)
    close_px = (
        data.pivot(index="dt", columns="symbol", values="close")
        .reindex(index=open_px.index, columns=open_px.columns)
    )
    weights = _apply_limit_constraints(weights, open_px, close_px)

    # t 日收盘形成的权重，在 t+1 开盘成交，收益为 t+1 开盘到 t+2 开盘。
    forward_open_return = open_px.shift(-2).div(open_px.shift(-1)).sub(1.0)
    gross = (weights * forward_open_return).sum(axis=1, min_count=1).fillna(0.0)
    traded = weights.diff().abs().sum(axis=1).fillna(weights.abs().sum(axis=1))
    fee = float(config.fee_rate if fee_rate is None else fee_rate)
    costs = traded * fee
    net = gross - costs
    nav = float(config.initial_cash) * (1.0 + net).cumprod()
    benchmark = open_px.shift(-2).div(open_px.shift(-1)).sub(1.0).mean(axis=1)
    benchmark_nav = float(config.initial_cash) * (1.0 + benchmark.fillna(0.0)).cumprod()
    equity = pd.DataFrame(
        {
            "dt": net.index,
            "gross_return": gross.values,
            "cost": costs.values,
            "net_return": net.values,
            "equity": nav.values,
            "benchmark_return": benchmark.reindex(net.index).fillna(0.0).values,
            "benchmark_equity": benchmark_nav.reindex(net.index).values,
            "turnover": traded.values,
        }
    )
    stats = _performance(net, traded)
    stats["gross_sharpe"] = _performance(gross, traded)["sharpe"]
    stats["benchmark_return"] = float(benchmark_nav.iloc[-1] / config.initial_cash - 1)

    changes = weights.diff().fillna(weights)
    trade_rows: list[dict[str, Any]] = []
    for when, row in changes.iterrows():
        for symbol, delta in row[row.abs() > 1e-12].items():
            trade_rows.append(
                {
                    "signal_dt": when,
                    "symbol": symbol,
                    "side": "buy" if delta > 0 else "sell",
                    "weight_change": float(delta),
                }
            )
    weight_long = weights.stack().rename("weight")
    weight_long.index.names = ["dt", "symbol"]
    score_long = score.stack().rename("score")
    score_long.index.names = ["dt", "symbol"]
    picks = (
        weight_long.reset_index()
        .query("weight > 0")
        .merge(score_long.reset_index(), on=["dt", "symbol"], how="left")
    )
    yearly_rows = []
    eq_series = equity.set_index("dt")["equity"]
    for year, group in eq_series.groupby(eq_series.index.year):
        before = eq_series[eq_series.index < group.index[0]]
        base = float(before.iloc[-1]) if len(before) else float(config.initial_cash)
        yearly_rows.append(
            {
                "year": int(year),
                "return": float(group.iloc[-1] / base - 1.0),
                "max_drawdown": _max_drawdown(group / base),
            }
        )
    return ChanBacktestResult(
        stats=stats,
        equity=equity,
        weights=weights,
        trades=pd.DataFrame(trade_rows),
        picks=picks,
        yearly=pd.DataFrame(yearly_rows),
        config=config.to_dict() | {"factor_column": factor_column, "fee_rate": fee},
    )


__all__ = [
    "ANNUAL_BARS",
    "ChanBacktestResult",
    "derive_eligibility",
    "run_chan_backtest",
]
