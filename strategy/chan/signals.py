"""CZSC 1.0.0rc8 买卖点：日线交易，30分钟只判断小转大买点。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd


M30_FREQ = "30分钟"
DAILY_FREQ = "日线"
# 兼容旧导入名
BASE_FREQ = DAILY_FREQ
HIGHER_FREQ = DAILY_FREQ
CONFIRM_FREQ = M30_FREQ


def _first_buy(freq: str) -> dict[str, Any]:
    return {"name": "cxt_first_buy_V221126", "freq": freq, "di": 1}


def _first_sell(freq: str) -> dict[str, Any]:
    return {"name": "cxt_first_sell_V221126", "freq": freq, "di": 1}


def _second_bs(freq: str) -> dict[str, Any]:
    return {
        "name": "cxt_second_bs_V230320",
        "freq": freq,
        "di": 1,
        "ma_type": "SMA",
        "timeperiod": 21,
    }


def _third_buy(freq: str) -> dict[str, Any]:
    return {"name": "cxt_third_buy_V230228", "freq": freq, "di": 1}


def _third_bs(freq: str) -> dict[str, Any]:
    return {
        "name": "cxt_third_bs_V230319",
        "freq": freq,
        "di": 1,
        "ma_type": "SMA",
        "timeperiod": 34,
    }


def _bi_status(freq: str) -> dict[str, Any]:
    return {"name": "cxt_bi_status_V230101", "freq": freq, "di": 1}


def _macd(freq: str) -> dict[str, Any]:
    return {
        "name": "tas_macd_bc_V230804",
        "freq": freq,
        "di": 1,
        "fastperiod": 12,
        "slowperiod": 26,
        "signalperiod": 9,
    }


SIGNALS_CONFIG: tuple[dict[str, Any], ...] = (
    _first_buy(M30_FREQ),
    _second_bs(M30_FREQ),
    _first_buy(DAILY_FREQ),
    _first_sell(DAILY_FREQ),
    _second_bs(DAILY_FREQ),
    _third_buy(DAILY_FREQ),
    _third_bs(DAILY_FREQ),
    _bi_status(DAILY_FREQ),
    _macd(DAILY_FREQ),
)


@dataclass(frozen=True)
class ChanSignalSnapshot:
    buy1: bool = False
    buy2: bool = False
    buy3: bool = False
    sell1: bool = False
    sell2: bool = False
    sell3: bool = False
    bi_up: bool = False
    bi_down: bool = False
    daily_up: bool = False
    macd_bottom_divergence: bool = False
    macd_top_divergence: bool = False
    limit_up: bool = False
    limit_down: bool = False
    suspended: bool = False

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "ChanSignalSnapshot":
        return cls(
            buy1=bool(row.get("buy1", False)),
            buy2=bool(row.get("buy2", False)),
            buy3=bool(row.get("buy3", False)),
            sell1=bool(row.get("sell1", False)),
            sell2=bool(row.get("sell2", False)),
            sell3=bool(row.get("sell3", False)),
            bi_up=bool(row.get("bi_up", False)),
            bi_down=bool(row.get("bi_down", False)),
            daily_up=bool(row.get("daily_up", False)),
            macd_bottom_divergence=bool(row.get("macd_bottom_divergence", False)),
            macd_top_divergence=bool(row.get("macd_top_divergence", False)),
            limit_up=bool(row.get("limit_up", False)),
            limit_down=bool(row.get("limit_down", False)),
            suspended=bool(row.get("suspended", False)),
        )


def _find_column(columns: Iterable[str], fragments: tuple[str, ...]) -> str | None:
    for col in columns:
        text = str(col)
        if all(fragment in text for fragment in fragments):
            return text
    return None


def _starts_with(frame: pd.DataFrame, column: str | None, prefix: str) -> pd.Series:
    if column is None:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame[column].fillna("").astype(str).str.startswith(prefix)


def _as_bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame[column].fillna(False).astype(bool)


def project_signal_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """把带版本的 CZSC 字符串列投影为稳定布尔列。"""
    out = frame.copy()
    for column in ("open", "close", "high", "low", "vol", "amount"):
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    cols = [str(x) for x in out.columns]
    m30_buy1 = _find_column(cols, (M30_FREQ, "BUY1"))
    m30_second = _find_column(cols, (M30_FREQ, "BS2辅助"))
    daily_buy1 = _find_column(cols, (DAILY_FREQ, "BUY1"))
    daily_sell1 = _find_column(cols, (DAILY_FREQ, "SELL1"))
    daily_second = _find_column(cols, (DAILY_FREQ, "BS2辅助"))
    daily_third_pure = _find_column(cols, (DAILY_FREQ, "三买辅助"))
    daily_third_bs = _find_column(cols, (DAILY_FREQ, "BS3辅助"))
    daily_bi = _find_column(cols, (DAILY_FREQ, "表里关系"))
    daily_macd = _find_column(cols, (DAILY_FREQ, "MACD背驰"))

    out["m30_buy1"] = _starts_with(out, m30_buy1, "一买")
    out["m30_buy2"] = _starts_with(out, m30_second, "二买")
    out["daily_buy1"] = _starts_with(out, daily_buy1, "一买")
    out["daily_sell1"] = _starts_with(out, daily_sell1, "一卖")
    out["daily_buy2"] = _starts_with(out, daily_second, "二买")
    out["daily_sell2"] = _starts_with(out, daily_second, "二卖")
    out["daily_buy3"] = _starts_with(out, daily_third_pure, "三买") | _starts_with(
        out, daily_third_bs, "三买"
    )
    out["daily_sell3"] = _starts_with(out, daily_third_bs, "三卖")
    out["daily_bi_up"] = _starts_with(out, daily_bi, "向上")
    out["daily_bi_down"] = _starts_with(out, daily_bi, "向下")
    out["daily_macd_bottom"] = _starts_with(out, daily_macd, "底部")
    out["daily_macd_top"] = _starts_with(out, daily_macd, "顶部")
    return out


def apply_xiaozhuan(frame: pd.DataFrame) -> pd.DataFrame:
    """日线向下/一买/底背驰环境下，30分钟一买/二买才视为小转大买点。

    卖点与三买只用日线。该函数在日线收盘后的日频面板上调用，不使用未来 K 线。
    """
    out = frame.copy()
    turn = (
        _as_bool(out, "daily_bi_down")
        | _as_bool(out, "daily_buy1")
        | _as_bool(out, "daily_macd_bottom")
    )
    out["daily_turn_env"] = turn
    out["buy1"] = _as_bool(out, "m30_buy1") & turn
    out["buy2"] = _as_bool(out, "m30_buy2") & turn
    out["buy3"] = _as_bool(out, "daily_buy3")
    out["sell1"] = _as_bool(out, "daily_sell1")
    out["sell2"] = _as_bool(out, "daily_sell2")
    out["sell3"] = _as_bool(out, "daily_sell3")
    out["bi_up"] = _as_bool(out, "daily_bi_up")
    out["bi_down"] = _as_bool(out, "daily_bi_down")
    out["daily_up"] = _as_bool(out, "daily_bi_up")
    out["macd_bottom_divergence"] = _as_bool(out, "daily_macd_bottom")
    out["macd_top_divergence"] = _as_bool(out, "daily_macd_top")
    return out


def _naive_dt(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    if getattr(dt.dt, "tz", None) is not None:
        return dt.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return dt


def collapse_signals_to_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """把 30 分钟信号收盘折叠成日频：当日任一 30 分钟买点取 max，日线环境取当日最后一根。"""
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    df["dt"] = _naive_dt(df["dt"])
    df["date"] = df["dt"].dt.normalize()
    if "symbol" not in df:
        df["symbol"] = ""
    any_cols = ("m30_buy1", "m30_buy2")
    last_cols = (
        "daily_buy1",
        "daily_buy2",
        "daily_buy3",
        "daily_sell1",
        "daily_sell2",
        "daily_sell3",
        "daily_bi_up",
        "daily_bi_down",
        "daily_macd_bottom",
        "daily_macd_top",
    )
    agg: dict[str, str] = {}
    for col in any_cols:
        if col in df:
            agg[col] = "max"
    for col in last_cols:
        if col in df:
            agg[col] = "last"
    grouped = df.groupby(["symbol", "date"], as_index=False).agg(agg)
    grouped = grouped.rename(columns={"date": "dt"})
    return apply_xiaozhuan(grouped)


def generate_signal_frame(
    bars: list[Any],
    *,
    signals_config: Iterable[Mapping[str, Any]] = SIGNALS_CONFIG,
    init_n: int = 300,
    sdt: str | None = None,
) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    try:
        from czsc import generate_czsc_signals
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("策略二需要 czsc==1.0.0rc8") from exc
    kwargs: dict[str, Any] = {
        "signals_config": [dict(x) for x in signals_config],
        "init_n": int(init_n),
        "df": True,
    }
    if sdt is not None:
        kwargs["sdt"] = str(sdt)
    raw = generate_czsc_signals(bars, **kwargs)
    out = project_signal_columns(raw)
    out["dt"] = pd.to_datetime(out["dt"])
    return out.sort_values("dt").reset_index(drop=True)


__all__ = [
    "BASE_FREQ",
    "CONFIRM_FREQ",
    "DAILY_FREQ",
    "HIGHER_FREQ",
    "M30_FREQ",
    "SIGNALS_CONFIG",
    "ChanSignalSnapshot",
    "apply_xiaozhuan",
    "collapse_signals_to_daily",
    "generate_signal_frame",
    "project_signal_columns",
]
