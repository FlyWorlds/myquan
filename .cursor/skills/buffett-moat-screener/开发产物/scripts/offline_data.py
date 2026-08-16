"""离线数据加载器：从 E:/量化实盘选股/data/lake 读取所有回测所需数据。

优点：不消耗 panda_data 套餐配额，全量本地跑。
局限：数据湖覆盖 bars 2012-12 起、financial_reports 2013 起、index_weights 2017 起。
"""

from __future__ import annotations

import glob
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds


LAKE = Path(r"E:/量化实盘选股/data/lake/raw")


@lru_cache(maxsize=8)
def _read_partitioned(name: str, columns: tuple[str, ...] | None = None) -> pd.DataFrame:
    """读一整个按 year=/month= 分区的表。"""
    root = LAKE / name
    if not root.exists():
        raise FileNotFoundError(root)
    dataset = ds.dataset(str(root), format="parquet", partitioning="hive")
    tbl = dataset.to_table(columns=list(columns) if columns else None)
    return tbl.to_pandas()


@lru_cache(maxsize=1)
def load_stock_details() -> pd.DataFrame:
    p = LAKE / "stock_details"
    if p.is_dir():
        files = list(p.glob("**/*.parquet"))
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()
    return pd.read_parquet(p)


@lru_cache(maxsize=1)
def load_industry() -> pd.DataFrame:
    p = LAKE / "industry_constituents"
    if p.is_dir():
        files = list(p.glob("**/*.parquet"))
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()
    return pd.read_parquet(p)


def stock_name_map() -> dict[str, str]:
    d = load_stock_details()
    return dict(zip(d["symbol"].astype(str), d["name"].astype(str)))


def industry_map() -> dict[str, str]:
    d = load_industry()
    # 一级行业中文名
    return dict(zip(d["stock_symbol"].astype(str), d["l1_name"].astype(str)))


@lru_cache(maxsize=1)
def load_financials() -> pd.DataFrame:
    """加载全部年报 + 季报，按 (symbol, quarter, available_date) 排序。"""
    df = _read_partitioned(
        "financial_reports",
        columns=(
            "symbol", "quarter", "date", "available_date",
            "operating_revenue", "gross_profit", "operating_profit",
            "np_parent_owners", "net_operate_cashflow",
            "total_assets", "se_parent_owners", "total_shares",
            "basic_eps", "roe",
            "revenue_yoy", "net_profit_yoy",
        ),
    )
    df["available_date"] = df["available_date"].astype(str)
    df["date"] = df["date"].astype(str)
    df["quarter"] = df["quarter"].astype(str)
    df = df.sort_values(["symbol", "quarter", "available_date", "date"])
    # 取同一 quarter 的最新修订
    df = df.drop_duplicates(["symbol", "quarter"], keep="last").reset_index(drop=True)
    return df


def annual_history(symbol: str, as_of: str) -> pd.DataFrame:
    """给定信号日和股票，返回信号日前可见的所有年报（quarter 以 q4 结尾）。"""
    fin = load_financials()
    q4 = fin[
        (fin["symbol"] == symbol)
        & (fin["quarter"].str.endswith("q4"))
        & (fin["available_date"] <= as_of)
    ].copy()
    q4["year"] = q4["quarter"].str[:4].astype(int)
    return q4.sort_values("year").reset_index(drop=True)


@lru_cache(maxsize=1)
def load_index_weights(index_symbol: str = "000300.SH") -> pd.DataFrame:
    """加载完整 index_weights；index_symbol 过滤后按日期返回。"""
    df = _read_partitioned("index_weights")
    df = df[df["index_symbol"] == index_symbol].copy()
    df["date"] = df["date"].astype(str)
    return df.sort_values("date").reset_index(drop=True)


def csi300_universe(as_of: str) -> list[str]:
    """返回 as_of 日前最近一次可见的 CSI300 成分股。
    如果 as_of < 数据湖起点（2017），使用最早那一日的成分作代理。"""
    w = load_index_weights("000300.SH")
    if w.empty:
        return []
    dates = w["date"].unique().tolist()
    pick_date = None
    for d in reversed(sorted(dates)):
        if d <= as_of:
            pick_date = d
            break
    if pick_date is None:
        pick_date = min(dates)
    snap = w[w["date"] == pick_date]
    return sorted(snap["stock_symbol"].astype(str).unique().tolist())


@lru_cache(maxsize=1)
def load_bars() -> pd.DataFrame:
    """加载全部后复权日线 close，只保留 (date, symbol, close)。"""
    df = _read_partitioned("bars_post_adjusted", columns=("date", "symbol", "close"))
    df["date"] = pd.to_datetime(df["date"].astype(str), errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["date", "close"]).sort_values(["symbol", "date"]).reset_index(drop=True)


def prices_pivot(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """返回 (date × symbol) 的收盘价宽表。"""
    bars = load_bars()
    s_ts = pd.to_datetime(start)
    e_ts = pd.to_datetime(end)
    sub = bars[(bars["date"] >= s_ts) & (bars["date"] <= e_ts) & (bars["symbol"].isin(symbols))]
    if sub.empty:
        return pd.DataFrame()
    pivot = sub.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    return pivot.ffill()


def trade_days(start: str, end: str) -> list[pd.Timestamp]:
    """从 bars 里推导交易日。"""
    bars = load_bars()
    s_ts = pd.to_datetime(start)
    e_ts = pd.to_datetime(end)
    mask = (bars["date"] >= s_ts) & (bars["date"] <= e_ts)
    return sorted(bars.loc[mask, "date"].unique().tolist())


def annual_jan_first_dates(start: str, end: str, year_step: int = 1) -> list[str]:
    """每年 1 月首个可见交易日；year_step 控制跨年数。"""
    ts = trade_days(start, end)
    picked: list[str] = []
    seen: set[int] = set()
    for d in ts:
        y = pd.Timestamp(d).year
        if y in seen:
            continue
        picked.append(pd.Timestamp(d).strftime("%Y%m%d"))
        seen.add(y)
    return picked[::year_step] if year_step > 1 else picked
