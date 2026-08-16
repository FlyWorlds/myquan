#!/usr/bin/env python3
"""backtest.py — standalone, framework-neutral RESEARCH backtest for an overseas
trend / macro strategy.

Reads a public overseas price CSV (Yahoo / stooq daily, columns ``date, close`` and
optionally ``open``) plus a signal, maps the signal to a target position with
vol-target or fixed-fraction sizing, applies risk limits, and simulates returns with
realistic costs/slippage. Signals are generated at ``t`` and traded at ``t+1`` to avoid
look-ahead. It reports CAGR / Sharpe / max drawdown / turnover and writes an equity
curve.

RESEARCH ONLY. This script places no live orders, connects to no broker, and uses no
live data. Results are illustrative historical statistics, not predictions, and do not
constitute investment advice.

Dependencies: Python standard library + pandas. If pandas is missing the script exits
with a clear install hint (graceful degradation).

Examples:
    # Self-contained demo (synthetic random-walk prices, built-in MA-crossover signal):
    python backtest.py --demo

    # Real run: your downloaded price CSV + a signal CSV (date,value):
    python backtest.py --prices CL=F.csv --signal my_signal.csv --sizing vol_target

    # Real run with the built-in moving-average-crossover signal:
    python backtest.py --prices CL=F.csv --signal builtin_ma --sizing fixed_fraction
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # graceful degradation — do not swallow, exit non-zero with a hint
    sys.stderr.write(
        "error: this backtest needs pandas.\n"
        "install it with:  pip install pandas\n"
    )
    raise SystemExit(3)


# --------------------------------------------------------------------------- data
def _read_csv(path: Path) -> "pd.DataFrame":
    return pd.read_csv(path)


def load_prices(path: Path) -> "pd.DataFrame":
    """Load a price CSV with date, close and optional open; clean and sort."""
    df = _read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "date" not in cols or "close" not in cols:
        raise ValueError("price CSV must contain 'date' and 'close' columns")
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[cols["date"]])
    out["close"] = pd.to_numeric(df[cols["close"]], errors="coerce")
    out["open"] = (
        pd.to_numeric(df[cols["open"]], errors="coerce") if "open" in cols else float("nan")
    )
    out = out.dropna(subset=["date", "close"]).sort_values("date")
    out = out.drop_duplicates("date", keep="last").reset_index(drop=True)
    if out.empty:
        raise ValueError("price data is empty after cleaning")
    if (out["close"] <= 0).any():
        raise ValueError("price data contains non-positive close prices")
    return out


def make_demo_prices(n: int = 750, seed: int = 7) -> "pd.DataFrame":
    """Synthetic random-walk daily prices so the script is runnable without any data."""
    import random

    rng = random.Random(seed)
    dates = pd.bdate_range("2021-01-01", periods=n)
    price = 100.0
    closes = []
    for _ in range(n):
        price *= math.exp(rng.gauss(0.0002, 0.012))
        closes.append(price)
    return pd.DataFrame({"date": dates, "close": closes, "open": closes})


# ------------------------------------------------------------------------- signal
def builtin_ma_signal(prices: "pd.DataFrame", fast: int = 20, slow: int = 100) -> "pd.Series":
    """Built-in trend signal: fast SMA minus slow SMA (positive = uptrend).

    Uses only information up to and including ``t`` (no future leak)."""
    close = prices.set_index("date")["close"]
    return (close.rolling(fast).mean() - close.rolling(slow).mean())


def load_signal(spec: str, prices: "pd.DataFrame") -> "pd.Series":
    """Return a signal series indexed by date. ``spec`` is 'builtin_ma' or a CSV path."""
    if spec == "builtin_ma":
        return builtin_ma_signal(prices)
    path = Path(spec)
    if not path.exists():
        raise FileNotFoundError(
            f"signal file not found: {spec} (use 'builtin_ma' for the demo signal)"
        )
    df = _read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "date" not in cols or "value" not in cols:
        raise ValueError("signal CSV must contain 'date' and 'value' columns")
    s = pd.Series(
        pd.to_numeric(df[cols["value"]], errors="coerce").values,
        index=pd.to_datetime(df[cols["date"]]),
    )
    return s.sort_index()


def zscore(sig: "pd.Series", window: int = 60) -> "pd.Series":
    mean = sig.rolling(window).mean()
    std = sig.rolling(window).std(ddof=0)
    return (sig - mean) / std.replace(0.0, float("nan"))


# ---------------------------------------------------------------------- positions
def target_position(z: "pd.Series", enter: float, exit_: float, long_only: bool) -> "pd.Series":
    """Hysteresis threshold band: enter when |z|>enter, exit when |z|<exit."""
    pos = []
    state = 0.0
    for val in z:
        if val != val:  # NaN
            pos.append(0.0)
            continue
        if state == 0.0:
            if val > enter:
                state = 1.0
            elif val < -enter and not long_only:
                state = -1.0
        else:
            if abs(val) < exit_:
                state = 0.0
            elif val > enter:
                state = 1.0
            elif val < -enter and not long_only:
                state = -1.0
        pos.append(max(state, 0.0) if long_only else state)
    return pd.Series(pos, index=z.index)


def size_weights(
    direction: "pd.Series",
    ret: "pd.Series",
    sizing: str,
    target_vol: float,
    fixed_fraction: float,
    vol_window: int,
    max_leverage: float,
    max_weight: float,
    annualization: float,
) -> "pd.Series":
    if sizing == "vol_target":
        realized = ret.rolling(vol_window).std(ddof=0) * math.sqrt(annualization)
        scale = (target_vol / realized).clip(upper=max_leverage)
        weight = direction * scale
    else:  # fixed_fraction
        weight = direction * fixed_fraction
    weight = weight.fillna(0.0).clip(-max_weight, max_weight)
    return weight


# ----------------------------------------------------------------------- backtest
def run(cfg: argparse.Namespace) -> dict:
    prices = make_demo_prices() if cfg.demo else load_prices(Path(cfg.prices))
    signal = builtin_ma_signal(prices) if cfg.demo else load_signal(cfg.signal, prices)

    px = prices.set_index("date")
    df = pd.DataFrame(index=px.index)
    df["close"] = px["close"]
    df["ret"] = df["close"].pct_change().fillna(0.0)
    df["signal"] = signal.reindex(df.index)

    z = zscore(df["signal"], cfg.z_window) if cfg.zscore else df["signal"]
    direction = target_position(z, cfg.enter, cfg.exit, cfg.long_only)

    weight = size_weights(
        direction, df["ret"], cfg.sizing, cfg.target_vol, cfg.fixed_fraction,
        cfg.vol_window, cfg.max_leverage, cfg.max_weight, cfg.annualization,
    )

    # Look-ahead avoidance: signal at t is only tradable at t+1.
    weight_used = weight.shift(1).fillna(0.0)

    # Risk: drawdown guard flattens exposure after a peak-to-trough breach.
    nav = 1.0
    peak = 1.0
    guarded = []
    gross_ret = weight_used * df["ret"]
    for w, r in zip(weight_used, gross_ret):
        if cfg.dd_guard > 0 and nav / peak - 1.0 <= -cfg.dd_guard:
            w = 0.0
            r = 0.0
        guarded.append(w)
        nav *= (1.0 + r)
        peak = max(peak, nav)
    weight_used = pd.Series(guarded, index=df.index)

    df["weight"] = weight_used
    df["turnover"] = df["weight"].diff().abs().fillna(df["weight"].abs())
    cost_rate = (cfg.fee_bps + cfg.slip_bps) / 1e4
    df["cost"] = df["turnover"] * cost_rate
    df["ret_gross"] = df["weight"] * df["ret"]
    df["ret_net"] = df["ret_gross"] - df["cost"]
    df["nav"] = (1.0 + df["ret_net"]).cumprod()
    df["drawdown"] = df["nav"] / df["nav"].cummax() - 1.0

    metrics = compute_metrics(df, cfg.annualization)
    metrics["execution"] = "t+1 close"
    metrics["signal"] = "builtin_ma" if cfg.demo else cfg.signal
    metrics["sizing"] = cfg.sizing
    metrics["cost_bps"] = cfg.fee_bps + cfg.slip_bps

    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    curve = df.reset_index()[["date", "nav", "drawdown", "weight", "ret_net"]]
    curve.to_csv(out_dir / "equity_curve.csv", index=False, encoding="utf-8-sig")
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics


def compute_metrics(df: "pd.DataFrame", annualization: float) -> dict:
    ret = df["ret_net"].fillna(0.0)
    n = len(ret)
    final_nav = float(df["nav"].iloc[-1]) if n else 1.0
    cagr = final_nav ** (annualization / n) - 1.0 if n > 0 and final_nav > 0 else float("nan")
    vol = float(ret.std(ddof=1) * math.sqrt(annualization)) if n > 1 else float("nan")
    sharpe = cagr / vol if vol and not math.isnan(vol) and vol != 0 else float("nan")
    max_dd = float(df["drawdown"].min()) if n else float("nan")
    avg_turnover = float(df["turnover"].mean()) if n else float("nan")
    return {
        "periods": int(n),
        "final_nav": round(final_nav, 4),
        "CAGR": round(cagr, 4) if not math.isnan(cagr) else None,
        "annual_vol": round(vol, 4) if not math.isnan(vol) else None,
        "Sharpe": round(sharpe, 4) if not math.isnan(sharpe) else None,
        "max_drawdown": round(max_dd, 4) if not math.isnan(max_dd) else None,
        "avg_turnover": round(avg_turnover, 4) if not math.isnan(avg_turnover) else None,
        "short_sample_warning": n < 60,
        "note": "research backtest only; illustrative history, not a prediction or advice",
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prices", help="price CSV (date, close[, open])")
    p.add_argument("--signal", default="builtin_ma", help="'builtin_ma' or a signal CSV (date, value)")
    p.add_argument("--demo", action="store_true", help="run on synthetic prices + built-in signal")
    p.add_argument("--sizing", choices=["vol_target", "fixed_fraction"], default="vol_target")
    p.add_argument("--target-vol", dest="target_vol", type=float, default=0.15)
    p.add_argument("--fixed-fraction", dest="fixed_fraction", type=float, default=1.0)
    p.add_argument("--vol-window", dest="vol_window", type=int, default=20)
    p.add_argument("--max-leverage", dest="max_leverage", type=float, default=1.0)
    p.add_argument("--max-weight", dest="max_weight", type=float, default=1.0)
    p.add_argument("--stop-pct", dest="stop_pct", type=float, default=0.0, help="reserved; see strategy-contract.md")
    p.add_argument("--dd-guard", dest="dd_guard", type=float, default=0.25, help="flatten if portfolio DD exceeds this")
    p.add_argument("--zscore", action="store_true", help="z-score the signal before thresholding")
    p.add_argument("--z-window", dest="z_window", type=int, default=60)
    p.add_argument("--enter", type=float, default=0.0, help="entry threshold on (z-)signal")
    p.add_argument("--exit", type=float, default=0.0, help="exit threshold (hysteresis)")
    p.add_argument("--long-only", dest="long_only", action="store_true")
    p.add_argument("--fee-bps", dest="fee_bps", type=float, default=2.0)
    p.add_argument("--slip-bps", dest="slip_bps", type=float, default=1.0)
    p.add_argument("--annualization", type=float, default=252.0)
    p.add_argument("--out-dir", dest="out_dir", default="backtest_out")
    return p


def main(argv: list[str] | None = None) -> int:
    cfg = build_parser().parse_args(argv)
    if not cfg.demo and not cfg.prices:
        sys.stderr.write("error: pass --prices PATH, or --demo for a self-contained run\n")
        return 2
    metrics = run(cfg)
    print(json.dumps({"ok": True, "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
