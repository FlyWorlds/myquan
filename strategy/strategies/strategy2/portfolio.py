"""策略二选股、特征面板和组合运行入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from strategy.chan.config import DEFAULT_CONFIG, ChanStrategyConfig
from strategy.chan.data_adapter import (
    DataQuality,
    load_symbol_frame,
    normalize_symbol,
    resample_to_daily,
    to_raw_bars,
    write_manifest,
)
from strategy.chan.features import build_feature_frame
from strategy.chan.signals import collapse_signals_to_daily, generate_signal_frame
from strategy.strategies.strategy2.backtest import (
    ChanBacktestResult,
    derive_eligibility,
    run_chan_backtest,
)
from strategy.strategies.strategy2.frozen_combo import apply_frozen_combo, load_frozen_combo


BOOL_FILL = (
    "buy1",
    "buy2",
    "buy3",
    "sell1",
    "sell2",
    "sell3",
    "m30_buy1",
    "m30_buy2",
    "daily_buy1",
    "daily_turn_env",
    "daily_bi_down",
    "daily_bi_up",
    "bi_up",
    "bi_down",
    "daily_up",
    "macd_bottom_divergence",
    "macd_top_divergence",
)


def build_xiaozhuan_daily_features(
    raw_30m: pd.DataFrame,
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    include_structure: bool = True,
    sdt: str | None = None,
) -> pd.DataFrame:
    """30分钟生成信号，折叠为日线小转大买点后再提日线结构特征。"""
    bars_30 = to_raw_bars(raw_30m, freq=config.confirm_freq)
    signals = generate_signal_frame(
        bars_30,
        init_n=config.confirm_warmup_bars,
        sdt=sdt or pd.Timestamp(config.discovery_start).strftime("%Y-%m-%d"),
    )
    daily_flags = collapse_signals_to_daily(signals)
    daily_ohlc = resample_to_daily(raw_30m)
    daily_ohlc["dt"] = pd.to_datetime(daily_ohlc["dt"]).dt.normalize()
    if daily_flags.empty:
        daily = daily_ohlc
    else:
        daily_flags["dt"] = pd.to_datetime(daily_flags["dt"]).dt.normalize()
        overlap = [
            col
            for col in daily_ohlc.columns
            if col in daily_flags.columns and col not in ("dt", "symbol")
        ]
        flags = daily_flags.drop(columns=overlap, errors="ignore")
        daily = daily_ohlc.merge(flags, on=["dt", "symbol"], how="left")
    for col in BOOL_FILL:
        if col in daily:
            daily[col] = daily[col].fillna(False).astype(bool)
        elif col in ("buy1", "buy2", "sell2", "sell3"):
            daily[col] = False
    bars_d = to_raw_bars(daily_ohlc, freq=config.base_freq)
    return build_feature_frame(daily, bars_d, include_structure=include_structure)


def build_symbol_features(
    symbol: str,
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    refresh: bool = False,
    include_structure: bool = True,
) -> tuple[pd.DataFrame, object]:
    sina, _ = normalize_symbol(symbol)
    feat_path = Path(config.cache_dir) / f"{sina}_daily_features.parquet"
    if feat_path.exists() and not refresh:
        features = pd.read_parquet(feat_path)
        quality = DataQuality(
            symbol=sina,
            rows=int(len(features)),
            start=str(features["dt"].min()) if len(features) else "",
            end=str(features["dt"].max()) if len(features) else "",
            duplicate_bars=0,
            invalid_ohlc=0,
            missing_volume=0,
            timezone="naive/Asia-Shanghai",
            source="feature_cache",
            point_in_time_universe=False,
        )
        return features, quality
    frame, quality = load_symbol_frame(symbol, config=config, refresh=refresh)
    features = build_xiaozhuan_daily_features(
        frame,
        config=config,
        include_structure=include_structure,
    )
    feat_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(feat_path, index=False)
    return features, quality


def build_feature_panel(
    symbols: Iterable[str],
    *,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    refresh: bool = False,
    continue_on_error: bool = True,
    panel_path: Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    qualities = []
    failures: list[dict[str, str]] = []
    symbol_list = [str(x) for x in symbols]
    total = len(symbol_list)
    for i, symbol in enumerate(symbol_list, 1):
        try:
            print(f"[{i}/{total}] {symbol} 开始", flush=True)
            feature, quality = build_symbol_features(
                symbol, config=config, refresh=refresh
            )
            if not feature.empty:
                frames.append(feature)
                qualities.append(quality)
            print(
                f"[{i}/{total}] {symbol} rows={len(feature)} ok={len(frames)} fail={len(failures)}",
                flush=True,
            )
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})
            print(f"[{i}/{total}] {symbol} FAIL {exc}", flush=True)
            if not continue_on_error:
                raise
    if not frames:
        raise RuntimeError(f"没有成功构建缠论特征；失败样例: {failures[:3]}")
    panel = pd.concat(frames, ignore_index=True).sort_values(["dt", "symbol"])
    panel = derive_eligibility(
        panel, candidate_timeout_bars=config.candidate_timeout_bars
    )
    panel = apply_frozen_combo(panel, min_cross_section=config.min_eligible)
    target = panel_path or (Path(config.cache_dir) / "feature_panel.parquet")
    target.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(target, index=False)
    write_manifest(qualities, config=config)
    if failures:
        pd.DataFrame(failures).to_csv(
            Path(config.cache_dir) / "failed_symbols.csv", index=False
        )
    return panel


def run_chan_portfolio(
    *,
    panel: pd.DataFrame | None = None,
    panel_path: Path | str | None = None,
    factor_column: str | None = None,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    start: str | None = None,
    end: str | None = None,
    fee_rate: float | None = None,
) -> ChanBacktestResult:
    if panel is None:
        path = Path(panel_path) if panel_path else Path(config.cache_dir) / "feature_panel.parquet"
        if not path.exists():
            raise FileNotFoundError(f"缠论特征面板不存在: {path}")
        panel = pd.read_parquet(path)
    if factor_column is None:
        spec = load_frozen_combo()
        if spec.get("members"):
            panel = apply_frozen_combo(panel, min_cross_section=config.min_eligible)
            factor_column = "factor_score"
    return run_chan_backtest(
        panel,
        factor_column=factor_column,
        config=config,
        start=start,
        end=end,
        fee_rate=fee_rate,
    )


__all__ = [
    "build_feature_panel",
    "build_symbol_features",
    "build_xiaozhuan_daily_features",
    "run_chan_portfolio",
]
