"""510500 中证500ETF — 自适应牛熊 + 短线反转策略.

══════════════════════════════════════════════════════════════
一、策略结构（两层）
══════════════════════════════════════════════════════════════
  【层 1 · 牛熊开关】默认开启 ENABLE_ADAPTIVE_REGIME
    · 牛市：ret20 > 5%（近 20 交易日涨幅）→ 尾盘满仓持有，不做战术买卖
    · 熊市/震荡：ret20 ≤ 5% → 启用层 2 短线反转

  【层 2 · 短线反转】仅在非牛市生效
    · 触发：相对昨收涨幅 >= 阈值（默认 1.05%，可 --no-auto 固定或自动优化）
    · 过滤：默认排除 RSI>60 追高；可选 classic / score 模式
    · 买入：信号日 15:00 收盘价（CurrentClose）
    · 卖出：持股 N 日（默认 4）收盘卖；或日 K 止盈 5% / 止损 3% 提前卖

  【可选 · 价格门控】ENABLE_PRICE_REGIME=False（默认关，上涨年易跑输持有）
    · 熊市且收盘 < 5 元：仅持有不交易；> 7 元才恢复战术；再次 < 5 回到持有

══════════════════════════════════════════════════════════════
二、默认参数 & 回测设定
══════════════════════════════════════════════════════════════
  · 回测起点：2016-01-04（剔除 2015）；数据拉取自 2015-04 起（供 ret20/RSI）
  · 初始资金 10 万；仓位缓冲 98%；佣金万 0.6
  · 自动优化硬约束：笔数>200、年化>10%、最大回撤<30%

══════════════════════════════════════════════════════════════
三、相对买入持有的表现特征（2016~今，仅供参考）
══════════════════════════════════════════════════════════════
  · 下跌年：多数年份少亏（战术 + 牛熊切换有效）
  · 上涨年：部分强趋势年（如 2019/2021/2025）仍可能跑输持有
  · 全区间：总收益与回撤通常优于死拿，但非每年都赢

  运行：python ZZ500ETF.py          # 自动优化参数
        python ZZ500ETF.py --no-auto  # 固定默认参数

══════════════════════════════════════════════════════════════
四、数据
══════════════════════════════════════════════════════════════
  · 前复权 qfq：ak.fund_etf_hist_em(..., adjust="qfq")，失败回退腾讯
  · akquant：lot_size=100、T+1、免印花税；复权在 fetch 层，非 run_backtest 参数
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import cast

import akquant as aq
import akshare as ak
import numpy as np
import pandas as pd
import requests
from akquant import CurrentClose, Strategy
from akquant.utils import prepare_dataframe

# ── 配置 ──────────────────────────────────────────────
SYMBOL = "510500"
SYMBOL_NAME = "中证500ETF"
SINA_SYMBOL = "sh510500"

DATA_START = "20150401"       # 提前若干日，用于计算指标（ret20/RSI 等）
BACKTEST_START = dt.date(2016, 1, 4)  # 回测起点（剔除 2015）
DATA_END = dt.date.today().strftime("%Y%m%d")

ADJUST = "qfq"                # 前复权：akquant 推荐回测默认值（见 utils.fetch_akshare_symbol）

INITIAL_CASH = 100_000.0
LOT_SIZE = 100
GAIN_THRESHOLD = 0.0105       # 约束优化最优：涨 1.05%
GAIN_THRESHOLD_SCAN = [0.007, 0.008, 0.009, 0.010, 0.0105, 0.011, 0.012, 0.013, 0.015, 0.020, 0.025]
HOLD_DAYS = 4                 # 约束优化最优：持 4 日
CASH_BUFFER = 0.98            # 留 2% 缓冲应付手续费
OPTIMIZE_OBJECTIVE = "constrained"  # constrained | balanced | ann | calmar | total

# 硬约束目标（自动优化）
MIN_TRADES_TARGET = 200
MIN_ANN_TARGET_PCT = 10.0
MAX_MDD_TARGET_PCT = 30.0

# 反转确认因子（非牛熊择时）
LOOKBACK = 20                 # 20 日窗口
RSI_PERIOD = 14
RSI_MAX = 9999.0              # 经典过滤 RSI 上限（9999=不限制）
MIN_DD20 = 1.0                # dd20 下限（1.0=不限制回撤）
FILTER_LOGIC = "and"          # "and" | "or"
FILTER_MODE = "none"          # none=仅排除追高 | classic=RSI+dd | score=评分
MIN_SCORE = 0                 # 评分模式最低分（0=不过滤）
MAX_RSI = 60.0                # 排除 RSI>60 追高信号
STOP_LOSS_PCT = 0.03          # 止损 3% 提前收盘卖
TAKE_PROFIT_PCT = 0.05        # 止盈 5% 提前收盘卖
# 自适应牛熊：牛市满仓追涨幅，熊市才做短线反转
ENABLE_ADAPTIVE_REGIME = True # 20日收益>阈值 → 满仓不动；否则战术交易
BULL_RET20_THRESHOLD = 0.05   # ret20>5% 视为牛市（回测较优）
# 价格门控（默认关：易在上涨年跑输持有；<5 持有 />7 交易 仍保留可选）
PRICE_HOLD_BELOW = 5.0
PRICE_STRATEGY_ABOVE = 7.0
PRICE_FULL_BELOW = 5.0
ENABLE_PRICE_REGIME = False   # 熊市价格门控
ENABLE_PRICE_POSITION = False # 高价递减仓位
PRICE_REDUCE_ABOVE = 7.0
PRICE_HIGH_BASE_PCT = 0.50
PRICE_HIGH_STEP_PCT = 0.10
HOLD_DAYS_SCAN = [2, 3, 4, 5, 6, 7, 8, 10, 15]
COMMISSION_RATE = 0.00006     # 佣金万 0.6
MIN_COMMISSION = 3.0

FILL_MODE = CurrentClose()      # ETF 尾盘竞价/收盘价成交（与 akquant ETF 示例一致）
MIN30_PERIOD = "30"
EOD_BAR_HM = (15, 0)            # A 股 30 分钟最后一根 K 线 15:00

CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_daily_{ADJUST}.parquet")
MIN30_CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_30m_{ADJUST}.parquet")
REPORT_PATH = Path(__file__).with_name("zz500etf_report.html")
DAILY_CLOSE_CSV = Path(__file__).with_name(f"{SYMBOL}_daily_close_zz500etf.csv")


def round_lot(qty: float) -> int:
    return max(0, int(qty // LOT_SIZE) * LOT_SIZE)


def price_target_position_pct(
    close: float,
    *,
    full_below: float = PRICE_FULL_BELOW,
    reduce_above: float = PRICE_REDUCE_ABOVE,
    high_base_pct: float = PRICE_HIGH_BASE_PCT,
    high_step_pct: float = PRICE_HIGH_STEP_PCT,
    enable_high_reduce: bool = ENABLE_PRICE_POSITION,
) -> float | None:
    """按收盘价计算目标仓位；None 表示不强制调仓."""
    if close < full_below:
        return CASH_BUFFER
    if not enable_high_reduce:
        return None
    if close <= reduce_above:
        return None
    pct = high_base_pct - (close - reduce_above) * high_step_pct
    return max(0.0, min(CASH_BUFFER, pct))


def _to_ts(date_str: str, hhmm: str = "15:00:00") -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {hhmm}"


def _date_fmt(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _standardize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """统一为 akquant 回测列结构（与官方 ETF 示例一致）."""
    rename_map = {
        "日期": "date", "day": "date",
        "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume",
    }
    out = df.rename(columns=rename_map).copy()
    required = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"缺少列 {missing}，实际: {out.columns.tolist()}")
    out = out[required].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in required[1:]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["symbol"] = symbol
    return cast(pd.DataFrame, out)


def _fetch_etf_hist_em(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = ADJUST,
) -> pd.DataFrame:
    """akquant 官方 ETF 示例同款：fund_etf_hist_em + adjust."""
    raw = ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if raw.empty:
        raise ValueError(f"东财 ETF 日线为空: {symbol}")
    return _standardize_ohlcv(raw, symbol)


def _fetch_tencent_daily(
    sina_symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = ADJUST,
) -> pd.DataFrame:
    """腾讯财经日线（前复权 qfqday，与主流行情软件一致）.

    腾讯接口单次最多约 640 根 K 线，按年分段拉取后合并。
    """
    suffix_map = {"qfq": "qfq", "hfq": "hfq", "": ""}
    key_map = {"qfq": "qfqday", "hfq": "hfqday", "": "day"}
    suffix = suffix_map.get(adjust, "qfq")
    data_key = key_map[suffix]

    start_ts = pd.Timestamp(_date_fmt(start_date))
    end_ts = pd.Timestamp(_date_fmt(end_date))
    records: list[dict[str, str]] = []

    for year in range(start_ts.year, end_ts.year + 1):
        chunk_start = max(start_ts, pd.Timestamp(year, 1, 1))
        chunk_end = min(end_ts, pd.Timestamp(year, 12, 31))
        if chunk_start > chunk_end:
            continue
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        param = f"{sina_symbol},day,{s},{e},640,{suffix}"
        resp = requests.get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": param},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()["data"][sina_symbol][data_key]
        for row in rows:
            records.append(
                {
                    "date": row[0],
                    "open": row[1],
                    "close": row[2],
                    "high": row[3],
                    "low": row[4],
                    "volume": row[5],
                }
            )

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["symbol"] = SYMBOL
    return _standardize_ohlcv(df, SYMBOL)


def fetch_etf_daily(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str = ADJUST,
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """拉取 ETF 前复权日线.

    优先级（均在数据层指定 adjust，与 akquant 文档一致）：
      1. ak.fund_etf_hist_em(..., adjust=adjust)  — 官方 ETF 示例
      2. 腾讯财经 qfqday                           — 东财网络失败时回退
    """
    fetch_start = start_date or "19900101"
    fetch_end = end_date or DATA_END
    req_start = pd.Timestamp(_to_ts(fetch_start, "00:00:00"))

    df: pd.DataFrame | None = None
    if use_cache and not refresh and CACHE_PATH.exists():
        cached = pd.read_parquet(CACHE_PATH)
        cached["date"] = pd.to_datetime(cached["date"])
        if cached["date"].min() <= req_start:
            print(f"使用本地缓存: {CACHE_PATH.name}（{len(cached)} 天，adjust={adjust}）")
            df = cached
        else:
            print(
                f"缓存起始于 {cached['date'].min().date()}，不覆盖 {fetch_start}，重新拉取 …"
            )

    if df is None:
        source = ""
        errors: list[str] = []

        # ① akquant 推荐：ETF 用 fund_etf_hist_em(adjust="qfq")
        try:
            df = _fetch_etf_hist_em(symbol, fetch_start, fetch_end, adjust=adjust)
            source = f"东财 ETF 日线 adjust={adjust}"
        except Exception as exc:
            errors.append(f"东财: {exc}")

        # ② 回退：腾讯前复权（与行情软件一致）
        if (df is None or df.empty) and adjust == "qfq":
            try:
                df = _fetch_tencent_daily(SINA_SYMBOL, fetch_start, fetch_end, adjust="qfq")
                source = "腾讯财经 前复权（东财不可用）"
            except Exception as exc:
                errors.append(f"腾讯: {exc}")

        if df is None or df.empty:
            msg = "\n".join(f"    · {e}" for e in errors)
            raise RuntimeError(f"无法获取 ETF 前复权日线（adjust={adjust}）:\n{msg}")

        if use_cache:
            df.to_parquet(CACHE_PATH, index=False)
            print(f"已缓存: {CACHE_PATH.name}（{len(df)} 天，来源: {source}）")

    if start_date:
        start = pd.Timestamp(_to_ts(start_date, "00:00:00"))
        df = df[df["date"] >= start]
    if end_date:
        end = pd.Timestamp(_to_ts(end_date, "23:59:59"))
        df = df[df["date"] <= end]
    return cast(pd.DataFrame, df.reset_index(drop=True))


def _standardize_minute_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """统一分钟/30分钟 OHLCV 为 date + ohlcv + symbol."""
    rename_map = {
        "时间": "date", "day": "date", "datetime": "date",
        "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume",
    }
    out = df.rename(columns=rename_map).copy()
    required = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"分钟线缺少列 {missing}，实际: {out.columns.tolist()}")
    out = out[required].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in required[1:]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["symbol"] = symbol
    return cast(pd.DataFrame, out)


def _fetch_em_30m_chunk(
    symbol: str,
    start_dt: str,
    end_dt: str,
    adjust: str = ADJUST,
) -> pd.DataFrame:
    """东财 ETF 30 分钟（单段）."""
    raw = ak.fund_etf_hist_min_em(
        symbol=symbol,
        period=MIN30_PERIOD,
        start_date=start_dt,
        end_date=end_dt,
        adjust=adjust,
    )
    if raw.empty:
        return pd.DataFrame()
    return _standardize_minute_ohlcv(raw, symbol)


def _fetch_sina_30m(sina_symbol: str, adjust: str = ADJUST) -> pd.DataFrame:
    """新浪 30 分钟（近若干个月，接口返回长度有限）."""
    raw = ak.stock_zh_a_minute(symbol=sina_symbol, period=MIN30_PERIOD, adjust=adjust)
    if raw.empty:
        return pd.DataFrame()
    return _standardize_minute_ohlcv(raw, SYMBOL)


def fetch_etf_30m(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str = ADJUST,
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """拉取 ETF 30 分钟前复权 K 线（新浪快速回退 + 东财按月补充，Parquet 缓存）."""
    fetch_start = start_date or DATA_START
    fetch_end = end_date or DATA_END
    req_start = pd.Timestamp(_to_ts(fetch_start, "09:30:00"))
    req_end = pd.Timestamp(_to_ts(fetch_end, "15:00:00"))

    if use_cache and not refresh and MIN30_CACHE_PATH.exists():
        cached = pd.read_parquet(MIN30_CACHE_PATH)
        cached["date"] = pd.to_datetime(cached["date"])
        clipped = cached[(cached["date"] >= req_start) & (cached["date"] <= req_end)]
        if not clipped.empty:
            print(
                f"使用本地 30 分钟缓存: {MIN30_CACHE_PATH.name}（{len(clipped)} 根，"
                f"{clipped['date'].min()} ~ {clipped['date'].max()}）"
            )
            return cast(pd.DataFrame, clipped.reset_index(drop=True))

    frames: list[pd.DataFrame] = []
    errors: list[str] = []

    try:
        sina_df = _fetch_sina_30m(SINA_SYMBOL, adjust=adjust)
        if not sina_df.empty:
            frames.append(sina_df)
    except Exception as exc:
        errors.append(f"新浪: {exc}")

    sina_covers = (
        not frames
        or pd.to_datetime(frames[0]["date"]).min() <= req_start + pd.Timedelta(days=7)
    )
    if refresh or not sina_covers:
        cursor = pd.Timestamp(req_start.year, req_start.month, 1)
        consecutive_fail = 0
        while cursor <= req_end and consecutive_fail < 3:
            month_end = (cursor + pd.offsets.MonthEnd(0)).normalize() + pd.Timedelta(hours=15)
            chunk_end = min(month_end, req_end)
            start_dt = max(cursor, req_start).strftime("%Y-%m-%d %H:%M:%S")
            end_dt = chunk_end.strftime("%Y-%m-%d %H:%M:%S")
            try:
                chunk = _fetch_em_30m_chunk(symbol, start_dt, end_dt, adjust=adjust)
                if chunk.empty:
                    consecutive_fail += 1
                else:
                    frames.append(chunk)
                    consecutive_fail = 0
            except Exception as exc:
                consecutive_fail += 1
                errors.append(f"{start_dt[:7]}: {exc}")
            cursor = (cursor + pd.offsets.MonthBegin(1)).normalize()

    if not frames:
        msg = "\n".join(f"    · {e}" for e in errors[-6:])
        raise RuntimeError(f"无法获取 ETF 30 分钟线（adjust={adjust}）:\n{msg}")

    df = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    if use_cache:
        df.to_parquet(MIN30_CACHE_PATH, index=False)
        print(
            f"已缓存 30 分钟线: {MIN30_CACHE_PATH.name}（{len(df)} 根，"
            f"{df['date'].min()} ~ {df['date'].max()}）"
        )

    out = df[(df["date"] >= req_start) & (df["date"] <= req_end)]
    return cast(pd.DataFrame, out.reset_index(drop=True))


def min30_to_akquant(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """30 分钟线 → akquant 格式（保留真实 bar 时间戳）."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = symbol
    required = ["date", "open", "high", "low", "close", "volume", "symbol"]
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return cast(pd.DataFrame, out[required])


def daily_to_akquant(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """日线 → akquant 格式（每根 K 线时间戳为当日 15:00 收盘）."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize() + pd.Timedelta(hours=15)
    out["symbol"] = symbol
    required = ["date", "open", "high", "low", "close", "volume", "symbol"]
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return cast(pd.DataFrame, out[required])


def print_buy_hold_pnl(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> dict[str, float | int | dt.date]:
    """无策略：首日开盘买入并持有至最新收盘."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")

    entry_row = daily[daily["date"] >= entry_date].head(1)
    if entry_row.empty:
        raise ValueError(f"日线数据中没有 {entry_date} 及之后的交易日")
    exit_row = daily[daily["date"] <= end_date].tail(1)
    if exit_row.empty:
        raise ValueError(f"日线数据中没有 {end_date} 及之前的交易日")

    entry = entry_row.iloc[0]
    exit_ = exit_row.iloc[0]
    entry_price = float(entry["open"])
    exit_price = float(exit_["close"])
    qty = round_lot(initial_cash * 0.98 / entry_price)
    cost = entry_price * qty
    value = exit_price * qty
    pnl = value - cost
    pct = pnl / cost * 100 if cost else 0.0

    print("\n=== 无策略 · 买入持有 ===")
    print(f"  买入日:   {entry['date']}  (开盘价)")
    print(f"  买入价:   {entry_price:.3f} 元")
    print(f"  持仓:     {qty} 股")
    print(f"  买入成本: {cost:,.2f} 元")
    print(f"  现价日:   {exit_['date']}  收盘")
    print(f"  现价:     {exit_price:.3f} 元")
    print(f"  市值:     {value:,.2f} 元")
    print(f"  盈亏:     {pnl:+,.2f} 元 ({pct:+.2f}%)")
    return {
        "entry_date": entry["date"],
        "exit_date": exit_["date"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": qty,
        "pnl": pnl,
        "pct": pct,
    }


def compute_reversal_indicators(daily_df: pd.DataFrame) -> pd.DataFrame:
    """计算反转因子：20日跌幅、RSI、20日高点回撤."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["ret20"] = daily["close"] / daily["close"].shift(LOOKBACK) - 1
    delta = daily["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    daily["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    daily["high20"] = daily["high"].rolling(LOOKBACK).max()
    daily["dd20"] = daily["close"] / daily["high20"] - 1
    daily["ret1"] = daily["close"].pct_change()
    return daily


def _filter_label(
    filter_logic: str,
    rsi_max: float,
    min_dd20: float,
    *,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
) -> str:
    parts: list[str] = []
    if filter_mode == "score":
        parts.append(f"评分>={min_score}")
    elif filter_mode == "classic" and min_dd20 < 1.0:
        dd_pct = abs(min_dd20) * 100
        if filter_logic == "or":
            parts.append(f"RSI<={rsi_max:.0f} 或 dd20<=-{dd_pct:.0f}%")
        else:
            parts.append(f"RSI<={rsi_max:.0f} 且 dd20<=-{dd_pct:.0f}%")
    if max_rsi < 9000:
        parts.append(f"排除RSI>{max_rsi:.0f}")
    return " + ".join(parts) if parts else "无过滤"


def compute_signal_score(feat: dict[str, float] | None, daily_ret: float) -> int:
    """反转质量评分：RSI 越低、回撤越深、20日越弱、当日涨幅越大 → 分越高."""
    if not feat:
        return 0
    score = 0
    rsi, dd20, ret20 = feat["rsi"], feat["dd20"], feat["ret20"]
    if pd.notna(rsi):
        if rsi <= 30:
            score += 35
        elif rsi <= 40:
            score += 25
        elif rsi <= 50:
            score += 15
    if pd.notna(dd20):
        if dd20 <= -0.10:
            score += 30
        elif dd20 <= -0.08:
            score += 22
        elif dd20 <= -0.05:
            score += 12
        elif dd20 <= -0.03:
            score += 5
    if pd.notna(ret20):
        if ret20 <= -0.10:
            score += 20
        elif ret20 <= -0.05:
            score += 12
        elif ret20 <= -0.02:
            score += 5
    if daily_ret >= 0.03:
        score += 20
    elif daily_ret >= 0.02:
        score += 12
    elif daily_ret >= 0.015:
        score += 6
    return score


def passes_entry_filter(
    feat: dict[str, float] | None,
    daily_ret: float,
    *,
    filter_mode: str = FILTER_MODE,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
) -> tuple[bool, str]:
    """入场过滤：经典反转 / 评分 / 无过滤 + 可选排除追高."""
    if not feat:
        return False, "无指标"
    rsi, dd20, ret20 = feat["rsi"], feat["dd20"], feat["ret20"]
    if pd.isna(rsi):
        return False, "RSI不足"
    if max_rsi < 9000 and rsi > max_rsi:
        return False, f"RSI={rsi:.1f}>追高上限{max_rsi:.0f}"

    if filter_mode == "score":
        score = compute_signal_score(feat, daily_ret)
        if score < min_score:
            return False, f"评分={score}<{min_score}"
        return True, f"评分={score} RSI={rsi:.1f} dd20={dd20 * 100:.1f}%"

    if filter_mode == "classic" and min_dd20 < 1.0:
        ok, reason = passes_reversal_filter(
            feat, rsi_max=rsi_max, min_dd20=min_dd20, filter_logic=filter_logic
        )
        if not ok:
            return False, reason

    return True, f"RSI={rsi:.1f} ret20={ret20 * 100:+.1f}% dd20={dd20 * 100:.1f}%"


def passes_reversal_filter(
    feat: dict[str, float] | None,
    *,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
) -> tuple[bool, str]:
    """判断单日特征是否通过反转过滤."""
    if not feat:
        return False, "无指标"
    rsi, dd20, ret20 = feat["rsi"], feat["dd20"], feat["ret20"]
    if pd.isna(rsi) or pd.isna(dd20):
        return False, "指标不足"
    rsi_ok = rsi <= rsi_max
    dd_ok = dd20 <= min_dd20
    if filter_logic == "or":
        passed = rsi_ok or dd_ok
        if not passed:
            return False, f"RSI={rsi:.1f}>上限且dd20={dd20 * 100:.1f}%未达回撤"
    else:
        passed = rsi_ok and dd_ok
        if not rsi_ok:
            return False, f"RSI={rsi:.1f}>上限"
        if not dd_ok:
            return False, f"dd20={dd20 * 100:.1f}%未达回撤"
    return True, f"RSI={rsi:.1f} ret20={ret20 * 100:+.1f}% dd20={dd20 * 100:.1f}%"


def build_reversal_feature_map(
    daily_df: pd.DataFrame,
) -> dict[dt.date, dict[str, float]]:
    """date → {ret20, rsi, dd20}."""
    daily = compute_reversal_indicators(daily_df)
    feat_map: dict[dt.date, dict[str, float]] = {}
    for _, row in daily.iterrows():
        bar_date = pd.Timestamp(row["date"]).date()
        feat_map[bar_date] = {
            "ret20": float(row["ret20"]) if pd.notna(row["ret20"]) else float("nan"),
            "rsi": float(row["rsi"]) if pd.notna(row["rsi"]) else float("nan"),
            "dd20": float(row["dd20"]) if pd.notna(row["dd20"]) else float("nan"),
        }
    return feat_map


def _signal_trade_returns(
    daily_df: pd.DataFrame,
    hold_days: int = HOLD_DAYS,
    gain_threshold: float = GAIN_THRESHOLD,
) -> pd.DataFrame:
    """所有「突然上涨」信号的持 hold_days 日收益（用于因子分析）."""
    daily = compute_reversal_indicators(daily_df)
    rows: list[dict[str, float | dt.date]] = []
    for i in range(LOOKBACK + 1, len(daily) - hold_days):
        row = daily.iloc[i]
        bar_date = pd.Timestamp(row["date"]).date()
        if bar_date < BACKTEST_START:
            continue
        if row["ret1"] < gain_threshold:
            continue
        entry = float(row["close"])
        exit_ = float(daily.iloc[i + hold_days]["close"])
        rows.append(
            {
                "date": bar_date,
                "ret": exit_ / entry - 1,
                "ret20": float(row["ret20"]),
                "rsi": float(row["rsi"]),
                "dd20": float(row["dd20"]),
            }
        )
    return pd.DataFrame(rows)


def _mask_filtered_signals(
    sig: pd.DataFrame,
    *,
    rsi_max: float,
    min_dd20: float,
    filter_logic: str,
) -> pd.Series:
    rsi_ok = sig["rsi"] <= rsi_max
    dd_ok = sig["dd20"] <= min_dd20
    if filter_logic == "or":
        return rsi_ok | dd_ok
    return rsi_ok & dd_ok


def print_reversal_factor_analysis(daily_df: pd.DataFrame) -> None:
    """按用户建议的三类因子，统计信号收益分布."""
    sig = _signal_trade_returns(daily_df)
    if sig.empty:
        print("\n（无足够信号用于因子分析）")
        return

    print(f"\n=== 反转因子分析（所有 +{GAIN_THRESHOLD * 100:.1f}% 信号，持{HOLD_DAYS}日）===")
    print(f"  样本信号数: {len(sig)}")
    print(f"  全样本均收益: {sig['ret'].mean() * 100:+.2f}%  胜率: {(sig['ret'] > 0).mean() * 100:.1f}%")

    print("\n  【1】买入前 20 日跌幅 ret20")
    for thr in [0, -0.05, -0.08, -0.10, -0.15, -0.20]:
        sub = sig[sig["ret20"] <= thr]
        if len(sub) < 3:
            continue
        print(
            f"    ret20<={thr * 100:.0f}%: n={len(sub):3d}  "
            f"均收益={sub['ret'].mean() * 100:+.2f}%  "
            f"胜率={(sub['ret'] > 0).mean() * 100:.1f}%"
        )

    print("\n  【2】买入日 RSI")
    for lo, hi, label in [
        (0, 30, "超卖 <=30"),
        (0, 40, "偏低 <=40"),
        (0, 50, "非超买 <=50"),
        (0, 55, "放宽 <=55"),
        (50, 100, "偏高 >50"),
    ]:
        sub = sig[(sig["rsi"] >= lo) & (sig["rsi"] <= hi)]
        if len(sub) < 3:
            continue
        print(
            f"    RSI {label}: n={len(sub):3d}  "
            f"均收益={sub['ret'].mean() * 100:+.2f}%  "
            f"胜率={(sub['ret'] > 0).mean() * 100:.1f}%"
        )

    print("\n  【3】距 20 日最高点回撤 dd20")
    for thr in [-0.03, -0.05, -0.08, -0.10, -0.15]:
        sub = sig[sig["dd20"] <= thr]
        if len(sub) < 3:
            continue
        print(
            f"    dd20<={thr * 100:.0f}%: n={len(sub):3d}  "
            f"均收益={sub['ret'].mean() * 100:+.2f}%  "
            f"胜率={(sub['ret'] > 0).mean() * 100:.1f}%"
        )

    print("\n  【4】过滤逻辑对比（当前持仓天数）")
    for logic, rsi_max in [("and", 50), ("and", 55), ("or", 50), ("or", 55)]:
        mask = _mask_filtered_signals(
            sig, rsi_max=rsi_max, min_dd20=MIN_DD20, filter_logic=logic
        )
        passed = sig[mask]
        if passed.empty:
            continue
        label = _filter_label(logic, rsi_max, MIN_DD20)
        print(
            f"    {label}: n={len(passed):3d}  "
            f"均收益={passed['ret'].mean() * 100:+.2f}%  "
            f"胜率={(passed['ret'] > 0).mean() * 100:.1f}%"
        )

    cur = sig[
        _mask_filtered_signals(
            sig,
            rsi_max=RSI_MAX,
            min_dd20=MIN_DD20,
            filter_logic=FILTER_LOGIC,
        )
    ]
    cur_label = _filter_label(FILTER_LOGIC, RSI_MAX, MIN_DD20)
    print(
        f"\n  【当前策略过滤】{cur_label}: "
        f"n={len(cur)}  均收益={cur['ret'].mean() * 100:+.2f}%  "
        f"胜率={(cur['ret'] > 0).mean() * 100:.1f}%"
        if not cur.empty
        else f"\n  【当前策略过滤】无样本"
    )


class ShortTermReversalStrategy(Strategy):
    """突然上涨 + 反转确认；牛市满仓持有，熊市才做短线 + 可选价格门控."""

    def __init__(
        self,
        backtest_start: dt.date,
        feature_map: dict[dt.date, dict[str, float]] | None = None,
        hold_days: int = HOLD_DAYS,
        rsi_max: float = RSI_MAX,
        min_dd20: float = MIN_DD20,
        filter_logic: str = FILTER_LOGIC,
        filter_mode: str = FILTER_MODE,
        min_score: int = MIN_SCORE,
        max_rsi: float = MAX_RSI,
        stop_loss_pct: float = STOP_LOSS_PCT,
        take_profit_pct: float = TAKE_PROFIT_PCT,
        gain_threshold: float = GAIN_THRESHOLD,
        use_30m_sltp: bool = False,
        price_hold_below: float = PRICE_HOLD_BELOW,
        price_strategy_above: float = PRICE_STRATEGY_ABOVE,
        enable_price_regime: bool = ENABLE_PRICE_REGIME,
        enable_adaptive_regime: bool = ENABLE_ADAPTIVE_REGIME,
        bull_ret20_threshold: float = BULL_RET20_THRESHOLD,
        quiet: bool = False,
    ) -> None:
        super().__init__()
        self.backtest_start = backtest_start
        self.feature_map = feature_map or {}
        self.hold_days = hold_days
        self.rsi_max = rsi_max
        self.min_dd20 = min_dd20
        self.filter_logic = filter_logic
        self.filter_mode = filter_mode
        self.min_score = min_score
        self.max_rsi = max_rsi
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.gain_threshold = gain_threshold
        self.use_30m_sltp = use_30m_sltp
        self.price_hold_below = price_hold_below
        self.price_strategy_above = price_strategy_above
        self.enable_price_regime = enable_price_regime
        self.enable_adaptive_regime = enable_adaptive_regime
        self.bull_ret20_threshold = bull_ret20_threshold
        self.quiet = quiet
        self.strategy_active: bool | None = None if enable_price_regime else True
        self.prev_close: float | None = None
        self.holding = False
        self.bars_until_sell = 0
        self.entry_price: float | None = None

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _bar_ts(self, bar) -> pd.Timestamp:
        return self.to_local_time(bar.timestamp)

    def _bar_date(self, bar) -> dt.date:
        return self._bar_ts(bar).date()

    def _is_eod_bar(self, bar) -> bool:
        """A 股 30 分钟最后一根 K 线（15:00）≈ 日线收盘."""
        ts = self._bar_ts(bar)
        return (ts.hour, ts.minute) == EOD_BAR_HM

    def _daily_ret(self, close: float) -> float | None:
        if self.prev_close is None or self.prev_close <= 0:
            return None
        return (close - self.prev_close) / self.prev_close

    def _passes_entry_filter(self, bar_date: dt.date, daily_ret: float) -> tuple[bool, str]:
        return passes_entry_filter(
            self.feature_map.get(bar_date),
            daily_ret,
            filter_mode=self.filter_mode,
            rsi_max=self.rsi_max,
            min_dd20=self.min_dd20,
            filter_logic=self.filter_logic,
            min_score=self.min_score,
            max_rsi=self.max_rsi,
        )

    def _close_position_at_bar(self, bar, ts: pd.Timestamp, reason: str) -> None:
        pos = int(self.get_position(bar.symbol))
        if pos > 0:
            self.close_position(symbol=bar.symbol)
            stamp = ts.strftime("%Y-%m-%d %H:%M") if self.use_30m_sltp else ts.strftime("%Y-%m-%d")
            self._log(f"[{stamp}] {reason} {pos} 股 @ {bar.close:.3f}")
        self.holding = False
        self.bars_until_sell = 0
        self.entry_price = None

    def _check_sltp(self, bar, ts: pd.Timestamp) -> bool:
        """30 分钟（或日线）收盘价检查止盈止损."""
        if not self.holding or not self.entry_price or self.entry_price <= 0:
            return False
        if self.stop_loss_pct <= 0 and self.take_profit_pct <= 0:
            return False
        pnl_pct = (bar.close - self.entry_price) / self.entry_price
        tag = "30分钟" if self.use_30m_sltp else "日线"
        if self.stop_loss_pct > 0 and pnl_pct <= -self.stop_loss_pct:
            self._close_position_at_bar(
                bar, ts, f"{tag}止损({self.stop_loss_pct * 100:.0f}%)收盘卖出"
            )
            return True
        if self.take_profit_pct > 0 and pnl_pct >= self.take_profit_pct:
            self._close_position_at_bar(
                bar, ts, f"{tag}止盈({self.take_profit_pct * 100:.0f}%)收盘卖出"
            )
            return True
        return False

    def _is_bull_market(self, bar_date: dt.date) -> bool:
        """20 日收益 > 阈值 → 牛市，满仓持有、不做战术交易."""
        if not self.enable_adaptive_regime:
            return False
        feat = self.feature_map.get(bar_date)
        if not feat:
            return False
        ret20 = feat.get("ret20")
        return pd.notna(ret20) and ret20 > self.bull_ret20_threshold

    def _apply_full_hold(self, bar, ts: pd.Timestamp, reason: str = "牛市") -> None:
        pos_before = int(self.get_position(bar.symbol))
        self.order_target_percent(
            symbol=bar.symbol,
            target_percent=CASH_BUFFER,
            fill_mode=FILL_MODE,
        )
        pos_after = int(self.get_position(bar.symbol))
        delta = pos_after - pos_before
        if abs(delta) >= LOT_SIZE:
            action = "加仓" if delta > 0 else "减仓"
            self._log(
                f"[{ts.strftime('%Y-%m-%d')}] {reason}：{action} {abs(delta)} 股 "
                f"@ {bar.close:.3f} → 满仓 {CASH_BUFFER * 100:.0f}%"
            )

    def _ensure_full_hold(self, bar, ts: pd.Timestamp) -> None:
        """持有模式：调仓至满仓（<5 元）或价格目标."""
        target = price_target_position_pct(bar.close)
        if target is None:
            self._apply_full_hold(bar, ts, reason="持有模式")
            return
        self._apply_price_position_target(bar, ts, force=True, target_override=target)

    def _apply_price_position_target(
        self, bar, ts: pd.Timestamp, *, force: bool = False, target_override: float | None = None
    ) -> None:
        """按收盘价将仓位调整至目标比例."""
        if not self.enable_price_regime:
            return
        if self.holding and not force:
            return
        target = (
            target_override
            if target_override is not None
            else price_target_position_pct(bar.close)
        )
        if target is None:
            return
        pos_before = int(self.get_position(bar.symbol))
        self.order_target_percent(
            symbol=bar.symbol,
            target_percent=target,
            fill_mode=FILL_MODE,
        )
        pos_after = int(self.get_position(bar.symbol))
        delta = pos_after - pos_before
        if abs(delta) >= LOT_SIZE:
            action = "加仓" if delta > 0 else "减仓"
            self._log(
                f"[{ts.strftime('%Y-%m-%d')}] 价格仓位：{action} {abs(delta)} 股 "
                f"@ {bar.close:.3f} → 目标 {target * 100:.0f}%"
            )

    def _update_price_regime(self, bar, ts: pd.Timestamp) -> None:
        """< 5 元持有；> 7 元策略；5~7 元保持上一状态."""
        close = bar.close
        if self.strategy_active is None:
            self.strategy_active = close > self.price_strategy_above
            mode = "策略模式" if self.strategy_active else "持有模式"
            self._log(
                f"[{ts.strftime('%Y-%m-%d')}] 初始：收盘 {close:.3f}，"
                f"{'>' if self.strategy_active else '≤'} {self.price_strategy_above} → {mode}"
            )
            return

        if not self.strategy_active and close > self.price_strategy_above:
            self.strategy_active = True
            self._log(
                f"[{ts.strftime('%Y-%m-%d')}] 收盘 {close:.3f} > {self.price_strategy_above}，"
                f"启动策略交易"
            )
            pos = int(self.get_position(bar.symbol))
            if pos > 0 and not self.holding:
                self.holding = True
                self.entry_price = close
                self.bars_until_sell = self.hold_days
                self._log(
                    f"  继承持有仓位 {pos} 股，纳入策略管理（{self.hold_days} 日计时）"
                )
        elif self.strategy_active and close < self.price_hold_below:
            self.strategy_active = False
            self._log(
                f"[{ts.strftime('%Y-%m-%d')}] 收盘 {close:.3f} < {self.price_hold_below}，"
                f"转入买入持有"
            )
            self.holding = False
            self.bars_until_sell = 0
            self.entry_price = None

    def on_bar(self, bar) -> None:
        ts = self._bar_ts(bar)
        bar_date = ts.date()
        is_eod = (not self.use_30m_sltp) or self._is_eod_bar(bar)

        if is_eod and bar_date >= self.backtest_start and self.enable_price_regime:
            self._update_price_regime(bar, ts)

        if is_eod and bar_date >= self.backtest_start and self._is_bull_market(bar_date):
            if self.holding:
                self.holding = False
                self.bars_until_sell = 0
                self.entry_price = None
            self._apply_full_hold(bar, ts, reason="牛市")
            self.prev_close = bar.close
            return

        if (
            is_eod
            and bar_date >= self.backtest_start
            and self.enable_price_regime
            and not self.strategy_active
        ):
            self._apply_price_position_target(bar, ts, force=True)
            self.holding = False
            self.bars_until_sell = 0
            self.entry_price = None
            self.prev_close = bar.close
            return

        if self.holding:
            if self.use_30m_sltp:
                if self._check_sltp(bar, ts):
                    self.prev_close = bar.close if is_eod else self.prev_close
                    return
            elif is_eod and self._check_sltp(bar, ts):
                return

            if is_eod and self.bars_until_sell > 0:
                self.bars_until_sell -= 1
                if self.bars_until_sell == 0:
                    self._close_position_at_bar(
                        bar, ts, f"持股{self.hold_days}日尾盘收盘卖出"
                    )

        if (
            is_eod
            and bar_date >= self.backtest_start
            and not self.holding
        ):
            ret = self._daily_ret(bar.close)
            if ret is not None and ret >= self.gain_threshold:
                ok, reason = self._passes_entry_filter(bar_date, ret)
                if ok:
                    target = price_target_position_pct(bar.close)
                    if target is None:
                        target = CASH_BUFFER
                    if target > 0:
                        self.order_target_percent(
                            symbol=bar.symbol,
                            target_percent=target,
                            fill_mode=FILL_MODE,
                        )
                        self.holding = True
                        self.bars_until_sell = self.hold_days
                        self.entry_price = bar.close
                        qty = int(self.get_position(bar.symbol))
                        self._log(
                            f"[{ts.strftime('%Y-%m-%d')}] 反转信号：+{ret * 100:.2f}% "
                            f"({reason}) → 尾盘收盘买入至 {target * 100:.0f}% "
                            f"({qty} 股) @ {bar.close:.3f}"
                        )

        if is_eod and bar_date >= self.backtest_start and self.enable_price_regime:
            self._apply_price_position_target(bar, ts)

        if is_eod:
            self.prev_close = bar.close


def build_benchmark_returns(df: pd.DataFrame) -> pd.Series:
    daily = df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()
    return daily["close"].pct_change().fillna(0.0).rename("510500_BENCH")


def monthly_returns_from_equity(equity: pd.Series, from_date: dt.date) -> pd.DataFrame:
    """按自然月计算权益变动：当月末权益 / 上月末权益 - 1（非年化平均）."""
    eq = equity.sort_index().copy()
    eq.index = pd.to_datetime(eq.index)
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")

    month_ends = eq.groupby(eq.index.to_period("M")).last()
    from_period = pd.Period(from_date, freq="M")

    rows: list[dict[str, float | int | str]] = []
    prev_end: float | None = None
    for period in sorted(month_ends.index):
        end_val = float(month_ends.loc[period])
        if period < from_period:
            prev_end = end_val
            continue
        if prev_end is None:
            chunk = eq[eq.index.to_period("M") == period]
            start_val = float(chunk.iloc[0])
        else:
            start_val = prev_end
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append(
            {
                "period": str(period),
                "year": period.year,
                "month": period.month,
                "return_pct": ret_pct,
                "pnl": end_val - start_val,
                "end_equity": end_val,
            }
        )
        prev_end = end_val
    return pd.DataFrame(rows)


def monthly_returns_buy_hold(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> pd.DataFrame:
    """买入持有：各自然月按月末市值相对上月末（首月为买入成本）."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    if entry_row.empty:
        return pd.DataFrame()

    entry_price = float(entry_row.iloc[0]["open"])
    qty = round_lot(initial_cash * 0.98 / entry_price)
    entry_cost = entry_price * qty

    sub = daily[(daily["date"] >= entry_date) & (daily["date"] <= end_date)].copy()
    sub["value"] = qty * sub["close"].astype(float)
    sub["period"] = pd.to_datetime(sub["date"]).dt.to_period("M")
    month_ends = sub.groupby("period").last()

    from_period = pd.Period(entry_date, freq="M")
    rows: list[dict[str, float | str]] = []
    prev_end: float | None = None
    for period in sorted(month_ends.index):
        end_val = float(month_ends.loc[period]["value"])
        if period < from_period:
            prev_end = end_val
            continue
        start_val = entry_cost if prev_end is None else prev_end
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append({"period": str(period), "return_pct": ret_pct})
        prev_end = end_val
    return pd.DataFrame(rows)


def monthly_closed_trade_count(
    trades: pd.DataFrame, from_date: dt.date
) -> dict[str, int]:
    if trades.empty:
        return {}
    exit_periods = pd.to_datetime(trades["exit_time"]).dt.to_period("M")
    from_period = pd.Period(from_date, freq="M")
    counts = exit_periods[exit_periods >= from_period].value_counts()
    return {str(p): int(c) for p, c in counts.items()}


def print_monthly_returns(
    result: aq.BacktestResult,
    daily_df: pd.DataFrame,
    backtest_start: dt.date,
    end_date: dt.date,
) -> None:
    strat = monthly_returns_from_equity(result.equity_curve, backtest_start)
    bh = monthly_returns_buy_hold(daily_df, backtest_start, end_date)
    trade_counts = monthly_closed_trade_count(result.trades_df, backtest_start)
    bh_map = {str(r["period"]): float(r["return_pct"]) for _, r in bh.iterrows()}

    print("\n=== 分月度收益（日历月末口径，非年化平均）===")
    print(
        f"  {'月份':<8} {'策略收益':>10} {'买入持有':>10} "
        f"{'策略盈亏(元)':>14} {'平仓笔数':>8}"
    )
    print("  " + "-" * 58)

    last_year: int | None = None
    for _, row in strat.iterrows():
        year = int(row["year"])
        if last_year is not None and year != last_year:
            print()
        last_year = year
        period = str(row["period"])
        bh_pct = bh_map.get(period)
        bh_str = f"{bh_pct:+10.2f}%" if bh_pct is not None else "       n/a"
        n_trades = trade_counts.get(period, 0)
        print(
            f"  {period:<8} {row['return_pct']:+10.2f}% {bh_str} "
            f"{row['pnl']:+14,.0f} {n_trades:>8}"
        )
    print(
        "\n  说明：策略各月收益 = 当月末权益 / 上月末权益 - 1；"
        "买入持有首月起点为回测首日买入成本。"
    )


def yearly_returns_from_equity(equity: pd.Series, from_year: int) -> pd.DataFrame:
    """按自然年计算权益变动：当年末权益 / 上年末权益 - 1（非年化平均）."""
    eq = equity.sort_index().copy()
    eq.index = pd.to_datetime(eq.index)
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")

    year_ends = eq.groupby(eq.index.year).last()
    rows: list[dict[str, float | int]] = []
    for year in year_ends.index:
        if year < from_year:
            continue
        end_val = float(year_ends.loc[year])
        prev_year = year - 1
        if prev_year in year_ends.index:
            start_val = float(year_ends.loc[prev_year])
        else:
            start_val = float(eq[eq.index.year == year].iloc[0])
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append(
            {
                "year": year,
                "start_equity": start_val,
                "end_equity": end_val,
                "return_pct": ret_pct,
                "pnl": end_val - start_val,
            }
        )
    return pd.DataFrame(rows)


def yearly_returns_buy_hold(
    daily_df: pd.DataFrame,
    entry_date: dt.date,
    end_date: dt.date,
    initial_cash: float = INITIAL_CASH,
) -> pd.DataFrame:
    """买入持有：各自然年按年末市值相对上年末（首年为买入成本）."""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily.sort_values("date")
    entry_row = daily[daily["date"] >= entry_date].head(1)
    if entry_row.empty:
        return pd.DataFrame()

    entry_price = float(entry_row.iloc[0]["open"])
    qty = round_lot(initial_cash * 0.98 / entry_price)
    entry_cost = entry_price * qty

    sub = daily[(daily["date"] >= entry_date) & (daily["date"] <= end_date)].copy()
    sub["value"] = qty * sub["close"].astype(float)
    year_ends = sub.groupby(sub["date"].apply(lambda d: d.year)).last()

    rows: list[dict[str, float | int]] = []
    for year in year_ends.index:
        end_val = float(year_ends.loc[year]["value"])
        prev_year = year - 1
        if prev_year in year_ends.index:
            start_val = float(year_ends.loc[prev_year]["value"])
        else:
            start_val = entry_cost
        ret_pct = (end_val / start_val - 1) * 100 if start_val else 0.0
        rows.append({"year": year, "return_pct": ret_pct, "end_value": end_val})
    return pd.DataFrame(rows)


def yearly_closed_trade_count(trades: pd.DataFrame, from_year: int) -> dict[int, int]:
    if trades.empty:
        return {}
    years = pd.to_datetime(trades["exit_time"]).dt.year
    counts = years[years >= from_year].value_counts()
    return {int(y): int(c) for y, c in counts.items()}


def print_yearly_returns(
    result: aq.BacktestResult,
    daily_df: pd.DataFrame,
    backtest_start: dt.date,
    end_date: dt.date,
) -> None:
    from_year = backtest_start.year
    strat = yearly_returns_from_equity(result.equity_curve, from_year)
    bh = yearly_returns_buy_hold(daily_df, backtest_start, end_date)
    trade_counts = yearly_closed_trade_count(result.trades_df, from_year)
    bh_map = {int(r["year"]): float(r["return_pct"]) for _, r in bh.iterrows()}

    print("\n=== 分年度收益（日历年末口径，非年化平均）===")
    print(
        f"  {'年份':<6} {'策略收益':>10} {'买入持有':>10} "
        f"{'策略盈亏(元)':>14} {'平仓笔数':>8}"
    )
    print("  " + "-" * 56)
    for _, row in strat.iterrows():
        year = int(row["year"])
        bh_pct = bh_map.get(year)
        bh_str = f"{bh_pct:+10.2f}%" if bh_pct is not None else "       n/a"
        n_trades = trade_counts.get(year, 0)
        print(
            f"  {year:<6} {row['return_pct']:+10.2f}% {bh_str} "
            f"{row['pnl']:+14,.0f} {n_trades:>8}"
        )
    print(
        "\n  说明：策略各年收益 = 当年末权益 / 上年末权益 - 1；"
        "买入持有首年起点为回测首日买入成本。"
    )


def print_trade_details(
    trades: pd.DataFrame,
    *,
    hold_days: int = HOLD_DAYS,
    gain_threshold: float = GAIN_THRESHOLD,
    filter_logic: str = FILTER_LOGIC,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
) -> None:
    """逐笔打印：买入=信号日收盘价，卖出=到期/止盈止损收盘价."""
    if trades.empty:
        print("\n（无完整买卖回合，可能区间内未触发信号）")
        return

    print(f"\n=== 交易明细（{len(trades)} 笔）===")
    print(
        f"  规则：反转信号（涨>={gain_threshold * 100:.1f}% + "
        f"{_filter_label(filter_logic, rsi_max, min_dd20, filter_mode=filter_mode, min_score=min_score, max_rsi=max_rsi)}）"
        f"信号日尾盘收盘买入；第 {hold_days} 个交易日收盘卖出（可提前止盈止损）\n"
        f"  止盈止损：日 K 线收盘价触发\n"
        f"  价格门控(熊市): < {PRICE_HOLD_BELOW} 元持有；> {PRICE_STRATEGY_ABOVE} 元才交易\n"
        f"  自适应: ret20>{BULL_RET20_THRESHOLD*100:.0f}% → 牛市满仓不交易\n"
    )

    total_net = 0.0
    wins = 0
    for i, row in trades.iterrows():
        n = trades.index.get_loc(i) + 1
        buy_date = pd.Timestamp(row["entry_time"]).strftime("%Y-%m-%d")
        sell_date = pd.Timestamp(row["exit_time"]).strftime("%Y-%m-%d")
        qty = int(row["quantity"])
        entry = float(row["entry_price"])
        exit_ = float(row["exit_price"])
        net = float(row["net_pnl"])
        ret = float(row["return_pct"])
        total_net += net
        if net > 0:
            wins += 1

        print(f"  第 {n:2d} 笔")
        print(f"    买入日:     {buy_date}  尾盘收盘 {entry:.3f} 元")
        print(f"    卖出日:     {sell_date}  持股{hold_days}日收盘 {exit_:.3f} 元")
        print(f"    数量: {qty:,} 股  |  净盈亏: {net:+,.2f} 元  |  收益率: {ret:+.2f}%")
        print()

    losses = len(trades) - wins
    print(f"  合计净盈亏: {total_net:+,.2f} 元")
    print(f"  盈利 {wins} 笔 / 亏损 {losses} 笔")


def _execute_backtest(
    df_daily: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
    hold_days: int,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    gain_threshold: float = GAIN_THRESHOLD,
    price_hold_below: float = PRICE_HOLD_BELOW,
    price_strategy_above: float = PRICE_STRATEGY_ABOVE,
    enable_price_regime: bool = ENABLE_PRICE_REGIME,
    enable_adaptive_regime: bool = ENABLE_ADAPTIVE_REGIME,
    bull_ret20_threshold: float = BULL_RET20_THRESHOLD,
    show_progress: bool = False,
    quiet: bool = True,
) -> aq.BacktestResult:
    # 止盈止损统一用日 K 收盘，不再切换 30 分钟 feed
    use_30m = False
    data = df_daily
    start_time = pd.Timestamp(_to_ts(DATA_START, "15:00:00")).date().isoformat()
    end_time = _to_ts(DATA_END, "15:00:00")

    class _Strategy(ShortTermReversalStrategy):
        def __init__(self) -> None:
            super().__init__(
                BACKTEST_START,
                feature_map,
                hold_days=hold_days,
                rsi_max=rsi_max,
                min_dd20=min_dd20,
                filter_logic=filter_logic,
                filter_mode=filter_mode,
                min_score=min_score,
                max_rsi=max_rsi,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                gain_threshold=gain_threshold,
                use_30m_sltp=use_30m,
                price_hold_below=price_hold_below,
                price_strategy_above=price_strategy_above,
                enable_price_regime=enable_price_regime,
                enable_adaptive_regime=enable_adaptive_regime,
                bull_ret20_threshold=bull_ret20_threshold,
                quiet=quiet,
            )

    return aq.run_backtest(
        data=data,
        strategy=_Strategy,
        initial_cash=INITIAL_CASH,
        symbols=SYMBOL,
        lot_size=LOT_SIZE,
        t_plus_one=True,
        timezone="Asia/Shanghai",
        start_time=start_time,
        end_time=end_time,
        fill_policy=FILL_MODE,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=0.0,
        min_commission=MIN_COMMISSION,
        show_progress=show_progress,
    )


def _metrics_row(
    result: aq.BacktestResult,
    *,
    hold_days: int,
    rsi_max: float,
    min_dd20: float,
    filter_logic: str,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    gain_threshold: float = GAIN_THRESHOLD,
) -> dict[str, float | int | str]:
    m = result.metrics_df["value"]
    ann = float(m.get("annualized_return", 0.0))
    mdd = float(m.get("max_drawdown_pct", 0.0))
    total = float(m.get("total_return_pct", 0.0))
    trades = int(m.get("closed_trade_count", 0))
    win = float(m.get("win_rate", 0.0))
    sharpe = float(m.get("sharpe_ratio", 0.0))
    calmar = ann / (mdd / 100) if mdd > 0 else 0.0
    row = {
        "filter": _filter_label(
            filter_logic, rsi_max, min_dd20,
            filter_mode=filter_mode, min_score=min_score, max_rsi=max_rsi,
        ),
        "filter_mode": filter_mode,
        "logic": filter_logic,
        "rsi_max": rsi_max,
        "min_dd20": min_dd20,
        "min_score": min_score,
        "max_rsi": max_rsi,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "gain_pct": gain_threshold * 100,
        "gain_threshold": gain_threshold,
        "hold_days": hold_days,
        "trades": trades,
        "total_pct": total,
        "ann_pct": ann * 100,
        "mdd_pct": mdd,
        "win_pct": win,
        "sharpe": sharpe,
        "calmar": calmar,
    }
    return row


def _meets_constraints(row: dict[str, float | int | str]) -> bool:
    return (
        int(row["trades"]) > MIN_TRADES_TARGET
        and float(row["ann_pct"]) > MIN_ANN_TARGET_PCT
        and float(row["mdd_pct"]) < MAX_MDD_TARGET_PCT
    )


def _constraint_score(row: dict[str, float | int | str]) -> float:
    """硬约束下的折中评分：优先满足笔数/回撤，尽量抬高年化."""
    trades = int(row["trades"])
    ann = float(row["ann_pct"])
    mdd = float(row["mdd_pct"])
    if _meets_constraints(row):
        return 100_000 + ann * 10 + float(row["calmar"])
    score = ann * 2.0 + float(row["calmar"]) * 5
    if trades <= MIN_TRADES_TARGET:
        score -= (MIN_TRADES_TARGET - trades) * 0.15
    if ann <= MIN_ANN_TARGET_PCT:
        score -= (MIN_ANN_TARGET_PCT - ann) * 3.0
    if mdd >= MAX_MDD_TARGET_PCT:
        score -= (mdd - MAX_MDD_TARGET_PCT) * 2.0
    return score


def _optimization_score(row: dict[str, float | int | str], objective: str) -> float:
    """综合评分：默认 constrained 满足硬约束优先，否则折中."""
    if objective == "constrained":
        return _constraint_score(row)
    ann = float(row["ann_pct"])
    total = float(row["total_pct"])
    calmar = float(row["calmar"])
    mdd = float(row["mdd_pct"])
    if objective == "ann":
        return ann
    if objective == "calmar":
        return calmar
    if objective == "total":
        return total
    # balanced：年化为主，回撤超 30% 惩罚，Calmar 为辅
    mdd_penalty = max(0.0, mdd - 30.0) * 0.08
    return ann * 0.55 + calmar * 10 * 0.25 + total * 0.02 - mdd_penalty


def _run_backtest_row(
    df_daily: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
    hold_days: int,
    gain_threshold: float,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    objective: str = OPTIMIZE_OBJECTIVE,
) -> dict[str, float | int | str]:
    result = _execute_backtest(
        df_daily,
        feature_map,
        df_30m=df_30m,
        hold_days=hold_days,
        rsi_max=rsi_max,
        min_dd20=min_dd20,
        filter_logic=filter_logic,
        filter_mode=filter_mode,
        min_score=min_score,
        max_rsi=max_rsi,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        gain_threshold=gain_threshold,
        show_progress=False,
        quiet=True,
    )
    row = _metrics_row(
        result,
        hold_days=hold_days,
        rsi_max=rsi_max,
        min_dd20=min_dd20,
        filter_logic=filter_logic,
        filter_mode=filter_mode,
        min_score=min_score,
        max_rsi=max_rsi,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        gain_threshold=gain_threshold,
    )
    row["score"] = _optimization_score(row, objective)
    row["feasible"] = _meets_constraints(row)
    return row


def grid_search_params(
    df_daily: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    gain_grid: list[float] | None = None,
    hold_grid: list[int] | None = None,
    objective: str = OPTIMIZE_OBJECTIVE,
) -> pd.DataFrame:
    """涨幅阈值 × 持仓天数 网格搜索."""
    gains = gain_grid or GAIN_THRESHOLD_SCAN
    holds = hold_grid or HOLD_DAYS_SCAN
    rows: list[dict[str, float | int | str]] = []
    for gain in gains:
        for hold in holds:
            rows.append(
                _run_backtest_row(
                    df_daily,
                    feature_map,
                    df_30m=df_30m,
                    hold_days=hold,
                    gain_threshold=gain,
                    rsi_max=rsi_max,
                    min_dd20=min_dd20,
                    filter_logic=filter_logic,
                    filter_mode=filter_mode,
                    min_score=min_score,
                    max_rsi=max_rsi,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    objective=objective,
                )
            )
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def constrained_optimize(
    df_daily: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
    objective: str = "constrained",
) -> tuple[dict[str, float | int | str], pd.DataFrame]:
    """硬约束优化：笔数>200、年化>10%、回撤<30%；无完全可行解时返回最接近方案."""
    gain_grid = [0.007, 0.008, 0.009, 0.010, 0.0105, 0.0108, 0.011, 0.0112, 0.012]
    hold_grid = [2, 3, 4, 5]
    # 精选过滤组合（避免全笛卡尔积爆炸）
    filter_configs: list[tuple[str, str, float, float, int, float]] = [
        ("none", "and", 9999.0, 1.0, 0, 60.0),
        ("none", "and", 9999.0, 1.0, 0, 65.0),
        ("none", "and", 9999.0, 1.0, 0, 70.0),
        ("none", "and", 9999.0, 1.0, 0, 75.0),
        ("none", "and", 9999.0, 1.0, 0, 9999.0),
        ("classic", "and", 55.0, -0.03, 0, 70.0),
        ("classic", "and", 55.0, -0.05, 0, 70.0),
        ("classic", "and", 60.0, -0.03, 0, 70.0),
        ("classic", "and", 60.0, -0.05, 0, 70.0),
        ("classic", "or", 55.0, -0.03, 0, 70.0),
        ("classic", "or", 55.0, -0.05, 0, 70.0),
        ("classic", "and", 55.0, 0.0, 0, 65.0),
        ("score", "and", 9999.0, 1.0, 25, 70.0),
        ("score", "and", 9999.0, 1.0, 35, 70.0),
        ("score", "and", 9999.0, 1.0, 45, 70.0),
        ("score", "and", 9999.0, 1.0, 35, 65.0),
        ("score", "and", 9999.0, 1.0, 25, 65.0),
    ]
    risk_configs: list[tuple[float, float]] = [
        (STOP_LOSS_PCT, TAKE_PROFIT_PCT),
    ] if (STOP_LOSS_PCT > 0 or TAKE_PROFIT_PCT > 0) else [(0.0, 0.0)]

    rows: list[dict[str, float | int | str]] = []
    for gain in gain_grid:
        for hold in hold_grid:
            for mode, logic, rsi_cap, min_dd, min_sc, max_rsi in filter_configs:
                for sl, tp in risk_configs:
                    rows.append(
                        _run_backtest_row(
                            df_daily,
                            feature_map,
                            df_30m=df_30m,
                            hold_days=hold,
                            gain_threshold=gain,
                            rsi_max=rsi_cap,
                            min_dd20=min_dd,
                            filter_logic=logic,
                            filter_mode=mode,
                            min_score=min_sc,
                            max_rsi=max_rsi,
                            stop_loss_pct=sl,
                            take_profit_pct=tp,
                            objective=objective,
                        )
                    )

    scan_df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    best = scan_df.iloc[0].to_dict()
    return best, scan_df


def optimize_strategy_params(
    df_daily: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    objective: str = OPTIMIZE_OBJECTIVE,
) -> tuple[dict[str, float | int | str], pd.DataFrame]:
    """返回 (最优参数字典, 完整扫描表)."""
    if objective == "constrained":
        return constrained_optimize(
            df_daily, feature_map, df_30m=df_30m, objective=objective
        )

    scan_df = grid_search_params(
        df_daily,
        feature_map,
        df_30m=df_30m,
        rsi_max=rsi_max,
        min_dd20=min_dd20,
        filter_logic=filter_logic,
        filter_mode=filter_mode,
        min_score=min_score,
        max_rsi=max_rsi,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        objective=objective,
    )
    return scan_df.iloc[0].to_dict(), scan_df


def print_grid_optimization(
    scan_df: pd.DataFrame,
    *,
    best: dict[str, float | int | str],
    objective: str,
) -> None:
    """打印网格搜索 Top 结果与最优参数."""
    feasible_n = int(scan_df["feasible"].sum()) if "feasible" in scan_df.columns else 0
    print(f"\n=== 自动优化（目标={objective}，硬约束：笔数>{MIN_TRADES_TARGET} "
          f"年化>{MIN_ANN_TARGET_PCT:.0f}% 回撤<{MAX_MDD_TARGET_PCT:.0f}%）===")
    if feasible_n:
        print(f"  ✓ 找到 {feasible_n} 组完全满足硬约束的参数")
    else:
        print("  ⚠ 无参数同时满足全部硬约束，以下为最接近的折中方案")
    print(
        f"  ★ 最优：涨>={float(best['gain_threshold']) * 100:.1f}%，持 {int(best['hold_days'])} 日，"
        f"{best['filter']}"
    )
    sl = float(best.get("stop_loss_pct", 0))
    tp = float(best.get("take_profit_pct", 0))
    if sl > 0 or tp > 0:
        print(f"     风控：止损={sl * 100:.0f}% 止盈={tp * 100:.0f}%")
    print(
        f"     笔数={int(best['trades'])}  总收益={float(best['total_pct']):+.1f}%  "
        f"年化={float(best['ann_pct']):+.2f}%  回撤={float(best['mdd_pct']):.1f}%  "
        f"胜率={float(best['win_pct']):.1f}%  评分={float(best['score']):.3f}"
    )
    print(
        f"\n  {'涨幅':>6} {'持仓':>4} {'笔数':>5} {'总收益':>8} "
        f"{'年化':>7} {'回撤':>7} {'Calmar':>7} {'评分':>6}"
    )
    print("  " + "-" * 62)
    for _, row in scan_df.head(10).iterrows():
        mark = " ★" if row.name == 0 else ""
        print(
            f"  {row['gain_pct']:>5.1f}% {int(row['hold_days']):>4} "
            f"{int(row['trades']):>5} {row['total_pct']:>+7.1f}% "
            f"{row['ann_pct']:>+6.2f}% {row['mdd_pct']:>6.1f}% "
            f"{row['calmar']:>7.3f} {row['score']:>6.3f}{mark}"
        )


def print_parameter_scan(
    df_daily: pd.DataFrame,
    daily_raw: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """扫描过滤逻辑 × 持仓天数，找年化/回撤平衡."""
    print("\n=== 参数扫描（过滤逻辑 × 持仓天数）===")
    filter_configs = [
        ("or", 55.0, MIN_DD20),
        ("or", 50.0, MIN_DD20),
        ("and", 55.0, MIN_DD20),
        ("and", 50.0, MIN_DD20),
    ]
    rows: list[dict[str, float | int | str]] = []
    for logic, rsi_max, min_dd20 in filter_configs:
        for hold in HOLD_DAYS_SCAN:
            result = _execute_backtest(
                df_daily,
                feature_map,
                df_30m=df_30m,
                hold_days=hold,
                rsi_max=rsi_max,
                min_dd20=min_dd20,
                filter_logic=logic,
                show_progress=False,
            )
            rows.append(
                _metrics_row(
                    result,
                    hold_days=hold,
                    rsi_max=rsi_max,
                    min_dd20=min_dd20,
                    filter_logic=logic,
                )
            )

    scan_df = pd.DataFrame(rows).sort_values(
        ["calmar", "ann_pct"], ascending=False
    ).reset_index(drop=True)

    print(
        f"  {'过滤':<22} {'持仓':>4} {'笔数':>5} {'总收益':>8} "
        f"{'年化':>7} {'回撤':>7} {'胜率':>6} {'Calmar':>7}"
    )
    print("  " + "-" * 78)
    for _, row in scan_df.head(12).iterrows():
        print(
            f"  {row['filter']:<22} {int(row['hold_days']):>4} "
            f"{int(row['trades']):>5} {row['total_pct']:>+7.1f}% "
            f"{row['ann_pct']:>+6.2f}% {row['mdd_pct']:>6.1f}% "
            f"{row['win_pct']:>5.1f}% {row['calmar']:>7.3f}"
        )
    print("\n  说明：Calmar = 年化收益 / 最大回撤；优先提高出手频率与年化。")
    return scan_df


def print_hold_days_scan(daily_raw: pd.DataFrame) -> None:
    """信号层快速扫描：不同持仓天数的过滤后均收益."""
    sig = _signal_trade_returns(daily_raw, hold_days=HOLD_DAYS)
    if sig.empty:
        return
    print(f"\n=== 持仓天数信号扫描（{_filter_label(FILTER_LOGIC, RSI_MAX, MIN_DD20)}）===")
    print(f"  {'天数':>4} {'样本':>5} {'均收益':>8} {'胜率':>7}")
    print("  " + "-" * 30)
    mask = _mask_filtered_signals(
        sig, rsi_max=RSI_MAX, min_dd20=MIN_DD20, filter_logic=FILTER_LOGIC
    )
    base = sig[mask]
    for hold in HOLD_DAYS_SCAN:
        sub_sig = _signal_trade_returns(daily_raw, hold_days=hold)
        sub = sub_sig[
            _mask_filtered_signals(
                sub_sig,
                rsi_max=RSI_MAX,
                min_dd20=MIN_DD20,
                filter_logic=FILTER_LOGIC,
            )
        ]
        if sub.empty:
            continue
        print(
            f"  {hold:>4} {len(sub):>5} "
            f"{sub['ret'].mean() * 100:>+7.2f}% "
            f"{(sub['ret'] > 0).mean() * 100:>6.1f}%"
        )
    _ = base  # 保留变量供后续扩展


def print_gain_threshold_scan(
    df_daily: pd.DataFrame,
    feature_map: dict[dt.date, dict[str, float]],
    *,
    df_30m: pd.DataFrame | None = None,
    hold_days: int = HOLD_DAYS,
    rsi_max: float = RSI_MAX,
    filter_logic: str = FILTER_LOGIC,
) -> pd.DataFrame:
    """扫描单日涨幅触发阈值（固定过滤与持仓）."""
    print(
        f"\n=== 涨幅阈值扫描（{_filter_label(filter_logic, rsi_max, MIN_DD20)}，"
        f"持{hold_days}日）==="
    )
    rows: list[dict[str, float | int | str]] = []
    for thr in GAIN_THRESHOLD_SCAN:
        result = _execute_backtest(
            df_daily,
            feature_map,
            df_30m=df_30m,
            hold_days=hold_days,
            rsi_max=rsi_max,
            min_dd20=MIN_DD20,
            filter_logic=filter_logic,
            gain_threshold=thr,
            show_progress=False,
        )
        row = _metrics_row(
            result,
            hold_days=hold_days,
            rsi_max=rsi_max,
            min_dd20=MIN_DD20,
            filter_logic=filter_logic,
        )
        row["gain_pct"] = thr * 100
        rows.append(row)

    scan_df = pd.DataFrame(rows).sort_values(
        ["calmar", "ann_pct"], ascending=False
    ).reset_index(drop=True)

    print(f"  {'涨幅':>6} {'笔数':>5} {'总收益':>8} {'年化':>7} {'回撤':>7} {'胜率':>6} {'Calmar':>7}")
    print("  " + "-" * 58)
    for _, row in scan_df.iterrows():
        mark = " ← 当前" if abs(row["gain_pct"] - GAIN_THRESHOLD * 100) < 0.05 else ""
        print(
            f"  {row['gain_pct']:>5.1f}% {int(row['trades']):>5} "
            f"{row['total_pct']:>+7.1f}% {row['ann_pct']:>+6.2f}% "
            f"{row['mdd_pct']:>6.1f}% {row['win_pct']:>5.1f}% "
            f"{row['calmar']:>7.3f}{mark}"
        )
    print("\n  说明：阈值越低信号越多；1.0% 在收益/频率间平衡最佳。")
    return scan_df


def print_summary(
    result: aq.BacktestResult,
    *,
    hold_days: int = HOLD_DAYS,
    gain_threshold: float = GAIN_THRESHOLD,
    filter_logic: str = FILTER_LOGIC,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
) -> None:
    metrics = result.metrics_df["value"]
    print("\n=== 关键指标 ===")
    for key in (
        "total_return_pct", "annualized_return", "max_drawdown_pct",
        "sharpe_ratio", "win_rate", "closed_trade_count", "total_commission",
    ):
        if key in metrics.index:
            print(f"  {key}: {metrics[key]}")
    print_trade_details(
        result.trades_df,
        hold_days=hold_days,
        gain_threshold=gain_threshold,
        filter_logic=filter_logic,
        rsi_max=rsi_max,
        min_dd20=min_dd20,
        filter_mode=filter_mode,
        min_score=min_score,
        max_rsi=max_rsi,
    )


def run_backtest(
    refresh: bool = False,
    auto_optimize: bool = True,
    scan: bool = False,
    hold_days: int | None = None,
    rsi_max: float = RSI_MAX,
    min_dd20: float = MIN_DD20,
    filter_logic: str = FILTER_LOGIC,
    filter_mode: str = FILTER_MODE,
    min_score: int = MIN_SCORE,
    max_rsi: float = MAX_RSI,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    gain_threshold: float | None = None,
    objective: str = OPTIMIZE_OBJECTIVE,
) -> aq.BacktestResult:
    use_hold = HOLD_DAYS if hold_days is None else hold_days
    use_gain = GAIN_THRESHOLD if gain_threshold is None else gain_threshold
    use_rsi_max = rsi_max
    use_min_dd20 = min_dd20
    use_filter_logic = filter_logic
    use_filter_mode = filter_mode
    use_min_score = min_score
    use_max_rsi = max_rsi
    use_stop_loss = stop_loss_pct
    use_take_profit = take_profit_pct
    manual_params = (
        not auto_optimize or hold_days is not None or gain_threshold is not None
    )

    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 adjust={ADJUST} …")
    print(f"  （akquant：复权在 fetch 层控制，run_backtest 无 adjust 参数）")
    print(f"回测区间: {BACKTEST_START} ~ {DATA_END}")

    daily_raw = fetch_etf_daily(
        SYMBOL,
        start_date=DATA_START, end_date=DATA_END,
        adjust=ADJUST, refresh=refresh,
    )
    end_date = pd.Timestamp(_to_ts(DATA_END, "00:00:00")).date()
    print_buy_hold_pnl(daily_raw, BACKTEST_START, end_date)

    df = daily_to_akquant(daily_raw, SYMBOL)
    df = prepare_dataframe(df, date_col="date", tz="Asia/Shanghai")
    print(f"\n日线数据: {len(df)} 天（{ADJUST}）")
    print(f"  覆盖区间: {pd.to_datetime(df['date']).min().date()} ~ "
          f"{pd.to_datetime(df['date']).max().date()}")

    df_30m: pd.DataFrame | None = None

    sample = daily_raw[daily_raw["date"] == pd.Timestamp("2024-10-10")]
    if not sample.empty:
        print(f"  校验 2024-10-10 收盘价: {float(sample.iloc[0]['close']):.3f}")

    daily_raw.to_csv(DAILY_CLOSE_CSV, index=False, encoding="utf-8-sig")
    print(f"已保存: {DAILY_CLOSE_CSV.name}")

    feature_map = build_reversal_feature_map(daily_raw)

    if not manual_params:
        best, scan_df = optimize_strategy_params(
            df,
            feature_map,
            df_30m=df_30m,
            rsi_max=rsi_max,
            min_dd20=min_dd20,
            filter_logic=filter_logic,
            filter_mode=filter_mode,
            min_score=min_score,
            max_rsi=max_rsi,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            objective=objective,
        )
        print_grid_optimization(scan_df, best=best, objective=objective)
        use_gain = float(best["gain_threshold"])
        use_hold = int(best["hold_days"])
        use_rsi_max = float(best["rsi_max"])
        use_min_dd20 = float(best["min_dd20"])
        use_filter_logic = str(best["logic"])
        use_filter_mode = str(best["filter_mode"])
        use_min_score = int(best["min_score"])
        use_max_rsi = float(best["max_rsi"])
        use_stop_loss = float(best["stop_loss_pct"])
        use_take_profit = float(best["take_profit_pct"])
    elif scan:
        print_reversal_factor_analysis(daily_raw)
        print_hold_days_scan(daily_raw)
        scan_df = grid_search_params(
            df,
            feature_map,
            df_30m=df_30m,
            rsi_max=rsi_max,
            min_dd20=min_dd20,
            filter_logic=filter_logic,
            filter_mode=filter_mode,
            min_score=min_score,
            max_rsi=max_rsi,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            objective=objective,
        )
        best = scan_df.iloc[0].to_dict()
        print_grid_optimization(scan_df, best=best, objective=objective)

    filter_desc = _filter_label(
        use_filter_logic, use_rsi_max, use_min_dd20,
        filter_mode=use_filter_mode, min_score=use_min_score, max_rsi=use_max_rsi,
    )
    risk_desc = ""
    if use_stop_loss > 0 or use_take_profit > 0:
        risk_desc = (
            f"，止损={use_stop_loss * 100:.0f}% 止盈={use_take_profit * 100:.0f}%"
            f"（日K收盘触发）"
        )
    print(
        f"\n策略配置: 涨>={use_gain * 100:.2f}% + {filter_desc}，持 {use_hold} 日{risk_desc}"
        + ("（自动优化）" if not manual_params else "")
    )
    if ENABLE_ADAPTIVE_REGIME:
        print(
            f"  自适应牛熊: ret20 > {BULL_RET20_THRESHOLD * 100:.0f}% → 牛市满仓持有；"
            f"否则熊市才做短线反转"
        )
    if ENABLE_PRICE_REGIME:
        print(
            f"  熊市门控: < {PRICE_HOLD_BELOW} 元仅持有；"
            f"> {PRICE_STRATEGY_ABOVE} 元启用策略"
        )

    result = _execute_backtest(
        df,
        feature_map,
        df_30m=df_30m,
        hold_days=use_hold,
        rsi_max=use_rsi_max,
        min_dd20=use_min_dd20,
        filter_logic=use_filter_logic,
        filter_mode=use_filter_mode,
        min_score=use_min_score,
        max_rsi=use_max_rsi,
        stop_loss_pct=use_stop_loss,
        take_profit_pct=use_take_profit,
        gain_threshold=use_gain,
        show_progress=True,
        quiet=False,
    )

    print("\n=== Backtest Result ===")
    print(result)
    print_summary(
        result,
        hold_days=use_hold,
        gain_threshold=use_gain,
        filter_logic=use_filter_logic,
        rsi_max=use_rsi_max,
        min_dd20=use_min_dd20,
        filter_mode=use_filter_mode,
        min_score=use_min_score,
        max_rsi=use_max_rsi,
    )
    print_yearly_returns(result, daily_raw, BACKTEST_START, end_date)
    print_monthly_returns(result, daily_raw, BACKTEST_START, end_date)

    result.viz.report(
        filename=str(REPORT_PATH),
        show=False,
        benchmark=build_benchmark_returns(df),
    )
    print(f"\n报告: {REPORT_PATH.name}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{SYMBOL_NAME} 短线反转策略（默认自动优化涨幅阈值与持仓天数）"
    )
    parser.add_argument("--refresh", action="store_true", help="重新拉取日线数据")
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help=f"关闭自动优化，使用固定参数（涨{GAIN_THRESHOLD*100:.1f}%% 持{HOLD_DAYS}日）",
    )
    parser.add_argument(
        "--objective",
        choices=["constrained", "balanced", "ann", "calmar", "total"],
        default=OPTIMIZE_OBJECTIVE,
        help="优化目标：constrained 硬约束（默认）| balanced | ann | calmar | total",
    )
    parser.add_argument(
        "--filter",
        choices=["and", "or"],
        default=FILTER_LOGIC,
        help="过滤逻辑：and（默认）或 or（高频率，建议配合 --hold 10）",
    )
    parser.add_argument(
        "--rsi-max",
        type=float,
        default=RSI_MAX,
        help=f"RSI 上限（默认 {RSI_MAX:.0f}）",
    )
    parser.add_argument(
        "--hold",
        type=int,
        default=None,
        help=f"手动指定持股天数（指定后不再自动优化持仓）",
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=None,
        help="手动指定涨幅阈值，小数形式（如 0.01 = 1%%）",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="手动模式下额外打印因子分析与网格扫描",
    )
    args = parser.parse_args()
    run_backtest(
        refresh=args.refresh,
        auto_optimize=not args.no_auto,
        scan=args.scan,
        hold_days=args.hold,
        rsi_max=args.rsi_max,
        filter_logic=args.filter,
        gain_threshold=args.gain,
        objective=args.objective,
    )


if __name__ == "__main__":
    main()
