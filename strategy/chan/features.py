"""缠论结构特征与截面因子候选。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _direction_sign(direction: Any) -> float:
    text = str(direction)
    return 1.0 if ("向上" in text or "Up" in text) else -1.0


def extract_structure_features(
    bars: list[Any],
    *,
    warmup_bars: int = 100,
) -> pd.DataFrame:
    """流式提取末笔与最近中枢特征，不使用未来 K 线。"""
    columns = [
        "dt",
        "symbol",
        "bi_count",
        "bi_direction",
        "bi_length",
        "bi_slope",
        "bi_snr",
        "bi_power_price",
        "zs_width",
        "zs_position",
    ]
    if len(bars) <= warmup_bars:
        return pd.DataFrame(columns=columns)
    try:
        from czsc import CZSC, ZS
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("策略二需要 czsc==1.0.0rc8") from exc

    seed_n = min(max(50, int(warmup_bars)), len(bars) - 1)
    analyzer = CZSC(bars[:seed_n])
    rows: list[dict[str, Any]] = []
    for bar in bars[seed_n:]:
        analyzer.update(bar)
        bis = analyzer.bi_list
        row: dict[str, Any] = {
            "dt": pd.Timestamp(bar.dt),
            "symbol": str(bar.symbol),
            "bi_count": float(len(bis)),
            "bi_direction": np.nan,
            "bi_length": np.nan,
            "bi_slope": np.nan,
            "bi_snr": np.nan,
            "bi_power_price": np.nan,
            "zs_width": np.nan,
            "zs_position": np.nan,
        }
        if bis:
            bi = bis[-1]
            row.update(
                {
                    "bi_direction": _direction_sign(bi.direction),
                    "bi_length": float(bi.length),
                    "bi_slope": float(bi.slope),
                    "bi_snr": float(bi.SNR),
                    "bi_power_price": float(bi.power_price),
                }
            )
        if len(bis) >= 5:
            try:
                zs = ZS(bis[-5:])
                if zs.is_valid():
                    center = float(zs.zz)
                    width = max(float(zs.zg) - float(zs.zd), 0.0)
                    row["zs_width"] = width / center if center > 0 else np.nan
                    row["zs_position"] = (
                        (float(bar.close) - center) / width if width > 0 else 0.0
                    )
            except (TypeError, ValueError, AttributeError):
                pass
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def _bars_since(flag: pd.Series, cap: int = 320) -> pd.Series:
    values = flag.fillna(False).astype(bool).to_numpy()
    out = np.full(len(values), np.nan)
    last = -10**9
    for i, hit in enumerate(values):
        if hit:
            last = i
        distance = i - last
        if distance <= cap:
            out[i] = float(distance)
    return pd.Series(out, index=flag.index)


def add_derived_features(frame: pd.DataFrame) -> pd.DataFrame:
    """只用当前及历史行生成连续特征。"""
    if frame.empty:
        return frame.copy()
    out = frame.sort_values(["symbol", "dt"]).copy()
    grouped = out.groupby("symbol", sort=False, group_keys=False)
    for name in ("buy1", "buy2", "buy3", "sell2", "sell3"):
        if name in out:
            out[f"{name}_recency"] = grouped[name].apply(_bars_since)

    close = grouped["close"]
    ret = close.pct_change()
    out["ret_1"] = ret
    out["ret_5"] = close.pct_change(5)
    out["ret_8"] = close.pct_change(8)
    out["ret_20"] = close.pct_change(20)
    out["ret_40"] = close.pct_change(40)
    out["volatility_20"] = ret.groupby(out["symbol"]).transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    out["volatility_40"] = ret.groupby(out["symbol"]).transform(
        lambda x: x.rolling(40, min_periods=20).std()
    )
    out["vol_5"] = ret.groupby(out["symbol"]).transform(
        lambda x: x.rolling(5, min_periods=3).std()
    )
    high_20 = grouped["high"].transform(lambda x: x.rolling(20, min_periods=10).max())
    low_20 = grouped["low"].transform(lambda x: x.rolling(20, min_periods=10).min())
    high_40 = grouped["high"].transform(lambda x: x.rolling(40, min_periods=20).max())
    low_40 = grouped["low"].transform(lambda x: x.rolling(40, min_periods=20).min())
    out["range_20"] = high_20 - low_20
    out["range_40"] = high_40 - low_40
    out["range_position_20"] = (out["close"] - low_20) / out["range_20"].replace(0, np.nan)
    out["range_position_40"] = (out["close"] - low_40) / out["range_40"].replace(0, np.nan)
    if "amount" not in out:
        out["amount"] = 0.0
    amount = pd.to_numeric(out["amount"], errors="coerce")
    out["turnover_log"] = np.log1p(amount)
    out["amount_mean_20"] = amount.groupby(out["symbol"]).transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    sma20 = grouped["close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    out["buy1_freshness"] = np.exp(-out.get("buy1_recency", np.nan) / 20.0)
    out["buy2_freshness"] = np.exp(-out.get("buy2_recency", np.nan) / 12.0)
    out["buy3_freshness"] = np.exp(-out.get("buy3_recency", np.nan) / 12.0)

    def _num(name: str) -> pd.Series:
        if name not in out:
            return pd.Series(np.nan, index=out.index, dtype=float)
        return pd.to_numeric(out[name], errors="coerce")

    def _flag(name: str) -> pd.Series:
        if name not in out:
            return pd.Series(0.0, index=out.index)
        return out[name].fillna(False).astype(float)

    turn = _flag("daily_turn_env")
    if turn.sum() == 0:
        turn = _flag("buy1") + _flag("buy2")
        turn = (turn > 0).astype(float)
    out["xiaozhuan_confirm"] = _flag("m30_buy2") * (1.0 + _flag("daily_macd_bottom")) * (
        1.0 + turn
    )
    out["oversold_in_turn"] = (1.0 - out["range_position_20"]) * (1.0 + turn)
    out["volume_confirm"] = amount / out["amount_mean_20"].replace(0, np.nan)
    out["liquidity"] = out["turnover_log"]
    out["low_volatility"] = -out["volatility_20"]
    out["skip_momentum"] = out["ret_20"] - out["ret_5"]
    out["reversal_5"] = -out["ret_5"]
    out["amihud_liquidity"] = -out["ret_1"].abs() / amount.replace(0, np.nan)
    out["range_quality"] = -(out["high"] - out["low"]) / out["close"].replace(0, np.nan)
    out["ma_extension"] = -(out["close"] / sma20.replace(0, np.nan) - 1.0)
    out["vol_compress"] = out["vol_5"] / out["volatility_20"].replace(0, np.nan)
    out["structure_efficiency"] = (
        _num("bi_snr") * _num("bi_direction") * np.sign(_num("bi_slope"))
    )
    zs_width = _num("zs_width")
    zs_position = _num("zs_position")
    out["pivot_break_strength"] = zs_position / (1.0 + zs_width.abs())
    out["zs_discount"] = -zs_position
    out["down_bi_force"] = -_num("bi_slope") * (_num("bi_direction") < 0).astype(float)
    out["divergence_proxy"] = -out["ret_8"] + 0.5 * out["ret_40"]
    out["risk_adjusted_reversal"] = -out["ret_8"] / out["volatility_40"].replace(
        0, np.nan
    )
    out["macd_align"] = _flag("macd_bottom_divergence") * (1.0 + _flag("daily_bi_down"))
    out["multi_freq_alignment"] = (
        _flag("bi_up") + _flag("daily_up") + _flag("macd_bottom_divergence")
    )
    return out


FACTOR_CANDIDATES: tuple[str, ...] = (
    "xiaozhuan_confirm",
    "oversold_in_turn",
    "volume_confirm",
    "liquidity",
    "low_volatility",
    "skip_momentum",
    "reversal_5",
    "amihud_liquidity",
    "range_quality",
    "ma_extension",
    "vol_compress",
    "buy2_freshness",
    "macd_align",
    "zs_discount",
    "down_bi_force",
    "structure_efficiency",
    "pivot_break_strength",
    "divergence_proxy",
    "risk_adjusted_reversal",
    "range_position_20",
    "multi_freq_alignment",
)


def _session_date(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return dt.dt.normalize()


def build_feature_frame(
    signal_frame: pd.DataFrame,
    bars: list[Any],
    *,
    include_structure: bool = True,
) -> pd.DataFrame:
    structures = (
        extract_structure_features(bars) if include_structure else pd.DataFrame()
    )
    base = signal_frame.copy()
    base["dt"] = _session_date(base["dt"])
    if not structures.empty:
        structures["dt"] = _session_date(structures["dt"])
        base = base.merge(structures, on=["dt", "symbol"], how="left")
    return add_derived_features(base)


__all__ = [
    "FACTOR_CANDIDATES",
    "add_derived_features",
    "build_feature_frame",
    "extract_structure_features",
]
