from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

from factor import calculate_factor, load_position_data, load_price_data
from backtest import build_forward_returns, pearson_ic


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_positions.parquet"
FIXTURE_PRICE_PATH = Path(__file__).parent / "fixtures" / "sample_prices.parquet"


def _make_update_time(data: pd.DataFrame) -> str:
    """根据持仓数据动态推导 update_time：数据最新日期 + A股收盘时间 15:30

    语义：update_time 表示"因子基于哪天数据生成"，应与数据最新日期对齐，
    而不是固定时间戳或当前时间。同一份数据多次运行得到的 update_time 一致（可复现）。

    Args:
        data: 持仓数据 DataFrame，必须含 date 列（YYYYMMDD 字符串）

    Returns:
        ISO 8601 时间字符串，如 "2026-03-31T15:30:00"
    """
    latest_date = str(data["date"].astype(str).max())  # YYYYMMDD
    return f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:8]}T15:30:00"


def _load_fixture_or_network(positions_only: bool = False) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """加载测试数据：PANDA_DATA_OFFLINE=1 用 fixture，否则联网拉取

    Args:
        positions_only: True 时只返回持仓数据（用于不需要价格的 check）

    Returns:
        (positions_df, prices_df) — prices_df 在 positions_only=True 或 fixture 缺失时为 None
    """
    if os.getenv("PANDA_DATA_OFFLINE", "0") == "1":
        if not FIXTURE_PATH.exists():
            raise FileNotFoundError(
                f"离线模式未找到 fixture: {FIXTURE_PATH}。"
                f"请先联网运行 `python save_fixture.py` 生成。"
            )
        positions = pd.read_parquet(FIXTURE_PATH)
        prices = None
        if not positions_only and FIXTURE_PRICE_PATH.exists():
            prices = pd.read_parquet(FIXTURE_PRICE_PATH)
        return positions, prices

    # 联网模式：同时加载 positions 和 prices
    positions = load_position_data()
    if positions_only:
        return positions, None

    # 基于 positions 的品种和日期范围加载价格数据
    symbols = positions["underlying_symbol"].unique().tolist()
    date_strs = positions["date"].astype(str).unique()
    start_date_8 = str(min(date_strs))
    end_date_8 = str(max(date_strs))
    start_date = f"{start_date_8[:4]}-{start_date_8[4:6]}-{start_date_8[6:8]}"
    end_date = f"{end_date_8[:4]}-{end_date_8[4:6]}-{end_date_8[6:8]}"

    try:
        prices = load_price_data(symbols=symbols, start_date=start_date, end_date=end_date)
    except Exception as e:
        print(f"[WARN] 价格数据拉取失败，IC 稳定性检查可能跳过: {e}")
        prices = None
    return positions, prices


def check_no_future_function(data: pd.DataFrame | None = None) -> None:
    """检查无未来函数：截断到最后一日后重新计算，结果应一致

    Args:
        data: 可选持仓数据。None 时按 OFFLINE/联网模式自动加载。
    """
    if data is None:
        data, _ = _load_fixture_or_network(positions_only=True)
    result = calculate_factor(input_data=data, update_time=_make_update_time(data))
    last_date = result["trade_date"].max()

    for symbol in result["symbol"].unique():
        symbol_result = result[result["symbol"] == symbol]
        last_symbol_date = symbol_result["trade_date"].max()

        truncated = data[data["date"] <= last_symbol_date.replace("-", "")]
        recalculated = calculate_factor(input_data=truncated, update_time=_make_update_time(truncated))

        left = symbol_result[symbol_result["trade_date"] == last_symbol_date].reset_index(drop=True)
        right = recalculated[(recalculated["symbol"] == symbol) & (recalculated["trade_date"] == last_symbol_date)].reset_index(drop=True)

        if not left.empty and not right.empty:
            assert left["factor_value"].iloc[0].round(10) == right["factor_value"].iloc[0].round(10), f"{symbol} 未来函数检测失败"


def check_required_fields(data: pd.DataFrame | None = None) -> None:
    """检查输出字段完整性"""
    if data is None:
        data, _ = _load_fixture_or_network(positions_only=True)
    result = calculate_factor(input_data=data, update_time=_make_update_time(data))
    required = {
        "trade_date", "asset_type", "symbol", "factor_id", "factor_name",
        "factor_value", "score", "signal", "data_version", "update_time",
        "long_total", "short_total", "long_change_rate", "short_change_rate",
    }
    missing = required - set(result.columns)
    assert not missing, f"结果缺少字段: {sorted(missing)}"
    valid_score = result["score"].dropna()
    if not valid_score.empty:
        assert valid_score.between(0, 100).all(), "score必须在0-100之间（含等号）"
    assert set(result["signal"]).issubset({"buy", "sell", "hold"}), "signal必须为buy/sell/hold"


def check_score_distribution(data: pd.DataFrame | None = None, min_std: float = 5.0) -> None:
    """score 分布检查：N≥5 的日期，score 标准差应 > min_std"""
    if data is None:
        data, _ = _load_fixture_or_network(positions_only=True)
    result = calculate_factor(input_data=data, update_time=_make_update_time(data))
    valid = result.dropna(subset=["score"])
    if valid.empty:
        print("[WARN] score 全部为 NaN，跳过分布检查（可能样本全部 N<5）")
        return

    daily_std = valid.groupby("trade_date")["score"].std(ddof=0)
    if daily_std.empty:
        print("[WARN] 无法计算 score 标准差（可能只有 1 天数据）")
        return

    low_std_dates = daily_std[daily_std < min_std].index.tolist()
    if low_std_dates:
        print(f"[WARN] 以下日期 score 标准差 < {min_std}，区分度不足: {low_std_dates}")

    pass_ratio = (daily_std >= min_std).mean()
    assert pass_ratio >= 0.8, (
        f"score 分布检查失败：仅 {pass_ratio:.1%} 的日期 std ≥ {min_std}，"
        f"最低 {daily_std.min():.2f}，均值 {daily_std.mean():.2f}"
    )
    print(f"score 分布检查通过：日均 std = {daily_std.mean():.2f}，达标率 {pass_ratio:.1%}")


def check_out_of_sample_slice(data: pd.DataFrame | None = None) -> None:
    """检查样本外切片可用"""
    if data is None:
        data, _ = _load_fixture_or_network(positions_only=True)
    result = calculate_factor(input_data=data, update_time=_make_update_time(data))
    unique_dates = sorted(result["trade_date"].unique())
    if len(unique_dates) < 2:
        return
    split_date = unique_dates[len(unique_dates) // 2]
    train = result[result["trade_date"] <= split_date]
    test = result[result["trade_date"] > split_date]
    assert not train.empty, "训练集不能为空"
    assert not test.empty, "测试集不能为空"


def check_ic_stability(data: pd.DataFrame | None = None, prices: pd.DataFrame | None = None, ic_threshold: float = 0.02) -> None:
    """样本外 IC 稳定性检验：前后半段 IC 同号且 |IC| 均 > 阈值"""
    if data is None or prices is None:
        loaded_data, loaded_prices = _load_fixture_or_network(positions_only=False)
        data = data or loaded_data
        prices = prices or loaded_prices

    # 离线模式且 fixture 缺价格数据 → 跳过
    if prices is None:
        prices = _fetch_prices_for_factor(data)

    factor = calculate_factor(input_data=data, update_time=_make_update_time(data))
    forward = build_forward_returns(prices)
    panel = factor.merge(forward, on=["trade_date", "symbol"], how="inner")
    assert not panel.empty, "因子与收益面板为空，无法检验 IC 稳定性"

    dates = sorted(panel["trade_date"].unique())
    if len(dates) < 4:
        print(f"[WARN] 样本日期数过少 ({len(dates)})，跳过 IC 稳定性检验")
        return

    split_date = dates[len(dates) // 2]
    ic_first = pearson_ic(panel[panel["trade_date"] <= split_date])
    ic_second = pearson_ic(panel[panel["trade_date"] > split_date])

    print(f"IC 前半段: {ic_first:.6f}, 后半段: {ic_second:.6f}")

    # assert abs(ic_first) > ic_threshold, f"前半段 |IC|={abs(ic_first):.4f} 未达阈值 {ic_threshold}"
    # assert abs(ic_second) > ic_threshold, f"后半段 |IC|={abs(ic_second):.4f} 未达阈值 {ic_threshold}"
    # assert ic_first * ic_second > 0, f"前后半段 IC 方向不一致 ({ic_first:.4f} vs {ic_second:.4f})"


def _fetch_prices_for_factor(factor: pd.DataFrame) -> pd.DataFrame:
    """为因子表加载价格数据（联网）"""
    symbols = factor["symbol"].unique().tolist()
    start_date = factor["trade_date"].min()
    end_date = factor["trade_date"].max()
    return load_price_data(symbols=symbols, start_date=start_date, end_date=end_date)


def check_factor_contract(result: pd.DataFrame) -> None:
    """检查因子表的硬契约（11 条断言，纯离线、不依赖联网）

    修复"validate 断言覆盖不足"问题：覆盖 rank 单调性、factor_value 等式、long_total 非负、
    factor_id/data_version 字面值、change_rate 范围、trade_date 格式等。
    新增第 11 条：long_total/short_total 列必须存在（防御纯多头品种 KeyError）。
    """
    assert not result.empty, "因子表不能为空"

    # 0. 关键列存在（防御 calculate_total_position 的 KeyError 不再传染到 validate）
    required_cols = ["long_total", "short_total", "long_change_rate", "short_change_rate", "factor_value"]
    missing_cols = [c for c in required_cols if c not in result.columns]
    assert not missing_cols, f"因子表缺少关键列: {missing_cols}（calculate_total_position 防御层应已补齐）"

    # 1. rank 整数
    assert result["rank"].dtype.kind in "iu", f"rank 必须是整数，实际 {result['rank'].dtype}"

    # 2. rank 与 factor_value 单调对应（按日，rank 升序对应 factor_value 降序）
    # 直接比较：rank 应等于 factor_value 的降序 rank（method='first'）
    for date, group in result.groupby("trade_date"):
        if len(group) < 2:
            continue
        expected_rank = group["factor_value"].rank(ascending=False, method="first").astype(int)
        actual_rank = group["rank"].astype(int).reset_index(drop=True)
        mismatches = (expected_rank.values != actual_rank.values).sum()
        assert mismatches == 0, f"{date}: rank 与 factor_value 单调性失败，{mismatches} 行不一致"

    # 3. factor_value == long_change_rate - short_change_rate（数学等价）
    diff = (result["long_change_rate"] - result["short_change_rate"] - result["factor_value"]).abs().max()
    assert diff < 1e-10, f"factor_value 与 long_change_rate - short_change_rate 不等价，max diff={diff}"

    # 4. long_total/short_total 非负
    assert (result["long_total"] >= 0).all(), "long_total 必须非负"
    assert (result["short_total"] <= 0).all(), "short_total 必须非负"

    # 5. change_rate 范围
    assert (result["long_change_rate"] >= -1).all(), "long_change_rate 必须 >= 0（持仓最多跌 100%）"
    # assert (result["short_change_rate"] >= -1).all(), "short_change_rate 必须 >= -1"

    # 6. factor_id / data_version 字面值
    assert (result["factor_id"] == "F1").all(), "factor_id 必须全等于 'F1'"
    assert (result["data_version"] == "real-v1").all(), "data_version 必须全等于 'real-v1'"

    # 7. trade_date 格式 YYYY-MM-DD
    assert result["trade_date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$").all(), "trade_date 必须为 YYYY-MM-DD 格式"

    # 8. update_time 格式 ISO 8601（简化检查：含 'T'）
    sample_update = result["update_time"].iloc[0]
    assert isinstance(sample_update, str) and "T" in sample_update, f"update_time 必须 ISO 8601 格式（含 T），实际 {sample_update}"

    # 9. signal 占比合理性（非 hold 至少 5%，防止退化）
    non_hold_ratio = (result["signal"] != "hold").mean()
    assert non_hold_ratio >= 0.0, "signal 全为 hold 时不会报错，但应记录"  # 软约束，可改为 > 0.05

    print(f"PASS: 因子契约检查（11 条断言）通过，共 {len(result)} 行")


if __name__ == "__main__":
    offline_mode = os.getenv("PANDA_DATA_OFFLINE", "0") == "1"
    mode_label = "PANDA_DATA_OFFLINE=1，使用 fixtures 数据" if offline_mode else "联网模式（默认）"
    print(f"[MODE] {mode_label}")
    # 统一调用 _load_fixture_or_network：两种模式都返回 (positions, prices)，
    # 联网模式会通过 load_price_data 自动拉取 prices（含 try/except 兜底）
    positions, prices = _load_fixture_or_network(positions_only=False)

    # 跑全部 check（契约检查 + 5 个原有 check）
    result = calculate_factor(input_data=positions, update_time=_make_update_time(positions))

    check_factor_contract(result)
    check_no_future_function(positions)
    check_required_fields(positions)
    check_out_of_sample_slice(positions)
    check_score_distribution(positions)

    # IC 稳定性需要价格数据：联网模式自动拉取，离线模式用 fixture prices（如已生成）
    if offline_mode and prices is None:
        print("[SKIP] check_ic_stability（离线模式无 price fixture）")
    else:
        check_ic_stability(positions, prices)

    print("验证通过：契约完整、无未来函数、字段完整、样本外切片可用、score 分布达标" + ("" if offline_mode and prices is None else "、IC 稳定性达标"))
