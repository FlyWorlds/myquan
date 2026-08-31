"""因子18 恐慌日 → OpenBreak 日期门控（开盘可观测，无未来函数）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from strategy.factors.factor18 import LD_OPEN_PANIC_MIN, factor18_signal

_MYQUAN = Path(__file__).resolve().parents[3]
_EMOTION_DIR = _MYQUAN / "backtest" / "strategy9_limit_down_emotion"
_EMOTION_CSV = _EMOTION_DIR / "emotion_index_merged.csv"
_EMOTION_PARQUET = _EMOTION_DIR / "mkt_ld_open_zz1000.parquet"


def _norm_day(value: Any) -> str:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y-%m-%d")


def load_ld_open_daily(*, path: Path | None = None) -> pd.DataFrame:
    """读取已缓存的中证1000 低开跌停家数（离线）。"""
    if path is not None:
        src = Path(path)
        if src.suffix == ".parquet":
            df = pd.read_parquet(src)
        else:
            df = pd.read_csv(src)
    elif _EMOTION_CSV.is_file():
        df = pd.read_csv(_EMOTION_CSV)
    elif _EMOTION_PARQUET.is_file():
        df = pd.read_parquet(_EMOTION_PARQUET)
    else:
        return pd.DataFrame(columns=["date", "mkt_ld_open"])
    if "date" not in df.columns:
        return pd.DataFrame(columns=["date", "mkt_ld_open"])
    out = df.copy()
    out["date"] = [_norm_day(x) for x in out["date"]]
    out = out[out["date"] != ""]
    if "mkt_ld_open" not in out.columns:
        out["mkt_ld_open"] = 0
    return out


def emotion_flag_by_date(
    *,
    min_ld: int = LD_OPEN_PANIC_MIN,
    daily: pd.DataFrame | None = None,
) -> dict[str, bool]:
    """mkt_ld_open >= min_ld 的日期 → True。"""
    df = load_ld_open_daily() if daily is None else daily
    out: dict[str, bool] = {}
    if df is None or df.empty or "mkt_ld_open" not in df.columns:
        return out
    for _, row in df.iterrows():
        day = _norm_day(row.get("date"))
        if not day:
            continue
        n = row.get("mkt_ld_open")
        if pd.isna(n):
            continue
        out[day] = int(n) >= int(min_ld)
    return out


def panic_halt_by_date(
    daily: pd.DataFrame | None = None,
    *,
    panic_min: int = LD_OPEN_PANIC_MIN,
) -> dict[str, bool]:
    """恐慌日 → True（当日跳过新开仓，已否决的旧门控）。"""
    return emotion_flag_by_date(min_ld=panic_min, daily=daily)


def phase_on_day(day: str, *, ld_open: int | None = None) -> dict[str, Any]:
    if ld_open is not None:
        return factor18_signal(ld_open=int(ld_open))
    halt = panic_halt_by_date()
    key = _norm_day(day)
    if key and halt.get(key):
        return factor18_signal(ld_open=LD_OPEN_PANIC_MIN)
    df = load_ld_open_daily()
    if df.empty or "mkt_ld_open" not in df.columns:
        return factor18_signal(ld_open=None)
    hit = df.loc[df["date"] == key]
    if hit.empty:
        return factor18_signal(ld_open=None)
    return factor18_signal(ld_open=int(hit.iloc[0]["mkt_ld_open"]))


__all__ = [
    "load_ld_open_daily",
    "emotion_flag_by_date",
    "panic_halt_by_date",
    "phase_on_day",
]
