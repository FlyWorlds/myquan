#!/usr/bin/env python3
"""Generate a small synthetic fixture for the development-only smoke flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "examples" / "smoke_data"
SMOKE_CONFIG = SKILL_ROOT / "examples" / "smoke_config.yaml"


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)


def _matrix(values: np.ndarray, dates: pd.DatetimeIndex, tickers: list[int]) -> pd.DataFrame:
    frame = pd.DataFrame(values, index=[int(date.strftime("%Y%m%d")) for date in dates], columns=tickers)
    frame.index.name = "date"
    return frame


def build_fixture(output_root: Path = DEFAULT_OUTPUT_ROOT, *, force: bool = True) -> dict[str, object]:
    root = output_root.expanduser().resolve()
    if root.exists() and not force:
        raise FileExistsError(f"Smoke output root already exists: {root}")
    root.mkdir(parents=True, exist_ok=True)

    dates = pd.bdate_range("2020-01-02", "2020-02-07")
    tickers = list(range(100001, 100013))
    time = np.arange(len(dates), dtype=float)[:, None]
    asset = np.arange(len(tickers), dtype=float)[None, :]
    rng = np.random.default_rng(20260807)

    log_returns = (
        0.005 * np.sin(0.43 * time + 0.71 * asset)
        + 0.003 * np.cos(0.29 * time - 0.37 * asset)
        + rng.normal(0.0, 0.0008, size=(len(dates), len(tickers)))
    )
    prices = 100.0 * np.exp(np.cumsum(log_returns, axis=0))
    forward_return = np.empty_like(prices)
    forward_return[:-2] = np.exp(log_returns[2:]) - 1.0
    forward_return[-2:] = forward_return[-3]

    noise = rng.normal(0.0, 0.001, size=forward_return.shape)
    pool_a_values = {
        "alpha191_001": forward_return + 0.20 * noise,
        "alpha191_002": np.sin(0.60 * asset + 0.25 * time) + noise,
        "alpha191_003": rng.normal(0.0, 1.0, size=forward_return.shape),
        "alpha191_004": -forward_return + 0.35 * noise,
    }
    pool_b_values = {
        "alpha101_001": forward_return + 0.10 * np.sin(asset),
        "alpha101_002": np.cos(0.50 * asset - 0.30 * time) + noise,
        "factormad_001": rng.normal(0.0, 1.0, size=forward_return.shape),
    }
    pool_a_values["alpha191_003"][0, 0] = np.nan

    keys = pd.MultiIndex.from_product(
        [[int(date.strftime("%Y%m%d")) for date in dates], tickers],
        names=["date", "ticker"],
    ).to_frame(index=False)
    pool_a = keys.copy()
    pool_b = keys.copy()
    for name, values in pool_a_values.items():
        pool_a[name] = values.reshape(-1)
    for name, values in pool_b_values.items():
        pool_b[name] = values.reshape(-1)
    _write(pool_a, root / "pool_a.parquet")
    _write(pool_b, root / "pool_b.parquet")

    market_root = root / "BackTestData_pq"
    close = _matrix(prices, dates, tickers)
    pre_close = close.shift(1).bfill()
    open_price = close * (1.0 + 0.0005 * np.sin(time))
    trade_price = (open_price + close) / 2.0
    _write(_matrix(np.ones_like(prices), dates, tickers), market_root / "adjfactor.parquet")
    _write(pre_close, market_root / "pre_close.parquet")
    _write(trade_price, market_root / "trade_price.parquet")
    _write(close, market_root / "balance_price.parquet")
    _write(open_price, market_root / "open_price.parquet")
    _write(_matrix(np.ones_like(prices, dtype=bool), dates, tickers), market_root / "mask_isopen.parquet")
    _write(_matrix(np.zeros_like(prices, dtype=bool), dates, tickers), market_root / "mask_isST.parquet")

    calendar = pd.DataFrame(
        {"calendarDate": dates.strftime("%Y-%m-%d"), "isOpen": np.ones(len(dates), dtype=int)}
    )
    names = pd.DataFrame(
        {"ticker": tickers, "secShortName": [f"SMOKE_{ticker}" for ticker in tickers]}
    )
    benchmark = pd.DataFrame(
        {
            "tradeDate": dates.strftime("%Y-%m-%d"),
            "closeIndex": close.mean(axis=1).to_numpy(),
            "openIndex": open_price.mean(axis=1).to_numpy(),
        }
    )
    _write(calendar, market_root / "calendar.parquet")
    _write(names, market_root / "name_dict.parquet")
    _write(benchmark, market_root / "Benchmark" / "benchmark.parquet")

    return {
        "status": "generated",
        "output_root": str(root),
        "config": str(SMOKE_CONFIG),
        "dates": len(dates),
        "tickers": len(tickers),
        "pool_a_factors": sorted(pool_a_values),
        "pool_b_factors": sorted(pool_b_values),
        "oos_backtest_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--no-force", action="store_true", help="Fail when output root already exists")
    args = parser.parse_args()
    payload = build_fixture(args.output_root, force=not args.no_force)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
