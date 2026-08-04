"""分钟线拉取与标准化（回测低开 9:45 / 因子3）。

数据源优先级：
  · 1 分钟：akshare 东财 → 新浪（近约 5 日，含均价）
  · 5/15/30/60 分钟：baostock 长历史（量额齐全）+ akshare 东财/新浪近期补充
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import akshare as ak
import pandas as pd

SUPPORTED_PERIODS = ("1", "5", "15", "30", "60")


def standardize_minute_1m(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    time_col = next((c for c in ("时间", "day", "date", "ts") if c in df.columns), None)
    if time_col is None:
        return pd.DataFrame()
    rename = {
        time_col: "ts",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "均价": "avg_price",
    }
    for src, dst in rename.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})
    need = ["ts", "open", "high", "low", "close"]
    if not all(c in df.columns for c in need):
        return pd.DataFrame()
    keep = list(need)
    for extra in ("volume", "amount", "avg_price"):
        if extra in df.columns:
            keep.append(extra)
    out = df[keep].copy()
    out["ts"] = pd.to_datetime(out["ts"])
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("volume", "amount", "avg_price"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["ts", "open", "high", "low", "close"])
    out = out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    if out["ts"].dt.tz is None:
        out["ts"] = out["ts"].dt.tz_localize("Asia/Shanghai")
    else:
        out["ts"] = out["ts"].dt.tz_convert("Asia/Shanghai")
    return out.reset_index(drop=True)


def _em_code_from_sina(sina_symbol: str) -> str:
    s = str(sina_symbol or "").strip().lower()
    if len(s) >= 8 and s[:2] in ("sh", "sz"):
        return s[2:]
    return s


def _retry_call(fn, *, retries: int = 3, pause: float = 1.2):
    last: Exception | None = None
    for i in range(max(1, retries)):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < retries:
                time.sleep(pause * (i + 1))
    if last is not None:
        raise last
    return None


def pull_akshare_1m(
    *,
    em_symbol: str | None = None,
    sina_symbol: str | None = None,
    adjust: str = "qfq",
    retries: int = 3,
) -> pd.DataFrame:
    """框架优先：东财 1 分钟 → 新浪 1 分钟。返回已标准化 DataFrame。"""
    return pull_akshare_min(
        period="1",
        em_symbol=em_symbol,
        sina_symbol=sina_symbol,
        adjust=adjust,
        retries=retries,
    )


def _bs_symbol(sina_symbol: str | None = None, em_symbol: str | None = None) -> str:
    """baostock 代码：sh.600552 / sz.000001。"""
    s = (sina_symbol or "").strip().lower()
    if len(s) >= 8 and s[:2] in ("sh", "sz"):
        return f"{s[:2]}.{s[2:]}"
    em = (em_symbol or "").strip()
    if not em and s:
        em = _em_code_from_sina(s)
    if not em:
        raise ValueError("无法推断 baostock 代码")
    market = "sh" if em.startswith("6") else "sz"
    return f"{market}.{em}"


def pull_baostock_min(
    *,
    period: str = "5",
    em_symbol: str | None = None,
    sina_symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """baostock 分钟线（含成交量/成交额），适合拉长历史。

    仅支持 period in {'5','15','30','60'}（无 1 分钟）。
    start_date/end_date: YYYYMMDD。
    """
    period = str(period).strip()
    if period not in ("5", "15", "30", "60"):
        return pd.DataFrame()
    try:
        import baostock as bs
    except ImportError:
        return pd.DataFrame()

    if start_date and end_date:
        start_s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end_s = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    else:
        end_dt = dt.datetime.now()
        start_dt = end_dt - dt.timedelta(days=365)
        start_s = start_dt.strftime("%Y-%m-%d")
        end_s = end_dt.strftime("%Y-%m-%d")

    adjustflag = {"qfq": "2", "hfq": "3", "": "1"}.get(adjust, "2")
    code = _bs_symbol(sina_symbol=sina_symbol, em_symbol=em_symbol)
    lg = bs.login()
    if getattr(lg, "error_code", "0") not in ("0", 0, None):
        return pd.DataFrame()
    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,time,code,open,high,low,close,volume,amount",
            start_date=start_s,
            end_date=end_s,
            frequency=period,
            adjustflag=adjustflag,
        )
        rows: list[list[str]] = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        raw = pd.DataFrame(rows, columns=list(rs.fields))
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    # time: 20200102093500000 → 2020-01-02 09:35:00
    t = raw["time"].astype(str).str.slice(0, 14)
    raw["ts"] = pd.to_datetime(t, format="%Y%m%d%H%M%S", errors="coerce")
    out = raw.rename(
        columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
        }
    )
    keep = ["ts", "open", "high", "low", "close", "volume", "amount"]
    out = out[keep].copy()
    for col in keep[1:]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["ts", "open", "high", "low", "close"])
    out = out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    if out["ts"].dt.tz is None:
        out["ts"] = out["ts"].dt.tz_localize("Asia/Shanghai")
    else:
        out["ts"] = out["ts"].dt.tz_convert("Asia/Shanghai")
    return out.reset_index(drop=True)


def pull_akshare_min(
    *,
    period: str = "1",
    em_symbol: str | None = None,
    sina_symbol: str | None = None,
    adjust: str = "qfq",
    retries: int = 3,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """框架优先拉分钟线：东财 → 新浪。

    period: '1'|'5'|'15'|'30'|'60'
    start_date/end_date: YYYYMMDD；period!='1' 时按约 40 日切块拉东财。
    """
    period = str(period).strip()
    if period not in SUPPORTED_PERIODS:
        raise ValueError(f"不支持的分钟周期: {period}")
    em = (em_symbol or "").strip() or (
        _em_code_from_sina(sina_symbol) if sina_symbol else ""
    )
    sina = (sina_symbol or "").strip()
    parts: list[pd.DataFrame] = []

    if em:
        if period == "1":
            try:
                raw = _retry_call(
                    lambda: ak.stock_zh_a_hist_min_em(
                        symbol=em,
                        period="1",
                        adjust=adjust,
                    ),
                    retries=retries,
                )
                part = standardize_minute_1m(raw)
                if not part.empty:
                    parts.append(part)
            except Exception:
                pass
        else:
            # 5/15/30/60：从 end 往前按约 40 日切块；连续空块则停止（东财可回溯有限）
            if start_date and end_date:
                start_dt = dt.datetime.strptime(start_date, "%Y%m%d")
                end_dt = dt.datetime.strptime(end_date, "%Y%m%d")
            else:
                end_dt = dt.datetime.now()
                start_dt = end_dt - dt.timedelta(days=120)
            empty_streak = 0
            cur_end = end_dt
            while cur_end >= start_dt and empty_streak < 3:
                cur_start = max(cur_end - dt.timedelta(days=40), start_dt)
                s = cur_start.strftime("%Y-%m-%d 09:30:00")
                e = cur_end.strftime("%Y-%m-%d 15:00:00")
                got = False
                try:
                    raw = _retry_call(
                        lambda s=s, e=e: ak.stock_zh_a_hist_min_em(
                            symbol=em,
                            period=period,
                            start_date=s,
                            end_date=e,
                            adjust=adjust,
                        ),
                        retries=retries,
                        pause=1.5,
                    )
                    part = standardize_minute_1m(raw)
                    if not part.empty:
                        parts.append(part)
                        got = True
                        empty_streak = 0
                except Exception:
                    pass
                if not got:
                    empty_streak += 1
                cur_end = cur_start - dt.timedelta(days=1)
                time.sleep(0.35)

    if sina:
        try:
            raw = _retry_call(
                lambda: ak.stock_zh_a_minute(
                    symbol=sina, period=period, adjust=adjust
                ),
                retries=retries,
            )
            part = standardize_minute_1m(raw)
            if not part.empty:
                parts.append(part)
        except Exception:
            pass

    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["_rich"] = (
        out.get("amount", pd.Series(index=out.index, dtype=float)).notna()
        | out.get("avg_price", pd.Series(index=out.index, dtype=float)).notna()
    ).astype(int)
    out = out.sort_values(["ts", "_rich"]).drop_duplicates(subset=["ts"], keep="last")
    return out.drop(columns=["_rich"]).reset_index(drop=True)


def fetch_minute_1m(
    *,
    sina_symbol: str,
    em_symbol: str,
    cache_path: Path,
    refresh: bool = False,
    lookback_days: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取 1 分钟线并写缓存（兼容旧调用）。"""
    return fetch_minute_bars(
        period="1",
        sina_symbol=sina_symbol,
        em_symbol=em_symbol,
        cache_path=cache_path,
        refresh=refresh,
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_minute_5m(
    *,
    sina_symbol: str,
    em_symbol: str,
    cache_path: Path,
    refresh: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取 5 分钟线并写缓存（baostock 长历史 + 东财/新浪近期）。"""
    return fetch_minute_bars(
        period="5",
        sina_symbol=sina_symbol,
        em_symbol=em_symbol,
        cache_path=cache_path,
        refresh=refresh,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_minute_30m(
    *,
    sina_symbol: str,
    em_symbol: str,
    cache_path: Path,
    refresh: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取 30 分钟线并写缓存（baostock 长历史 + 东财/新浪近期）。"""
    return fetch_minute_bars(
        period="30",
        sina_symbol=sina_symbol,
        em_symbol=em_symbol,
        cache_path=cache_path,
        refresh=refresh,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_minute_bars(
    *,
    period: str = "1",
    sina_symbol: str,
    em_symbol: str,
    cache_path: Path,
    refresh: bool = False,
    lookback_days: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取分钟线并写缓存。

    period='1'：东财/新浪近几日。
    period='5' 等：优先 baostock 拉长历史（量额齐全），再合并东财/新浪近期。
    若本地缓存已覆盖请求区间，跳过 baostock 全量重拉（仅补近期）。
    """
    del lookback_days
    period = str(period).strip()

    cached = pd.DataFrame()
    if cache_path.exists() and not refresh:
        try:
            cached = standardize_minute_1m(pd.read_parquet(cache_path))
        except Exception:
            cached = pd.DataFrame()

    cache_covers = False
    if not cached.empty and start_date and end_date:
        dmin = cached["ts"].min()
        dmax = cached["ts"].max()
        start_ts = pd.Timestamp(start_date).tz_localize("Asia/Shanghai")
        end_ts = pd.Timestamp(end_date).tz_localize("Asia/Shanghai") + pd.Timedelta(
            hours=23, minutes=59
        )
        # 起点不晚于请求起点后 5 日；终点不早于请求终点前 5 日
        cache_covers = (dmin <= start_ts + pd.Timedelta(days=5)) and (
            dmax >= end_ts - pd.Timedelta(days=5)
        )

    parts: list[pd.DataFrame] = []
    if not cached.empty:
        parts.append(cached)

    # 长历史：仅在缓存不足或强制刷新时走 baostock
    if period in ("5", "15", "30", "60") and (refresh or not cache_covers):
        try:
            bs_df = pull_baostock_min(
                period=period,
                em_symbol=em_symbol or _em_code_from_sina(sina_symbol),
                sina_symbol=sina_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if not bs_df.empty:
                parts.append(bs_df)
        except Exception:
            pass

    # 近期补充（1m 总是拉；5m 在缓存将尽或强制刷新时拉）
    need_fresh = refresh or period == "1" or not cache_covers
    if need_fresh:
        fresh = pull_akshare_min(
            period=period,
            em_symbol=em_symbol or _em_code_from_sina(sina_symbol),
            sina_symbol=sina_symbol,
            adjust="qfq",
            start_date=start_date,
            end_date=end_date,
        )
        if not fresh.empty:
            parts.append(fresh)

    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["_rich"] = (
        out.get("amount", pd.Series(index=out.index, dtype=float)).notna()
        | out.get("avg_price", pd.Series(index=out.index, dtype=float)).notna()
    ).astype(int)
    out = out.sort_values(["ts", "_rich"]).drop_duplicates(subset=["ts"], keep="last")
    out = out.drop(columns=["_rich"])

    if start_date:
        start_ts = pd.Timestamp(start_date).tz_localize("Asia/Shanghai")
        out = out[out["ts"] >= start_ts]
    if end_date:
        end_ts = pd.Timestamp(end_date).tz_localize("Asia/Shanghai") + pd.Timedelta(
            hours=23, minutes=59
        )
        out = out[out["ts"] <= end_ts]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    return out.reset_index(drop=True)
