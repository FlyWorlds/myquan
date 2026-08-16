from __future__ import annotations

import os
import time
from datetime import timedelta

import pandas as pd
from scipy import stats

from factor import _date_to_yyyymmdd, _parse_underlying, calculate_factor, load_real_position


def _format_date(value: str) -> str:
    return pd.to_datetime(str(value), format="%Y%m%d").strftime("%Y-%m-%d")


_BATCH = 5          # 每批品种数，避免单次查询超过套餐限额
_BATCH_SLEEP = 2.0  # 批次间隔（秒），避免触发每分钟限频
_RATE_LIMIT_CODE = "500010"
_TOKEN_EXPIRED_CODE = "200004"


def _batched(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _call_with_retry(fn, *args, max_retries: int = 6, base_wait: float = 10.0, **kwargs):
    """调用 fn(*args, **kwargs)，遇到限频/Token过期错误时自动处理后重试。"""
    import panda_data
    from panda_data.exceptions import ServiceError

    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except ServiceError as e:
            err = str(e)
            if _TOKEN_EXPIRED_CODE in err and attempt < max_retries - 1:
                print(f"  [Token过期] 重新登录后重试 (第 {attempt + 1}/{max_retries} 次)...")
                panda_data.init_token()
            elif _RATE_LIMIT_CODE in err and attempt < max_retries - 1:
                wait = base_wait * (2 ** attempt)
                print(f"  [限频] 等待 {wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
                time.sleep(wait)
            else:
                raise
        except (TimeoutError, OSError, ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = base_wait * (2 ** attempt)
                print(f"  [网络超时] {str(e)[:80]} → 等待 {wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
                time.sleep(wait)
            else:
                raise


def load_real_dominant_and_daily(
    underlying_symbols: list[str],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    import panda_data

    start = _date_to_yyyymmdd(start_date)
    end_dt = pd.to_datetime(_date_to_yyyymmdd(end_date), format="%Y%m%d") + timedelta(days=10)
    end_plus = end_dt.strftime("%Y%m%d")

    dominant_chunks = []
    batches = list(_batched(underlying_symbols, _BATCH))
    for i, batch in enumerate(batches):
        print(f"  加载主力合约 batch {i+1}/{len(batches)}: {batch}")
        chunk = _call_with_retry(
            panda_data.get_future_dominant,
            underlying_symbol=batch,
            start_date=start,
            end_date=end_plus,
        )
        if not chunk.empty:
            dominant_chunks.append(chunk)
        if i < len(batches) - 1:
            time.sleep(_BATCH_SLEEP)
    if not dominant_chunks:
        raise ValueError("Panda data 未返回主力合约数据")
    dominant = pd.concat(dominant_chunks, ignore_index=True)

    contracts = sorted(dominant["symbol"].dropna().astype(str).unique().tolist())
    daily_chunks = []
    batches = list(_batched(contracts, _BATCH))
    for i, batch in enumerate(batches):
        print(f"  加载日线数据 batch {i+1}/{len(batches)}: {batch}")
        chunk = _call_with_retry(
            panda_data.get_future_daily,
            symbol=batch,
            start_date=start,
            end_date=end_plus,
            fields=[],
        )
        if not chunk.empty:
            daily_chunks.append(chunk)
        if i < len(batches) - 1:
            time.sleep(_BATCH_SLEEP)
    if not daily_chunks:
        raise ValueError("Panda data 未返回期货日线数据")
    daily = pd.concat(daily_chunks, ignore_index=True)
    return dominant, daily


def build_trend_data(dominant: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    prices = daily[["date", "symbol", "close"]].copy()
    prices["date"] = prices["date"].astype(str).str.replace("-", "", regex=False)
    prices["close"] = pd.to_numeric(prices["close"], errors="raise")
    panel = dom.merge(prices.rename(columns={"symbol": "contract_symbol"}), on=["date", "contract_symbol"], how="inner")
    panel = panel.sort_values(["symbol", "date"]).copy()
    panel["ma20"] = panel.groupby("symbol")["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    panel["ma60"] = panel.groupby("symbol")["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    panel["trade_date"] = panel["date"].map(_format_date)
    return panel.dropna(subset=["ma20", "ma60"])[["trade_date", "symbol", "close", "ma20", "ma60"]]


def build_forward_returns(dominant: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["trade_date"] = dom["date"].map(_format_date)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    dom = dom.sort_values(["symbol", "date"]).reset_index(drop=True)
    dom["next_date"] = dom.groupby("symbol")["date"].shift(-1)

    prices = daily[["date", "symbol", "close"]].copy()
    prices["date"] = prices["date"].astype(str).str.replace("-", "", regex=False)
    prices["close"] = pd.to_numeric(prices["close"], errors="raise")

    current_price = prices.rename(columns={"date": "date", "symbol": "contract_symbol", "close": "close_t"})
    next_price = prices.rename(columns={"date": "next_date", "symbol": "contract_symbol", "close": "close_t1"})
    panel = dom.merge(current_price, on=["date", "contract_symbol"], how="left").merge(
        next_price,
        on=["next_date", "contract_symbol"],
        how="left",
    )
    panel = panel.dropna(subset=["close_t", "close_t1"]).copy()
    panel = panel[panel["close_t"] > 0]
    panel["forward_return"] = panel["close_t1"] / panel["close_t"] - 1
    return panel[["trade_date", "symbol", "contract_symbol", "forward_return"]].reset_index(drop=True)


def build_tradeable_forward_returns(
    dominant: pd.DataFrame,
    daily: pd.DataFrame,
    data_lag: int = 0,
    roll_cost_bps: float = 5.0,
) -> pd.DataFrame:
    """
    Tradeable forward returns with explicit data lag and rollover cost.

    data_lag=0: signal on T predicts T→T+1 (data available T night).
    data_lag=1: signal on T predicts (T+1)→(T+2) (1 extra day lag).
    roll_cost_bps: one-way cost deducted on rollover days (applied twice = round-trip).
    """
    base = build_forward_returns(dominant, daily)
    if base.empty:
        return base

    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["trade_date"] = dom["date"].map(_format_date)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    dom = dom.sort_values(["symbol", "trade_date"])
    dom["prev_contract"] = dom.groupby("symbol")["contract_symbol"].shift(1)
    rollover_days = dom[dom["contract_symbol"] != dom["prev_contract"]].copy()
    rollover_set = set(zip(rollover_days["trade_date"], rollover_days["symbol"]))

    roll_cost = roll_cost_bps / 10000
    result = base.copy()
    result["is_rollover"] = result.apply(
        lambda r: (r["trade_date"], r["symbol"]) in rollover_set, axis=1
    )
    result["forward_return"] = result["forward_return"] - result["is_rollover"] * roll_cost * 2

    if data_lag > 0:
        dates = sorted(result["trade_date"].unique())
        date_to_lag = {d: dates[i - data_lag] if i >= data_lag else None for i, d in enumerate(dates)}
        result["signal_date"] = result["trade_date"].map(date_to_lag)
        result = result.dropna(subset=["signal_date"])
        result = result.rename(columns={"trade_date": "execution_date", "signal_date": "trade_date"})

    return result[["trade_date", "symbol", "contract_symbol", "forward_return"]].reset_index(drop=True)


def _build_horizon_returns(dominant: pd.DataFrame, daily: pd.DataFrame, horizon: int) -> pd.DataFrame:
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["trade_date"] = dom["date"].map(_format_date)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    dom = dom.sort_values(["symbol", "date"]).reset_index(drop=True)
    dom["next_date_h"] = dom.groupby("symbol")["date"].shift(-horizon)

    prices = daily[["date", "symbol", "close"]].copy()
    prices["date"] = prices["date"].astype(str).str.replace("-", "", regex=False)
    prices["close"] = pd.to_numeric(prices["close"], errors="raise")

    cur = prices.rename(columns={"date": "date", "symbol": "contract_symbol", "close": "close_t"})
    nxt = prices.rename(columns={"date": "next_date_h", "symbol": "contract_symbol", "close": "close_th"})
    panel = (
        dom.merge(cur, on=["date", "contract_symbol"], how="left")
        .merge(nxt, on=["next_date_h", "contract_symbol"], how="left")
    )
    panel = panel.dropna(subset=["close_t", "close_th"]).copy()
    panel = panel[panel["close_t"] > 0].copy()
    panel["forward_return"] = panel["close_th"] / panel["close_t"] - 1
    return panel[["trade_date", "symbol", "forward_return"]].reset_index(drop=True)


def bootstrap_ic_ci(
    daily_ic: pd.Series,
    n_bootstrap: int = 500,
    ci: float = 0.95,
) -> tuple[float, float]:
    if len(daily_ic) < 4:
        return (float("nan"), float("nan"))
    s = daily_ic.dropna()
    alpha = (1 - ci) / 2
    means = pd.Series([s.sample(n=len(s), replace=True).mean() for _ in range(n_bootstrap)])
    return (round(float(means.quantile(alpha)), 6), round(float(means.quantile(1 - alpha)), 6))


def calculate_ic_by_horizon(
    factor: pd.DataFrame,
    dominant: pd.DataFrame,
    daily: pd.DataFrame,
    horizons: list[int] | None = None,
    n_bootstrap: int = 200,
) -> dict:
    if horizons is None:
        horizons = [1, 2, 3, 5, 10, 20]
    result = {}
    for h in horizons:
        ret = _build_horizon_returns(dominant, daily, h)
        panel = factor.merge(ret, on=["trade_date", "symbol"], how="inner")
        if panel.empty:
            result[f"{h}D"] = {"IC": None, "RankIC": None, "IC_CI95": None}
            continue
        daily_ic_h = panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()
        daily_ric_h = panel.groupby("trade_date").apply(rank_ic, include_groups=False).dropna()
        ic_mean = round(float(daily_ic_h.mean()), 6) if not daily_ic_h.empty else None
        ric_mean = round(float(daily_ric_h.mean()), 6) if not daily_ric_h.empty else None
        lo, hi = bootstrap_ic_ci(daily_ic_h, n_bootstrap=n_bootstrap)
        result[f"{h}D"] = {
            "IC": ic_mean,
            "RankIC": ric_mean,
            "IC_CI95": f"[{lo:.4f}, {hi:.4f}]" if ic_mean is not None else None,
        }
    return result


def pearson_ic(x: pd.DataFrame) -> float:
    if x["factor_value"].std() == 0 or x["forward_return"].std() == 0:
        return float("nan")
    return float(x["factor_value"].corr(x["forward_return"]))


def rank_ic(x: pd.DataFrame) -> float:
    factor_rank = x["factor_value"].rank(method="average")
    return_rank = x["forward_return"].rank(method="average")
    if factor_rank.std() == 0 or return_rank.std() == 0:
        return float("nan")
    return float(factor_rank.corr(return_rank))


def information_ratio(returns: pd.Series) -> float:
    std = returns.std()
    if returns.empty or not std:
        return 0.0
    return float(returns.mean() / std * (252**0.5))


def annualized_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    cumulative_return = float((1 + returns).prod() - 1)
    years = len(returns) / 252
    if years <= 0:
        return cumulative_return
    return float((1 + cumulative_return) ** (1 / years) - 1)


def count_rollovers(dominant: pd.DataFrame) -> int:
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom = dom.sort_values(["underlying_symbol", "date"])
    changed = dom.groupby("underlying_symbol")["symbol"].apply(lambda s: s.ne(s.shift()).sum() - 1)
    return int(changed.clip(lower=0).sum())


def _turnover(panel: pd.DataFrame) -> float:
    """计算多空双侧平均换手率，无信号侧记为 0。"""
    def side_turnover(daily_sets) -> float:
        if daily_sets.empty:
            return 0.0
        values, previous = [], None
        for current in daily_sets:
            if previous is not None:
                union = current | previous
                values.append(1 - len(current & previous) / len(union) if union else 0.0)
            previous = current
        return float(sum(values) / len(values)) if values else 0.0

    buy_sets = panel[panel["signal"] == "buy"].groupby("trade_date")["symbol"].apply(set)
    sell_sets = panel[panel["signal"] == "sell"].groupby("trade_date")["symbol"].apply(set)
    buy_to = side_turnover(buy_sets)
    sell_to = side_turnover(sell_sets)
    active_sides = (1 if buy_to > 0 else 0) + (1 if sell_to > 0 else 0)
    if active_sides == 0:
        return 0.0
    return round((buy_to + sell_to) / active_sides, 6)


_COST_SCENARIOS: dict[str, float] = {
    "0成本": 0.0,
    "低成本(0.05%)": 0.0005,
    "中成本(0.15%)": 0.0015,
    "高成本(0.30%)": 0.0030,
}


def _cost_sensitivity(long_short: pd.Series, turnover_rate: float, rollover_count: int) -> dict:
    n = len(long_short)
    result = {}
    for label, one_way in _COST_SCENARIOS.items():
        daily_turnover_cost = turnover_rate * 2 * one_way
        daily_rollover_cost = (rollover_count / n * one_way) if n > 0 else 0.0
        net = long_short - daily_turnover_cost - daily_rollover_cost
        net_curve = (1 + net).cumprod()
        net_dd = (net_curve / net_curve.cummax() - 1).min() if not net_curve.empty else 0.0
        result[label] = {
            "净ARR(%)": round(annualized_return(net) * 100, 4),
            "净MDD(%)": round(float(net_dd) * 100, 4),
        }
    return result


def calculate_metrics(factor: pd.DataFrame, forward: pd.DataFrame, rollover_count: int = 0) -> dict:
    panel = factor.merge(forward, on=["trade_date", "symbol"], how="inner")
    if panel.empty:
        raise ValueError("回测样本为空")

    daily_ic = panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()
    daily_rank_ic = panel.groupby("trade_date").apply(rank_ic, include_groups=False).dropna()
    ic = float(daily_ic.mean()) if not daily_ic.empty else 0.0
    icir = float(daily_ic.mean() / daily_ic.std()) if len(daily_ic) > 1 and daily_ic.std() else 0.0
    rank_ic_value = float(daily_rank_ic.mean()) if not daily_rank_ic.empty else 0.0
    rank_icir = (
        float(daily_rank_ic.mean() / daily_rank_ic.std())
        if len(daily_rank_ic) > 1 and daily_rank_ic.std()
        else 0.0
    )

    ic_ttest = stats.ttest_1samp(daily_ic, 0) if len(daily_ic) >= 2 else None
    rank_ic_ttest = stats.ttest_1samp(daily_rank_ic, 0) if len(daily_rank_ic) >= 2 else None

    n_groups = 5 if panel["trade_date"].nunique() >= 5 else 2
    group_labels = [f"Q{i}" for i in range(1, n_groups + 1)] if n_groups == 5 else ["low", "high"]
    panel["group"] = panel.groupby("trade_date")["factor_value"].transform(
        lambda s: pd.qcut(s.rank(method="first"), n_groups, labels=group_labels)
    )
    group_return = panel.groupby("group", observed=False)["forward_return"].mean().round(6).to_dict()
    buy_return = panel[panel["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0)
    sell_return = panel[panel["signal"] == "sell"].groupby("trade_date")["forward_return"].mean().fillna(0)
    long_short = buy_return.subtract(sell_return, fill_value=0)
    curve = (1 + long_short).cumprod()
    cumulative_return = float(curve.iloc[-1] - 1) if not curve.empty else 0.0
    drawdown = curve / curve.cummax() - 1 if not curve.empty else pd.Series(dtype=float)
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = cumulative_return / abs(max_drawdown) if max_drawdown else 0.0

    turnover_rate = round(_turnover(panel), 6)
    return {
        "IC": round(ic, 6),
        "ICIR": round(icir, 6),
        "IC_t": round(float(ic_ttest.statistic), 4) if ic_ttest else None,
        "IC_p": round(float(ic_ttest.pvalue), 4) if ic_ttest else None,
        "Rank IC": round(rank_ic_value, 6),
        "Rank ICIR": round(rank_icir, 6),
        "RankIC_t": round(float(rank_ic_ttest.statistic), 4) if rank_ic_ttest else None,
        "RankIC_p": round(float(rank_ic_ttest.pvalue), 4) if rank_ic_ttest else None,
        "IR(SHR*)": round(information_ratio(long_short), 6),
        "CR": round(calmar, 6),
        "ARR(%)": round(annualized_return(long_short) * 100, 6),
        "MDD(%)": round(max_drawdown * 100, 6),
        "分层收益": group_return,
        "多空收益": round(float(long_short.mean()), 6) if not long_short.empty else 0.0,
        "换手率": turnover_rate,
        "换月次数": int(rollover_count),
        "样本数": int(len(panel)),
        "成本敏感性": _cost_sensitivity(long_short, turnover_rate, rollover_count),
        "评估口径": "因子在 t 日形成；forward_return 使用 t 日主力同一合约的 t+1 close / t close - 1，换月价差不计入收益，未计手续费/滑点。",
        "positive_ic_ratio": round(float((daily_ic > 0).mean()), 4) if not daily_ic.empty else None,
        "rolling_ic_1y": (
            round(float(daily_ic.rolling(252, min_periods=60).mean().dropna().iloc[-1]), 6)
            if len(daily_ic) >= 60 else None
        ),
        "IC_bootstrap_CI95": (
            lambda ci: f"[{ci[0]:.4f}, {ci[1]:.4f}]"
        )(bootstrap_ic_ci(daily_ic, n_bootstrap=200)) if len(daily_ic) >= 4 else None,
    }


def run_backtest() -> dict:
    positions = load_real_position()
    factor = calculate_factor(positions, update_time="2026-06-01T12:00:00")
    symbols = sorted(factor["symbol"].unique().tolist())
    start_date = factor["trade_date"].min()
    end_date = factor["trade_date"].max()
    dominant, daily = load_real_dominant_and_daily(symbols, start_date, end_date)
    forward = build_forward_returns(dominant, daily)
    metrics = calculate_metrics(factor, forward, rollover_count=count_rollovers(dominant))
    metrics["IC_by_horizon"] = calculate_ic_by_horizon(factor, dominant, daily)
    return metrics


def run_tradeable_backtest(
    data_lag: int = 0,
    roll_cost_bps: float = 5.0,
    tcost_bps: float = 5.0,
) -> dict:
    """
    Tradeable backtest with explicit execution lag, rollover cost, and transaction cost.

    data_lag: days between signal formation and execution (0 = T-night data → T+1 execution).
    roll_cost_bps: one-way bps cost on contract rollover days.
    tcost_bps: one-way bps per unit turnover per day.
    """
    from factor import calculate_factor, load_real_position

    positions = load_real_position()
    factor = calculate_factor(positions, update_time="2026-06-01T12:00:00")
    symbols = sorted(factor["symbol"].unique().tolist())
    start_date = factor["trade_date"].min()
    end_date = factor["trade_date"].max()
    dominant, daily = load_real_dominant_and_daily(symbols, start_date, end_date)
    forward = build_tradeable_forward_returns(dominant, daily, data_lag=data_lag, roll_cost_bps=roll_cost_bps)
    metrics = calculate_metrics(factor, forward, rollover_count=count_rollovers(dominant))
    tcost_per_day = _turnover(
        factor.merge(forward[["trade_date", "symbol"]], on=["trade_date", "symbol"], how="inner")
    ) * 2 * tcost_bps / 10000
    buy_return = (
        factor.merge(forward, on=["trade_date", "symbol"], how="inner")
        .pipe(lambda p: p[p["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0))
    )
    sell_return = (
        factor.merge(forward, on=["trade_date", "symbol"], how="inner")
        .pipe(lambda p: p[p["signal"] == "sell"].groupby("trade_date")["forward_return"].mean().fillna(0))
    )
    long_short_net = buy_return.subtract(sell_return, fill_value=0) - tcost_per_day
    metrics["tradeable_ARR(%)"] = round(annualized_return(long_short_net) * 100, 6)
    metrics["tradeable_IR"] = round(information_ratio(long_short_net), 6)
    metrics["执行口径"] = (
        f"data_lag={data_lag}日；换月成本={roll_cost_bps}bps单边；"
        f"交易成本={tcost_bps}bps单边；"
        "执行价为收盘价，换月日扣除双边滚动成本。"
    )
    return metrics


if __name__ == "__main__":
    # 先加载席位数据，推断品种和日期范围
    positions = load_real_position()
    _pos = pd.DataFrame(positions)
    _symbols = sorted(_pos["underlying_symbol"].astype(str).str.upper().unique().tolist())
    _start = pd.to_datetime(
        _pos["date"].astype(str).str.replace("-", "", regex=False).min(), format="%Y%m%d"
    ).strftime("%Y-%m-%d")
    _end = pd.to_datetime(
        _pos["date"].astype(str).str.replace("-", "", regex=False).max(), format="%Y%m%d"
    ).strftime("%Y-%m-%d")

    # 加载价格数据（用于计算 forward_returns 和 IC 衰减）
    dominant, daily = load_real_dominant_and_daily(_symbols, _start, _end)
    forward = build_forward_returns(dominant, daily)
    rollovers = count_rollovers(dominant)

    # 计算因子（F5 会员持仓集中度）
    factor = calculate_factor(
        positions,
        update_time="2026-06-01T12:00:00",
    )

    # ── 研究口径 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("研究口径（same-contract close-to-close，不计成本）")
    print("=" * 60)
    forward = build_forward_returns(dominant, daily)
    metrics = calculate_metrics(factor, forward, rollover_count=rollovers)
    metrics["IC_by_horizon"] = calculate_ic_by_horizon(factor, dominant, daily)
    SKIP = {"IC_by_horizon", "成本敏感性", "评估口径"}
    for key, value in metrics.items():
        if key not in SKIP:
            print(f"  {key}: {value}")
    print(f"\n  评估口径: {metrics['评估口径']}")
    print("\n  成本敏感性:")
    for label, v in metrics["成本敏感性"].items():
        print(f"    {label}: {v}")
    print("\n  IC 多周期衰减:")
    for h, v in metrics["IC_by_horizon"].items():
        print(f"    {h}: {v}")

    # ── 可交易口径 ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("可交易口径（data_lag=1, roll=5bps, tcost=5bps）")
    print("=" * 60)
    t_forward = build_tradeable_forward_returns(dominant, daily, data_lag=1, roll_cost_bps=5.0)
    t_metrics = calculate_metrics(factor, t_forward, rollover_count=rollovers)
    tcost_per_day = _turnover(
        factor.merge(t_forward[["trade_date", "symbol"]], on=["trade_date", "symbol"], how="inner")
    ) * 2 * 5.0 / 10000
    buy_r = factor.merge(t_forward, on=["trade_date", "symbol"], how="inner")
    long_short_net = (
        buy_r[buy_r["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0)
        .subtract(
            buy_r[buy_r["signal"] == "sell"].groupby("trade_date")["forward_return"].mean().fillna(0),
            fill_value=0,
        )
        - tcost_per_day
    )
    print(f"  tradeable_ARR(%): {round(annualized_return(long_short_net) * 100, 6)}")
    print(f"  tradeable_IR:     {round(information_ratio(long_short_net), 6)}")
    print(f"  执行口径: data_lag=1日；换月成本=5bps单边；交易成本=5bps单边")
