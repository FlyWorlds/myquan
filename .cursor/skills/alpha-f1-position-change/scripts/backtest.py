from __future__ import annotations

import pandas as pd

from factor import calculate_factor, load_position_data, load_price_data


def build_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """基于真实价格数据构建未来收益（修复"持仓自相关 IC"问题的核心）

    严格口径（避免偷价）：
        forward_return_t = close_{t+1} / open_{t+1} - 1
    信号 t 日收盘后产生（持仓数据 t 日收盘后才发布），最早 t+1 日开盘才能成交，
    t+1 日收盘平仓。这样保证因子和收益不共用 t 日数据，符合 SKILL.md "不允许偷价"要求。

    Args:
        prices: 价格 DataFrame，必须包含 date / symbol / open / close 字段。

    Returns:
        DataFrame，包含字段：
        - trade_date: 信号产生的日期（YYYY-MM-DD 格式，对应 t 日）
        - symbol: 品种代码
        - forward_return: t+1 日 open → close 的真实价格收益
    """
    required = {"date", "symbol", "open", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"价格数据缺少必要字段: {sorted(missing)}")

    df = prices.copy()
    df = df.sort_values(["symbol", "date"])

    # 按 (symbol) 分组取次日 open / close
    df["next_open"] = df.groupby("symbol")["open"].shift(-1)
    df["next_close"] = df.groupby("symbol")["close"].shift(-1)

    # 严格口径：t+1 日开盘成交，t+1 日收盘平仓
    df["forward_return"] = df["next_close"] / df["next_open"] - 1

    # 日期格式转换（YYYYMMDD → YYYY-MM-DD），trade_date 对应因子形成的 t 日
    df["trade_date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")

    return df[["trade_date", "symbol", "forward_return"]].dropna()


def pearson_ic(x: pd.DataFrame) -> float:
    """计算 Pearson IC"""
    return float(x["factor_value"].corr(x["forward_return"]))


def rank_ic(x: pd.DataFrame) -> float:
    """计算 Rank IC"""
    factor_rank = x["factor_value"].rank(method="average")
    return_rank = x["forward_return"].rank(method="average")
    return float(factor_rank.corr(return_rank))


def information_ratio(returns: pd.Series) -> float:
    """计算信息比率"""
    std = returns.std()
    if returns.empty or not std:
        return 0.0
    return float(returns.mean() / std * (252**0.5))


def annualized_return(returns: pd.Series) -> float:
    """计算年化收益率"""
    if returns.empty:
        return 0.0
    cumulative_return = float((1 + returns).prod() - 1)
    years = len(returns) / 252
    if years <= 0:
        return cumulative_return
    return float((1 + cumulative_return) ** (1 / years) - 1)


def run_backtest() -> dict:
    """运行回测

    计算期货持仓因子的 IC、ICIR、分层收益等指标。
    收益基于 get_future_daily 主力合约真实价格，采用严格口径避免偷价。
    """
    # 加载原始持仓数据
    raw_positions = load_position_data()

    # 计算因子
    factor = calculate_factor(input_data=raw_positions)

    # 加载覆盖因子表的价格数据（按因子涉及的品种和日期范围）
    factor_symbols = factor["symbol"].unique().tolist()
    start_date = factor["trade_date"].min()
    end_date = factor["trade_date"].max()
    prices = load_price_data(symbols=factor_symbols, start_date=start_date, end_date=end_date)

    # 基于真实价格收益构建 forward_return（严格口径：t+1 日 open → close）
    forward = build_forward_returns(prices)

    # 合并数据（按日期和品种）
    panel = factor.merge(forward, on=["trade_date", "symbol"], how="inner")

    if panel.empty:
        raise ValueError("回测样本为空")

    # 按日期计算 IC 指标
    # include_groups=False：pandas ≥2.2 默认会把 grouping 列传给 apply 函数并触发 FutureWarning，
    # pearson_ic/rank_ic 内部只用 factor_value/forward_return 两列，不依赖 trade_date，明确排除即可
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

    # 分层收益（按日期）
    panel["group"] = panel.groupby("trade_date")["factor_value"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 2, labels=["low", "high"], duplicates="drop")
    )
    group_return = panel.groupby("group", observed=False)["forward_return"].mean().round(6).to_dict()

    # 买入信号收益
    buy_return = panel[panel["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0)
    if buy_return.empty:
        buy_return = panel.groupby("trade_date")["forward_return"].mean().fillna(0)

    # 累计收益和回撤
    curve = (1 + buy_return).cumprod()
    cumulative_return = float(curve.iloc[-1] - 1) if not curve.empty else 0.0
    drawdown = curve / curve.cummax() - 1
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = cumulative_return / abs(max_drawdown) if max_drawdown else 0.0

    # 换手率（基于信号变化）
    signal_changes = (panel["signal"] != panel.groupby("symbol")["signal"].shift(1)).sum()
    turnover = float(signal_changes / len(panel)) if len(panel) > 0 else 0.0

    # 信号统计
    total_records = len(panel)
    buy_signals = len(panel[panel["signal"] == "buy"])
    sell_signals = len(panel[panel["signal"] == "sell"])
    hold_signals = len(panel[panel["signal"] == "hold"])

    # 按品种统计信号
    symbol_signals = panel.groupby("symbol")["signal"].value_counts().unstack(fill_value=0).to_dict()

    return {
        "IC": round(ic, 6),
        "ICIR": round(icir, 6),
        "Rank IC": round(rank_ic_value, 6),
        "Rank ICIR": round(rank_icir, 6),
        "IR(SHR*)": round(information_ratio(buy_return), 6),
        "CR": round(calmar, 6),
        "ARR(%)": round(annualized_return(buy_return) * 100, 6),
        "MDD(%)": round(max_drawdown * 100, 6),
        "分层收益": group_return,
        "换手率": round(turnover, 6),
        "样本数": int(len(panel)),
        "买入信号": buy_signals,
        "卖出信号": sell_signals,
        "持仓信号": hold_signals,
        "品种信号分布": symbol_signals,
        "评估口径": "因子在 t 日形成（基于 t 日及以前的持仓数据）；收益采用严格口径 forward_return = close_{t+1}/open_{t+1} - 1，即信号 t 日收盘后产生，t+1 日开盘成交、t+1 日收盘平仓，避免偷价；价格数据来源于 get_future_daily 主力合约。",
    }


if __name__ == "__main__":
    metrics = run_backtest()
    for key, value in metrics.items():
        if key == "品种信号分布":
            print(f"{key}:")
            for symbol, signals in value.items():
                print(f"  {symbol}: {signals}")
        else:
            print(f"{key}: {value}")
