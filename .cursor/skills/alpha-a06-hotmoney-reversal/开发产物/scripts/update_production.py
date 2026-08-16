from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from factor import (
    DEFAULT_DATA_VERSION,
    calculate_factor,
    extract_calendar_trade_dates,
    load_real_lhb_details,
    load_real_quotes,
    load_real_trade_calendar,
    validate_production_output,
)


ALPHA_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ALPHA_ROOT / "生产产物" / "数据库.parquet"


def _display_path(path: str | Path) -> str:
    try:
        return os.path.relpath(Path(path).resolve(), Path.cwd().resolve())
    except ValueError:
        return Path(path).name


def _normalise_date(value: str) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"无法解析日期: {value}")
    return parsed.strftime("%Y-%m-%d")


def _compact_date(value: str) -> str:
    return _normalise_date(value).replace("-", "")


def _three_year_start(end_date: str) -> str:
    parsed = pd.to_datetime(_normalise_date(end_date)).date()
    return (parsed - timedelta(days=365 * 3 + 2)).strftime("%Y%m%d")


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _resolve_start_date(
    existing: pd.DataFrame,
    bootstrap_start_date: str,
    end_date: str,
    lookback_days: int,
    full_refresh: bool,
) -> str:
    if full_refresh or existing.empty:
        return _compact_date(bootstrap_start_date)
    max_existing = pd.to_datetime(existing["trade_date"]).max().date()
    recompute_start = max_existing - timedelta(days=lookback_days)
    bootstrap = pd.to_datetime(_normalise_date(bootstrap_start_date)).date()
    return max(recompute_start, bootstrap).strftime("%Y%m%d")


def _shift_start_date(start_date: str, bootstrap_start_date: str, lookback_days: int) -> str:
    start = pd.to_datetime(_normalise_date(start_date)).date()
    bootstrap = pd.to_datetime(_normalise_date(bootstrap_start_date)).date()
    shifted = start - timedelta(days=max(0, lookback_days))
    return max(shifted, bootstrap).strftime("%Y%m%d")


def _detail_symbols(details: pd.DataFrame) -> list[str]:
    detail_frame = pd.DataFrame(details).copy()
    symbol_col = "symbol" if "symbol" in detail_frame.columns else "ts_code"
    return sorted(detail_frame[symbol_col].astype(str).unique())


def _merge_existing(existing: pd.DataFrame, fresh: pd.DataFrame, recompute_start: str) -> pd.DataFrame:
    if existing.empty:
        return fresh
    cutoff = _normalise_date(recompute_start)
    preserved = existing.loc[existing["trade_date"].astype(str) < cutoff].copy()
    merged = pd.concat([preserved, fresh], ignore_index=True)
    merged = merged.sort_values(["trade_date", "rank", "ts_code"]).reset_index(drop=True)
    return merged


def update_production(
    output_path: Path,
    end_date: str,
    bootstrap_start_date: str,
    lookback_days: int,
    quality_lookback_days: int,
    full_refresh: bool,
    data_version: str,
) -> pd.DataFrame:
    existing = _read_existing(output_path)
    version_changed = not existing.empty and set(existing.get("data_version", pd.Series(dtype=str)).astype(str)) != {data_version}
    effective_full_refresh = full_refresh or version_changed
    start_date = _resolve_start_date(
        existing=existing,
        bootstrap_start_date=bootstrap_start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        full_refresh=effective_full_refresh,
    )
    fetch_start_date = _shift_start_date(start_date, "19000101", quality_lookback_days)
    details = load_real_lhb_details(start_date=fetch_start_date, end_date=end_date)
    calendar = load_real_trade_calendar(start_date=fetch_start_date, end_date=end_date)
    quotes = load_real_quotes(start_date=fetch_start_date, end_date=end_date, symbols=_detail_symbols(details))
    fresh_all = calculate_factor(
        details,
        trade_calendar=calendar,
        quotes=quotes,
        data_version=data_version,
        update_time=datetime.now().isoformat(timespec="seconds"),
        dynamic_seat_quality=False,
    )
    fresh = fresh_all.loc[pd.to_datetime(fresh_all["trade_date"]) >= pd.to_datetime(_normalise_date(start_date))].copy()
    merged = fresh if effective_full_refresh else _merge_existing(existing, fresh, start_date)
    validation_calendar = load_real_trade_calendar(
        start_date=merged["trade_date"].min(),
        end_date=end_date,
    )
    validate_production_output(merged, valid_trade_dates=extract_calendar_trade_dates(validation_calendar))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    merged.to_parquet(temp_path, index=False)
    temp_path.replace(output_path)
    return merged


def _parse_args() -> argparse.Namespace:
    today = date.today().strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="每日更新 A06 游资席位协同 Alpha 生产 Parquet")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--end-date", default=today)
    parser.add_argument("--bootstrap-start-date", default=None, help="首次全量生成起点；默认 end-date 往前近三年")
    parser.add_argument("--lookback-days", type=int, default=10, help="增量更新时回看重算天数，用于覆盖连续三日席位状态")
    parser.add_argument("--quality-lookback-days", type=int, default=260, help="增量更新时额外拉取的原始数据回看窗口")
    parser.add_argument("--full-refresh", action="store_true", help="忽略已有数据库，从 bootstrap-start-date 全量重算")
    parser.add_argument("--data-version", default=DEFAULT_DATA_VERSION)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    end_date = _compact_date(args.end_date)
    bootstrap_start_date = args.bootstrap_start_date or _three_year_start(end_date)
    result = update_production(
        output_path=Path(args.output),
        end_date=end_date,
        bootstrap_start_date=bootstrap_start_date,
        lookback_days=args.lookback_days,
        quality_lookback_days=args.quality_lookback_days,
        full_refresh=args.full_refresh,
        data_version=args.data_version,
    )
    print(f"更新完成: {_display_path(args.output)}")
    print(f"rows: {len(result)}")
    print(f"date_min: {result['trade_date'].min()}")
    print(f"date_max: {result['trade_date'].max()}")
    print(f"data_version: {args.data_version}")


if __name__ == "__main__":
    main()
