"""myquan 分钟行情到 CZSC 的适配、缓存与质量检查。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from strategy.chan.config import DEFAULT_CONFIG, ChanStrategyConfig
from strategy.minute import fetch_minute_30m


STANDARD_COLUMNS = ("dt", "symbol", "open", "close", "high", "low", "vol", "amount")


@dataclass(frozen=True)
class DataQuality:
    symbol: str
    rows: int
    start: str
    end: str
    duplicate_bars: int
    invalid_ohlc: int
    missing_volume: int
    timezone: str
    source: str
    point_in_time_universe: bool

    @property
    def valid(self) -> bool:
        return self.rows > 0 and self.duplicate_bars == 0 and self.invalid_ohlc == 0


def normalize_symbol(symbol: str) -> tuple[str, str]:
    """返回 (新浪格式, 东财纯数字格式)。"""
    value = str(symbol).strip().lower()
    if value.startswith(("sh", "sz")) and len(value) >= 8:
        return value, value[2:8]
    code = value.zfill(6)
    market = "sh" if code.startswith(("5", "6")) else "sz"
    return f"{market}{code}", code


def standardize_czsc_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """把 myquan/供应商行情转换为 CZSC 标准八列，不做未来复权。"""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(STANDARD_COLUMNS))
    df = frame.copy()
    rename: dict[str, str] = {}
    for source, target in (
        ("ts", "dt"),
        ("date", "dt"),
        ("volume", "vol"),
        ("成交量", "vol"),
        ("成交额", "amount"),
    ):
        if source in df.columns and target not in df.columns:
            rename[source] = target
    df = df.rename(columns=rename)
    required = {"dt", "open", "close", "high", "low"}
    if not required.issubset(df.columns):
        missing = sorted(required.difference(df.columns))
        raise ValueError(f"行情缺少字段: {missing}")
    if "vol" not in df.columns:
        df["vol"] = 0.0
    if "amount" not in df.columns:
        df["amount"] = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(
            df["vol"], errors="coerce"
        )
    df["dt"] = pd.to_datetime(df["dt"], errors="coerce")
    if df["dt"].dt.tz is not None:
        df["dt"] = df["dt"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    for col in ("open", "close", "high", "low", "vol", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["symbol"] = str(symbol)
    df = df.dropna(subset=["dt", "open", "close", "high", "low"])
    df = df.sort_values("dt").drop_duplicates("dt", keep="last")
    return df[list(STANDARD_COLUMNS)].reset_index(drop=True)


def validate_czsc_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    source: str,
    point_in_time_universe: bool = False,
) -> DataQuality:
    if frame is None or frame.empty:
        return DataQuality(
            symbol=symbol,
            rows=0,
            start="",
            end="",
            duplicate_bars=0,
            invalid_ohlc=0,
            missing_volume=0,
            timezone="naive/Asia-Shanghai",
            source=source,
            point_in_time_universe=point_in_time_universe,
        )
    duplicated = int(frame["dt"].duplicated().sum())
    invalid = (
        (frame[["open", "close", "high", "low"]] <= 0).any(axis=1)
        | (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    volume = pd.to_numeric(frame["vol"], errors="coerce")
    return DataQuality(
        symbol=symbol,
        rows=int(len(frame)),
        start=str(pd.Timestamp(frame["dt"].min())),
        end=str(pd.Timestamp(frame["dt"].max())),
        duplicate_bars=duplicated,
        invalid_ohlc=int(invalid.sum()),
        missing_volume=int((volume.isna() | (volume < 0)).sum()),
        timezone="naive/Asia-Shanghai",
        source=source,
        point_in_time_universe=point_in_time_universe,
    )


def resample_to_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """把 30 分钟 OHLCV 聚合成日线，日期对齐到日历日 00:00。"""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(STANDARD_COLUMNS))
    df = frame.copy()
    df["dt"] = pd.to_datetime(df["dt"], errors="coerce")
    if df["dt"].dt.tz is not None:
        df["dt"] = df["dt"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    df = df.dropna(subset=["dt"])
    if "symbol" not in df:
        df["symbol"] = ""
    parts: list[pd.DataFrame] = []
    for symbol, group in df.groupby("symbol", sort=False):
        bar = (
            group.set_index("dt")
            .resample("1D")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "vol": "sum",
                    "amount": "sum",
                }
            )
            .dropna(subset=["open", "close"])
        )
        bar["symbol"] = str(symbol)
        parts.append(bar.reset_index())
    if not parts:
        return pd.DataFrame(columns=list(STANDARD_COLUMNS))
    out = pd.concat(parts, ignore_index=True)
    out["dt"] = pd.to_datetime(out["dt"]).dt.normalize()
    return out[list(STANDARD_COLUMNS)].reset_index(drop=True)


def to_raw_bars(frame: pd.DataFrame, *, freq: str = "日线") -> list[Any]:
    """转换为 CZSC RawBar；延迟导入使未安装依赖时错误更清晰。"""
    try:
        from czsc import format_standard_kline
    except ImportError as exc:  # pragma: no cover - 依赖错误
        raise RuntimeError("策略二需要 czsc==1.0.0rc8，请先安装 requirements.txt") from exc
    return list(format_standard_kline(frame[list(STANDARD_COLUMNS)], freq=freq))


def symbol_cache_path(symbol: str, config: ChanStrategyConfig = DEFAULT_CONFIG) -> Path:
    sina, _ = normalize_symbol(symbol)
    return Path(config.cache_dir) / f"{sina}_30m_raw.parquet"


def load_symbol_frame(
    symbol: str,
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    refresh: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, DataQuality]:
    """读取/拉取单票30分钟行情。使用不复权价格，除权日应由研究层做事件隔离。"""
    sina, em = normalize_symbol(symbol)
    cache = symbol_cache_path(sina, config)
    start = start_date or config.data_start
    end = end_date or config.test_end
    raw = fetch_minute_30m(
        sina_symbol=sina,
        em_symbol=em,
        cache_path=cache,
        refresh=refresh,
        start_date=start,
        end_date=end,
        adjust="",
    )
    frame = standardize_czsc_frame(raw, sina)
    quality = validate_czsc_frame(
        frame,
        symbol=sina,
        source="baostock+akshare",
        point_in_time_universe=False,
    )
    if not quality.valid:
        raise ValueError(f"{sina} 30分钟行情质量检查失败: {quality}")
    return frame, quality


def load_frames_from_paths(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        raw = pd.read_parquet(path)
        symbol = str(raw["symbol"].iloc[0]) if "symbol" in raw and len(raw) else path.stem
        frames.append(standardize_czsc_frame(raw, symbol))
    if not frames:
        return pd.DataFrame(columns=list(STANDARD_COLUMNS))
    return pd.concat(frames, ignore_index=True).sort_values(["dt", "symbol"])


def write_manifest(
    qualities: Iterable[DataQuality],
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    path: Path | None = None,
) -> Path:
    target = path or (Path(config.cache_dir) / "_manifest.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(x) | {"valid": x.valid} for x in qualities]
    payload = {
        "schema_version": 1,
        "frequency": config.base_freq,
        "adjustment": "raw",
        "universe": "CSI500+CSI1000",
        "point_in_time": bool(rows) and all(x["point_in_time_universe"] for x in rows),
        "rows": rows,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def synthetic_frame(
    symbol: str = "SYNTHETIC",
    *,
    start: str = "20180101",
    end: str = "20261231",
    seed: int = 42,
) -> pd.DataFrame:
    """仅供离线测试；报告必须标注为合成数据。"""
    try:
        from czsc.mock import generate_symbol_kines
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 czsc mock 数据工具") from exc
    raw = generate_symbol_kines(symbol, "30分钟", start, end, seed=seed)
    frame = standardize_czsc_frame(raw, symbol)
    frame["vol"] = frame["vol"].replace(0, np.nan).fillna(1.0)
    return frame


__all__ = [
    "DataQuality",
    "STANDARD_COLUMNS",
    "load_frames_from_paths",
    "load_symbol_frame",
    "normalize_symbol",
    "resample_to_daily",
    "standardize_czsc_frame",
    "symbol_cache_path",
    "synthetic_frame",
    "to_raw_bars",
    "validate_czsc_frame",
    "write_manifest",
]
