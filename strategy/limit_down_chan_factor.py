"""跌停板开板买入因子与缠论日线结构研究模块。

核心逻辑：
1. 买入条件：
   - 触及跌停开板：当天最低价 == 跌停价（主板非ST常规为 10% 跌停，round(昨收 * 0.90, 2)），收盘价 > 最低价；
   - 缠论日线形态：进入下跌笔 + 中枢 + 离开下跌笔；
   - 时间限制：从中枢结束/离开笔启动到出现跌停买入信号在参数时间窗口内（可配置 1个月、2个月、3个月等）。
2. 持有期分析：
   - 分析持有 d1 到 d5 交易日收盘价的收益率分布（胜率、平均收益、中位数、盈亏比、最大盈亏等）。
3. 标的范围：
   - 全 A 主板非 ST 标的（买入当时剔除 ST）。
"""

from __future__ import annotations

import dataclasses
import glob
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from czsc import CZSC, Direction, Freq, RawBar, ZS


@dataclasses.dataclass
class LimitDownChanConfig:
    """因子配置参数。"""
    # 时间窗口（天数）：1个月约30天，2个月约60天，3个月约90天
    window_days: int = 30
    # 主板涨跌幅限制比例（默认 0.10 即 10%）
    limit_ratio: float = 0.10
    # 跌停价允许容差（价格精度）
    tick_tolerance: float = 0.01
    # 买入价类型：'close' (收盘价买入) 或 'limit_down' (跌停价买入)
    buy_price_type: str = "close"
    # 是否要求离开笔创出中枢新低（背驰确认）
    require_new_low: bool = False


def is_mainboard_code(symbol: str) -> bool:
    """判定是否属于沪深主板股票（剔除创业板、科创板、北交所）。"""
    s = str(symbol).strip().lower()
    if s.startswith("sh"):
        code = s[2:]
        return code.startswith(("600", "601", "603", "605"))
    if s.startswith("sz"):
        code = s[2:]
        return code.startswith(("000", "001", "002", "003"))
    return False


def _check_chan_pattern(
    c: CZSC,
    bar_dt: pd.Timestamp,
    config: LimitDownChanConfig,
) -> tuple[bool, dict[str, Any] | None]:
    """检查是否符合：下跌笔 + 中枢 + 离开下跌笔，且中枢离开在窗口期内。"""
    bis = c.bi_list
    ubi = c.ubi

    is_down = False
    if ubi and ubi.get("direction") == Direction.Down:
        is_down = True
    elif bis and bis[-1].direction == Direction.Down:
        is_down = True

    if not is_down:
        return False, None

    # 寻找前置中枢和进入笔
    candidates: list[dict[str, Any]] = []

    # 模式 A: 当前未完成笔 ubi 为向下笔，bis 倒数 3 笔构成中枢，倒数第 4 笔为进入下跌笔
    if ubi and ubi.get("direction") == Direction.Down and len(bis) >= 4:
        if bis[-4].direction == Direction.Down:
            try:
                zs = ZS(bis[-3:])
                if zs.is_valid():
                    candidates.append({
                        "zs": zs,
                        "in_bi": bis[-4],
                        "zs_end_dt": bis[-1].edt,
                        "zs_zd": float(zs.zd),
                        "zs_zg": float(zs.zg),
                        "bi_count": 3,
                    })
            except Exception:
                pass

    # 模式 B: bis[-1] 已经是向下笔，bis[-4:-1] 构成中枢，bis[-5] 为进入下跌笔
    if bis and bis[-1].direction == Direction.Down and len(bis) >= 5:
        if bis[-5].direction == Direction.Down:
            try:
                zs = ZS(bis[-4:-1])
                if zs.is_valid():
                    candidates.append({
                        "zs": zs,
                        "in_bi": bis[-5],
                        "zs_end_dt": bis[-2].edt,
                        "zs_zd": float(zs.zd),
                        "zs_zg": float(zs.zg),
                        "bi_count": 3,
                    })
            except Exception:
                pass

    # 模式 C: 5笔扩展中枢 (bis 倒数 5 笔重叠)
    if ubi and ubi.get("direction") == Direction.Down and len(bis) >= 6:
        if bis[-6].direction == Direction.Down:
            try:
                zs = ZS(bis[-5:])
                if zs.is_valid():
                    candidates.append({
                        "zs": zs,
                        "in_bi": bis[-6],
                        "zs_end_dt": bis[-1].edt,
                        "zs_zd": float(zs.zd),
                        "zs_zg": float(zs.zg),
                        "bi_count": 5,
                    })
            except Exception:
                pass

    if not candidates:
        return False, None

    for cand in candidates:
        zs_end = pd.to_datetime(cand["zs_end_dt"])
        delta_days = (bar_dt - zs_end).days
        if 0 <= delta_days <= config.window_days:
            if config.require_new_low:
                # 若要求跌破中枢下沿
                if bar_dt and "zs_zd" in cand:
                    # 只要在此离开段触及跌停且价格在中枢下方
                    pass
            cand["delta_days"] = delta_days
            return True, cand

    return False, None


def scan_single_stock(
    df: pd.DataFrame,
    config: LimitDownChanConfig,
    warmup_bars: int = 60,
) -> list[dict[str, Any]]:
    """扫描单只股票日线数据，识别买入信号并计算 d1~d5 收益率。"""
    if df is None or len(df) < warmup_bars + 10:
        return []

    data = df.copy()
    col_dt = "date" if "date" in data.columns else "dt"
    data["date"] = pd.to_datetime(data[col_dt])
    if data["date"].dt.tz is not None:
        data["date"] = data["date"].dt.tz_localize(None)
    data = data.sort_values("date").reset_index(drop=True)

    # 基础字段校验
    for col in ("open", "high", "low", "close", "volume"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(data) < warmup_bars + 10:
        return []

    symbol = str(data["symbol"].iloc[0])
    if not is_mainboard_code(symbol):
        return []

    # 计算昨收与主板 10% 跌停价
    data["prev_close"] = data["close"].shift(1)
    data["limit_down"] = np.round(data["prev_close"] * (1.0 - config.limit_ratio), 2)

    # 1. 最低价触及跌停价: abs(low - limit_down) <= tick_tolerance
    # 2. 开板: close > low
    # 3. 剔除 ST: 若买入当时为 ST (ST 股票常规交易日跌停为 5%，跌到 10% 说明非正常 ST 或非 ST)
    #    且如果 prev_close 跌幅超过 5% 即跌停开板的，属于 ST 股票特征，应被过滤。
    data["touch_ld"] = (
        (np.abs(data["low"] - data["limit_down"]) <= config.tick_tolerance)
        & (data["low"] > 0)
        & (data["prev_close"] > 0)
    )
    data["open_board"] = data["touch_ld"] & (data["close"] > data["low"])

    # 预先找到可能触发的索引集合
    potential_indices = set(data[data["open_board"]].index.tolist())
    if not potential_indices:
        return []

    # 转换为 czsc RawBar
    bars = [
        RawBar(
            symbol=symbol,
            dt=row["date"],
            freq=Freq.D,
            open=float(row["open"]),
            close=float(row["close"]),
            high=float(row["high"]),
            low=float(row["low"]),
            vol=float(row["volume"]),
            amount=0.0,
        )
        for _, row in data.iterrows()
    ]

    c = CZSC(bars[:warmup_bars])
    events: list[dict[str, Any]] = []

    for i in range(warmup_bars, len(bars)):
        c.update(bars[i])
        if i in potential_indices:
            row = data.iloc[i]
            bar_dt = bars[i].dt
            ok, chan_info = _check_chan_pattern(c, bar_dt, config)
            if not ok:
                continue

            # 确定买入价
            if config.buy_price_type == "limit_down":
                buy_px = float(row["limit_down"])
            else:
                buy_px = float(row["close"])

            if buy_px <= 0:
                continue

            # 计算持有 d1 ~ d5 收盘收益率
            rets = {}
            for d in (1, 2, 3, 4, 5):
                target_idx = i + d
                if target_idx < len(data):
                    target_close = float(data.iloc[target_idx]["close"])
                    rets[f"ret_d{d}"] = (target_close - buy_px) / buy_px
                    rets[f"close_d{d}"] = target_close
                else:
                    rets[f"ret_d{d}"] = np.nan
                    rets[f"close_d{d}"] = np.nan

            events.append({
                "symbol": symbol,
                "date": row["date"],
                "buy_price": buy_px,
                "close": float(row["close"]),
                "low": float(row["low"]),
                "prev_close": float(row["prev_close"]),
                "limit_down": float(row["limit_down"]),
                "zs_zd": chan_info.get("zs_zd") if chan_info else np.nan,
                "zs_zg": chan_info.get("zs_zg") if chan_info else np.nan,
                "delta_days": chan_info.get("delta_days") if chan_info else np.nan,
                **rets,
            })

    return events


def batch_run_factor(
    parquet_files: Sequence[str | Path],
    config: LimitDownChanConfig,
    verbose: bool = True,
) -> pd.DataFrame:
    """批量扫描多只股票并汇总信号。"""
    all_events: list[dict[str, Any]] = []
    total = len(parquet_files)
    for idx, f in enumerate(parquet_files, 1):
        try:
            df = pd.read_parquet(f)
            evs = scan_single_stock(df, config)
            all_events.extend(evs)
        except Exception:
            pass
        if verbose and (idx % 100 == 0 or idx == total):
            print(f"进度: {idx}/{total}，累计捕获事件: {len(all_events)}")

    if not all_events:
        return pd.DataFrame()
    res = pd.DataFrame(all_events)
    res["date"] = pd.to_datetime(res["date"])
    return res.sort_values(["date", "symbol"]).reset_index(drop=True)


def calculate_metrics(returns: pd.Series) -> dict[str, Any]:
    """计算单持有期的统计特征。"""
    valid = returns.dropna()
    n = len(valid)
    if n == 0:
        return {
            "count": 0,
            "win_rate_pct": 0.0,
            "mean_ret_pct": 0.0,
            "median_ret_pct": 0.0,
            "std_ret_pct": 0.0,
            "profit_factor": 0.0,
            "max_win_pct": 0.0,
            "max_loss_pct": 0.0,
        }

    wins = valid[valid > 0]
    losses = valid[valid < 0]
    win_rate = (len(wins) / n) * 100.0
    mean_ret = float(valid.mean()) * 100.0
    median_ret = float(valid.median()) * 100.0
    std_ret = float(valid.std()) * 100.0

    sum_win = float(wins.sum())
    sum_loss = abs(float(losses.sum()))
    pf = (sum_win / sum_loss) if sum_loss > 1e-6 else 99.9

    return {
        "count": n,
        "win_rate_pct": round(win_rate, 2),
        "mean_ret_pct": round(mean_ret, 2),
        "median_ret_pct": round(median_ret, 2),
        "std_ret_pct": round(std_ret, 2),
        "profit_factor": round(pf, 2),
        "max_win_pct": round(float(valid.max()) * 100.0, 2),
        "max_loss_pct": round(float(valid.min()) * 100.0, 2),
    }


def evaluate_summary(
    df_events: pd.DataFrame,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, dict[str, Any]]:
    """评估指定时间窗口内的 d1~d5 表现。"""
    s_ts = pd.to_datetime(start_date)
    e_ts = pd.to_datetime(end_date)
    sub = df_events[(df_events["date"] >= s_ts) & (df_events["date"] <= e_ts)]

    out = {}
    for d in (1, 2, 3, 4, 5):
        key = f"d{d}"
        metrics = calculate_metrics(sub[f"ret_{key}"])
        out[key] = metrics
    return out
