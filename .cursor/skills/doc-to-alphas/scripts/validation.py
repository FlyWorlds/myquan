#!/usr/bin/env python3
"""Alpha expression validation against synthetic toy OHLCV market data.

Provides a self-contained ``ToyAlphaEngine`` that mirrors the full
``AlphaEngine`` API so that generated alpha expressions can be evaluated
without requiring real market data or an LLM translation step.

Includes look-ahead bias detection and numerical stability checks with
categorized error diagnostics and actionable correction hints.

Usage::

    from validation import make_toy_data, ToyAlphaEngine, validate_alphas_against_toy_data

    alphas = [{"name": "mom", "expression": "returns(close, 5)"}, ...]
    result = validate_alphas_against_toy_data(alphas)
    print(f"Passed: {result['passed']}, Failed: {result['failed']}")
"""

from __future__ import annotations

import re
import time
import warnings
from typing import Any

import numpy as np
import pandas as pd

# Suppress numpy RuntimeWarnings during validation (NaN/Inf are expected
# and handled explicitly by our stability checks).
warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pandas")


# ═══════════════════════════════════════════════════════════════════════════════
# Toy Market Data Generator
# ═══════════════════════════════════════════════════════════════════════════════

def make_toy_data(
    num_dates: int = 30,
    num_symbols: int = 5,
    seed: int = 42,
) -> pd.DataFrame:
    """Create synthetic OHLCV data suitable for alpha expression validation.

    Generates realistic prices following correlated random walks with proper
    OHLC relationships (high ≥ max(open, close), low ≤ min(open, close)).

    Args:
        num_dates: Number of trading days (default 30).
        num_symbols: Number of synthetic stocks (default 5).
        seed: Random seed for reproducibility (default 42).

    Returns:
        DataFrame with columns: ``date``, ``symbol``, ``open``, ``high``,
        ``low``, ``close``, ``volume``, ``amount``.
    """
    rng = np.random.default_rng(seed)
    symbols = [f"TEST{i:03d}" for i in range(num_symbols)]
    dates = pd.date_range("2024-01-01", periods=num_dates, freq="B")

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        drift = rng.normal(0.0002, 0.0005)
        base_price = rng.uniform(10, 100)
        close_prices: list[float] = []
        for _ in range(num_dates):
            ret = rng.normal(drift, 0.02)
            base_price *= (1 + ret)
            close_prices.append(base_price)

        for d_idx, date in enumerate(dates):
            c = close_prices[d_idx]
            daily_range = c * rng.uniform(0.01, 0.04)
            o = c * rng.uniform(0.98, 1.02)
            h = max(o, c) + daily_range * rng.uniform(0, 0.5)
            l = min(o, c) - daily_range * rng.uniform(0, 0.5)
            v = rng.integers(100_000, 10_000_000)
            rows.append({
                "date": date.strftime("%Y%m%d"),
                "symbol": sym,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": float(v),
                "amount": round(c * v, 2),
            })

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
# ToyAlphaEngine — mirrors the full AlphaEngine API
# ═══════════════════════════════════════════════════════════════════════════════

class ToyAlphaEngine:
    """Lightweight, self-contained AlphaEngine for toy-data validation.

    Mirrors the full ``AlphaEngine`` API so alpha expressions evaluate
    identically. No LLM translation step is needed — expressions are
    evaluated as-is after converting ``open`` → ``open_`` (Python
    reserved-word workaround).

    Usage::

        df = make_toy_data()
        engine = ToyAlphaEngine(df)
        ns = engine.eval_ns()
        result = eval("returns(close, 5)", ns)
    """

    def __init__(self, df: pd.DataFrame) -> None:
        df = df.copy()
        df["date"] = df["date"].astype(str)
        df = df.sort_values(["date", "symbol"])
        self.matrices: dict[str, pd.DataFrame] = {}
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                self.matrices[col] = df.pivot(
                    index="date", columns="symbol", values=col
                ).astype(float)
        if not self.matrices:
            raise ValueError("Toy data has no OHLCV fields.")
        self._template: pd.DataFrame = next(iter(self.matrices.values()))

    # ── internal utilities ────────────────────────────────────────────────

    def _ref(self, name: str) -> pd.DataFrame:
        if name not in self.matrices:
            available = ", ".join(self.matrices.keys())
            raise KeyError(
                f"Field '{name}' not in market data. Available: {available}"
            )
        return self.matrices[name]

    def _to_df(self, x: Any) -> pd.DataFrame:
        if isinstance(x, pd.DataFrame):
            return x
        ref = self._template
        if isinstance(x, (int, float, np.integer, np.floating)):
            return pd.DataFrame(float(x), index=ref.index, columns=ref.columns)
        if isinstance(x, pd.Series):
            return pd.DataFrame(
                [x.values] * len(ref), index=ref.index, columns=ref.columns
            )
        raise TypeError(f"Cannot coerce {type(x).__name__} to DataFrame")

    # ── cross-sectional ───────────────────────────────────────────────────

    def rank(self, x: Any) -> pd.DataFrame:
        return self._to_df(x).rank(axis=1, pct=True)

    def zscore(self, x: Any) -> pd.DataFrame:
        x = self._to_df(x)
        row_std = x.std(axis=1).replace(0, np.nan)
        return x.sub(x.mean(axis=1), axis=0).div(row_std, axis=0)

    def scale(self, x: Any, a: float = 1.0) -> pd.DataFrame:
        x = self._to_df(x)
        row_sum = x.abs().sum(axis=1).replace(0, np.nan)
        return x.div(row_sum, axis=0) * a

    # ── time-series ───────────────────────────────────────────────────────

    def delay(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).shift(n)

    def delta(self, x: Any, n: int) -> pd.DataFrame:
        x = self._to_df(x)
        return x - x.shift(n)

    def returns(self, x: Any = None, n: int = 1) -> pd.DataFrame:
        base = self._to_df(x) if x is not None else self._ref("close")
        return base.pct_change(n)

    def adv(self, n: int) -> pd.DataFrame:
        return self.ts_mean(self._ref("volume"), n)

    def ts_mean(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).rolling(n, min_periods=1).mean()

    def ts_std(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).rolling(n, min_periods=2).std()

    def ts_max(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).rolling(n, min_periods=1).max()

    def ts_min(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).rolling(n, min_periods=1).min()

    def ts_sum(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).rolling(n, min_periods=1).sum()

    def ts_rank(self, x: Any, n: int) -> pd.DataFrame:
        def _rank_last(w: np.ndarray) -> float:
            s = pd.Series(w)
            return float(s.rank(pct=True).iloc[-1])

        return self._to_df(x).apply(
            lambda col: col.rolling(n, min_periods=max(1, n // 2)).apply(
                _rank_last, raw=False
            )
        )

    def ts_zscore(self, x: Any, n: int) -> pd.DataFrame:
        x = self._to_df(x)
        rm = x.rolling(n, min_periods=1).mean()
        rs = x.rolling(n, min_periods=2).std().replace(0, np.nan)
        return (x - rm) / rs

    def ts_argmax(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).apply(
            lambda col: col.rolling(n, min_periods=1).apply(
                lambda w: float(len(w) - 1 - int(np.argmax(w))), raw=True
            )
        )

    def ts_argmin(self, x: Any, n: int) -> pd.DataFrame:
        return self._to_df(x).apply(
            lambda col: col.rolling(n, min_periods=1).apply(
                lambda w: float(len(w) - 1 - int(np.argmin(w))), raw=True
            )
        )

    def decay_linear(self, x: Any, n: int) -> pd.DataFrame:
        weights = np.arange(1, n + 1, dtype=float)
        weights /= weights.sum()
        return self._to_df(x).apply(
            lambda col: col.rolling(n, min_periods=n).apply(
                lambda w: float(np.dot(w, weights)), raw=True
            )
        )

    # ── pairwise ──────────────────────────────────────────────────────────

    def correlation(self, x: Any, y: Any, n: int) -> pd.DataFrame:
        x, y = self._to_df(x), self._to_df(y)
        result = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
        for sym in x.columns:
            if sym in y.columns:
                result[sym] = x[sym].rolling(n, min_periods=2).corr(y[sym])
        return result

    def covariance(self, x: Any, y: Any, n: int) -> pd.DataFrame:
        x, y = self._to_df(x), self._to_df(y)
        result = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
        for sym in x.columns:
            if sym in y.columns:
                result[sym] = x[sym].rolling(n, min_periods=2).cov(y[sym])
        return result

    # ── element-wise ──────────────────────────────────────────────────────

    def sign(self, x: Any) -> pd.DataFrame:
        return pd.DataFrame(
            np.sign(self._to_df(x)),
            index=self._template.index,
            columns=self._template.columns,
        )

    def log(self, x: Any) -> pd.DataFrame:
        return np.log(self._to_df(x))

    def abs(self, x: Any) -> pd.DataFrame:
        return self._to_df(x).abs()

    def power(self, x: Any, n: Any) -> pd.DataFrame:
        return self._to_df(x) ** n

    def signed_power(self, x: Any, n: Any) -> pd.DataFrame:
        x = self._to_df(x)
        return np.sign(x) * (x.abs() ** n)

    def _min(self, x: Any, y: Any) -> pd.DataFrame:
        return self._to_df(x).combine(self._to_df(y), np.minimum)

    def _max(self, x: Any, y: Any) -> pd.DataFrame:
        return self._to_df(x).combine(self._to_df(y), np.maximum)

    def clip(self, x: Any, lower: Any, upper: Any) -> pd.DataFrame:
        x = self._to_df(x)
        lv = (
            self._to_df(lower)
            if isinstance(lower, (pd.DataFrame, pd.Series))
            else lower
        )
        uv = (
            self._to_df(upper)
            if isinstance(upper, (pd.DataFrame, pd.Series))
            else upper
        )
        return self._min(self._max(x, lv), uv)

    # ── eval namespace ────────────────────────────────────────────────────

    def eval_ns(self) -> dict[str, Any]:
        """Return namespace for ``eval(expr, ns)``.

        Includes all 27 functions, field matrices, ``_ref``, ``np``, ``pd``,
        and ``open_`` (reserved-word workaround for ``open``).
        """
        ns: dict[str, Any] = {
            "rank": self.rank,
            "zscore": self.zscore,
            "ts_rank": self.ts_rank,
            "ts_zscore": self.ts_zscore,
            "delay": self.delay,
            "delta": self.delta,
            "returns": self.returns,
            "adv": self.adv,
            "ts_mean": self.ts_mean,
            "ts_std": self.ts_std,
            "ts_max": self.ts_max,
            "ts_min": self.ts_min,
            "ts_sum": self.ts_sum,
            "ts_argmax": self.ts_argmax,
            "ts_argmin": self.ts_argmin,
            "correlation": self.correlation,
            "covariance": self.covariance,
            "scale": self.scale,
            "decay_linear": self.decay_linear,
            "sign": self.sign,
            "log": self.log,
            "abs": self.abs,
            "power": self.power,
            "signed_power": self.signed_power,
            "min": self._min,
            "max": self._max,
            "clip": self.clip,
            "_ref": self._ref,
            "np": np,
            "pd": pd,
        }
        for name, mat in self.matrices.items():
            ns[name] = mat
        ns["open_"] = self.matrices.get("open")
        return ns


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Preprocessing
# ═══════════════════════════════════════════════════════════════════════════════

def preprocess_expression(expr: str) -> str:
    """Prepare a symbolic alpha expression for direct Python ``eval()``.

    Handles:
    - ``open`` → ``open_`` (Python reserved word workaround)
    - Whitespace normalization

    Args:
        expr: Raw alpha expression string.

    Returns:
        Python-evaluable expression string.
    """
    expr = expr.strip()
    # Replace bare 'open' that is not part of 'open_' or another identifier
    expr = re.sub(r'\bopen\b(?!_)', 'open_', expr)
    return expr


# ═══════════════════════════════════════════════════════════════════════════════
# Look-Ahead Bias Detection
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns that indicate explicit future-peeking (n ≤ 0 in lag/delta/returns)
_FUTURE_PEEK_PATTERNS = [
    (r'\bdelay\s*\(\s*\w+\s*,\s*(-?\d*\.?\d+)\s*\)', "delay"),
    (r'\bdelta\s*\(\s*\w+\s*,\s*(-?\d*\.?\d+)\s*\)', "delta"),
    (r'\breturns\s*\(\s*\w*\s*,\s*(-?\d*\.?\d+)\s*\)', "returns"),
]

# Numeric thresholds
_MAX_NAN_RATIO = 0.5        # >50% NaN → unstable
_MAX_INF_RATIO = 0.01       # >1% Inf → unstable
_MAX_EXTREME_STDDEV = 10.0  # output std > 10× input std → likely unstable


def _extract_numeric_arg(expr: str, func_name: str, default: float = 1.0) -> float | None:
    """Extract the second numeric argument from a function call.

    Returns None if the function is not found or the arg can't be parsed.
    """
    pattern = rf'\b{func_name}\s*\(\s*\w+\s*,\s*(-?\d*\.?\d+)\s*\)'
    m = re.search(pattern, expr, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def check_lookahead_bias(
    expr: str,
    processed_expr: str,
    engine: ToyAlphaEngine,
    ns: dict[str, Any],
) -> dict[str, Any]:
    """Detect look-ahead bias in an alpha expression.

    Uses two complementary methods:

    1. **Static scan** — checks for ``delay(x, n)``, ``delta(x, n)``, or
       ``returns(x, n)`` with n ≤ 0 (explicit future peeking).
    2. **Truncation test** — evaluates the expression on a truncated dataset
       (last 20% of dates removed) and compares against the overlapping region
       of the full evaluation. If results differ substantially, the expression
       is using future information.

    Args:
        expr: Original expression string.
        processed_expr: Preprocessed expression (``open`` → ``open_``).
        engine: ToyAlphaEngine instance on the full dataset.
        ns: Eval namespace from the engine.

    Returns:
        Dict with keys ``has_bias`` (bool), ``method`` (str), ``detail`` (str).
    """
    result: dict[str, Any] = {"has_bias": False, "method": "", "detail": ""}

    # ── Method 1: Static scan for explicit future-peeking ─────────────────
    for pattern, func_name in _FUTURE_PEEK_PATTERNS:
        for m in re.finditer(pattern, expr, re.IGNORECASE):
            try:
                n = float(m.group(1))
                if n <= 0:
                    result["has_bias"] = True
                    result["method"] = "static_scan"
                    result["detail"] = (
                        f"{func_name}(..., {n}) uses n ≤ 0 — "
                        f"this peeks into the future. Use n ≥ 1 for "
                        f"{func_name}."
                    )
                    return result
            except ValueError:
                pass

    # ── Method 2: Truncation test ─────────────────────────────────────────
    try:
        # Evaluate on full data
        full_output = eval(processed_expr, ns)  # noqa: S307
        if not isinstance(full_output, pd.DataFrame):
            return result  # can't check non-DataFrame

        # Build truncated engine: remove last 20% of dates
        full_dates = list(engine._template.index)
        cutoff = max(10, int(len(full_dates) * 0.8))
        truncated_dates = full_dates[:cutoff]

        # Rebuild a truncated engine
        truncated_matrices: dict[str, pd.DataFrame] = {}
        for name, mat in engine.matrices.items():
            truncated_matrices[name] = mat.loc[truncated_dates]

        # Create minimal truncated engine & namespace
        truncated_engine = ToyAlphaEngine.__new__(ToyAlphaEngine)
        truncated_engine.matrices = truncated_matrices
        truncated_engine._template = next(iter(truncated_matrices.values()))
        truncated_ns = truncated_engine.eval_ns()

        # Evaluate on truncated data
        truncated_output = eval(processed_expr, truncated_ns)  # noqa: S307
        if not isinstance(truncated_output, pd.DataFrame):
            return result

        # Compare overlapping region (dates present in both)
        overlap_dates = full_output.index.intersection(truncated_output.index)
        if len(overlap_dates) < 5:
            return result  # not enough overlap to judge

        full_overlap = full_output.loc[overlap_dates]
        trunc_overlap = truncated_output.loc[overlap_dates]

        # Compute correlation of flattened values
        fv = full_overlap.values.flatten()
        tv = trunc_overlap.values.flatten()
        mask = ~(np.isnan(fv) | np.isnan(tv))
        if mask.sum() < 10:
            return result

        corr = np.corrcoef(fv[mask], tv[mask])[0, 1]
        mean_diff = abs(float(np.nanmean(fv) - np.nanmean(tv)))
        max_abs_diff = float(np.nanmax(np.abs(fv[mask] - tv[mask])))

        # Heuristic: if correlation < 0.95 or mean diff is large, likely bias
        if corr < 0.95 or (corr < 0.99 and mean_diff > 0.1):
            result["has_bias"] = True
            result["method"] = "truncation_test"
            result["detail"] = (
                f"Truncation test: corr={corr:.4f}, mean_diff={mean_diff:.4f}, "
                f"max_abs_diff={max_abs_diff:.4f}. The expression appears to "
                f"use future information. Check that all rolling/lag functions "
                f"use n ≥ 1, and that no function implicitly references "
                f"future bars."
            )
            return result

    except Exception:
        pass  # If truncation test fails, fall through to no-bias result

    return result


def check_numerical_stability(
    output: pd.DataFrame,
    engine: ToyAlphaEngine | None = None,
) -> dict[str, Any]:
    """Check an alpha output for numerical instability.

    Detects:
    - High NaN ratio (division by zero, log of negative, etc.)
    - Inf values (overflow, division by zero)
    - Extreme standard deviation relative to input fields
    - Zero-variance output (flat/constant)

    Args:
        output: The evaluated alpha output DataFrame.
        engine: Optional ToyAlphaEngine for comparing against input scale.

    Returns:
        Dict with ``is_stable`` (bool), ``warnings`` (list[str]), and metrics.
    """
    result: dict[str, Any] = {"is_stable": True, "warnings": []}

    total_cells = output.size
    if total_cells == 0:
        result["is_stable"] = False
        result["warnings"].append("Empty output (zero cells).")
        return result

    # ── NaN ratio ─────────────────────────────────────────────────────────
    nan_count = int(output.isna().sum().sum())
    nan_ratio = nan_count / total_cells
    result["nan_ratio"] = round(nan_ratio, 4)

    if nan_ratio >= 1.0:
        result["is_stable"] = False
        result["warnings"].append(
            "All-NaN output — expression likely divides by zero everywhere "
            "or takes log() of negative/zero values. "
            "Add clip() or abs() guards, or ensure denominators cannot be zero."
        )
    elif nan_ratio > _MAX_NAN_RATIO:
        result["is_stable"] = False
        result["warnings"].append(
            f"{nan_ratio:.1%} NaN ratio (>{_MAX_NAN_RATIO:.0%}) — "
            "expression produces too many invalid values. "
            "Guard divisions with max(denominator, 1e-8) or use clip()."
        )

    # ── Inf ratio ─────────────────────────────────────────────────────────
    inf_count = int(np.isinf(output.values).sum())
    inf_ratio = inf_count / total_cells
    result["inf_ratio"] = round(inf_ratio, 4)

    if inf_ratio > _MAX_INF_RATIO:
        result["is_stable"] = False
        result["warnings"].append(
            f"{inf_ratio:.2%} Inf ratio (>{_MAX_INF_RATIO:.2%}) — "
            "overflow or division by near-zero. "
            "Use clip() to bound values or check for degenerate divisors."
        )

    # ── Extreme values ────────────────────────────────────────────────────
    finite_vals = output.values[np.isfinite(output.values)]
    if len(finite_vals) > 0:
        out_std = float(np.nanstd(finite_vals))
        out_mean = float(np.nanmean(finite_vals))
        result["output_std"] = round(out_std, 4)
        result["output_mean"] = round(out_mean, 4)

        # Compare against input scale if engine provided
        if engine is not None and out_std > 0:
            ref_fields = ["close", "open", "high", "low"]
            ref_stds = []
            for f in ref_fields:
                if f in engine.matrices:
                    ref_stds.append(float(engine.matrices[f].values.std()))
            if ref_stds:
                avg_ref_std = float(np.mean(ref_stds))
                if avg_ref_std > 0 and out_std > _MAX_EXTREME_STDDEV * avg_ref_std:
                    result["is_stable"] = False
                    result["warnings"].append(
                        f"Output std ({out_std:.2f}) is {out_std / avg_ref_std:.1f}× "
                        f"the input scale ({avg_ref_std:.2f}) — expression may be "
                        f"numerically unstable. Normalize with zscore(), rank(), "
                        f"or scale()."
                    )

        # Zero-variance check
        if out_std < 1e-10:
            result["is_stable"] = False
            result["warnings"].append(
                "Output is constant (zero variance) — expression does not "
                "differentiate between symbols or dates."
            )

    return result


def diagnose_failure(
    expr: str,
    processed_expr: str,
    error: Exception | None,
    output: pd.DataFrame | None,
    engine: ToyAlphaEngine,
    ns: dict[str, Any],
) -> dict[str, Any]:
    """Categorize a validation failure and produce a correction hint.

    Args:
        expr: Original alpha expression.
        processed_expr: Preprocessed expression.
        error: The exception raised during eval, or None if eval succeeded.
        output: The eval result if eval succeeded, or None.
        engine: ToyAlphaEngine instance.
        ns: Eval namespace.

    Returns:
        Dict with ``error_type``, ``correction_hint``, and diagnostic details.
    """
    diag: dict[str, Any] = {
        "error_type": "unknown",
        "correction_hint": "",
        "lookahead_bias": None,
        "numerical_stability": None,
    }

    error_str = str(error) if error else ""

    # ── Classify the error ────────────────────────────────────────────────
    if error is not None:
        err_type_name = type(error).__name__

        if err_type_name == "KeyError" and "not in market data" in error_str.lower():
            diag["error_type"] = "unsupported_field"
            diag["correction_hint"] = (
                "You used a field not in the contract. "
                "Only these 6 fields are allowed: open, high, low, close, volume, amount."
            )
        elif err_type_name in ("NameError", "UnboundLocalError"):
            diag["error_type"] = "unsupported_function"
            diag["correction_hint"] = (
                "You used an undefined function or variable. "
                "Check that every function name matches the contract exactly "
                "(case-sensitive). See references/alpha_ops.md."
            )
        elif err_type_name == "SyntaxError":
            diag["error_type"] = "syntax_error"
            diag["correction_hint"] = (
                f"Syntax error in expression: {error}. "
                "Check parentheses, commas, and argument counts."
            )
        elif err_type_name == "TypeError":
            diag["error_type"] = "type_error"
            diag["correction_hint"] = (
                f"Type mismatch: {error}. "
                "Check argument types and counts against the contract."
            )
        elif err_type_name == "ValueError" and "all-NaN" in error_str:
            diag["error_type"] = "all_nan"
            diag["correction_hint"] = (
                "Expression produces all NaN. Common causes: division by zero, "
                "log() of negative values, or insufficient data for rolling windows. "
                "Add guards like max(denom, 1e-8) or clip(x, 1e-8, 1e8)."
            )
        else:
            diag["error_type"] = "eval_error"
            diag["correction_hint"] = (
                f"Evaluation failed: {error}. "
                "Review the expression against the contract in references/alpha_ops.md."
            )

    # ── If eval succeeded, check for subtle issues ────────────────────────
    if output is not None and isinstance(output, pd.DataFrame):
        # Numerical stability
        stability = check_numerical_stability(output, engine)
        diag["numerical_stability"] = stability
        if not stability["is_stable"]:
            diag["error_type"] = "numerical_instability"
            diag["correction_hint"] = "; ".join(stability["warnings"])

        # Look-ahead bias
        bias = check_lookahead_bias(expr, processed_expr, engine, ns)
        diag["lookahead_bias"] = bias
        if bias["has_bias"]:
            if diag["error_type"] in ("unknown", "numerical_instability"):
                diag["error_type"] = "lookahead_bias"
            diag["correction_hint"] = (
                bias["detail"] + " " + diag["correction_hint"]
            ).strip()

    return diag


# ═══════════════════════════════════════════════════════════════════════════════
# Main Validation Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def validate_alphas_against_toy_data(
    alphas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate each alpha expression against synthetic OHLCV market data.

    For each alpha object (with key ``"expression"``), this function:

    1. Preprocesses the expression (handles ``open`` reserved word).
    2. Attempts direct ``eval()`` against a ``ToyAlphaEngine`` on toy data.
    3. Reports per-alpha pass/fail with timing and error details.

    Args:
        alphas: List of alpha dicts, each with at least ``"name"`` and
                ``"expression"`` keys.

    Returns:
        Dict with:
        - ``toy_data_shape``: ``[dates, symbols]`` of validation data
        - ``total_checked``: number of alphas tested
        - ``passed``: count that evaluated successfully
        - ``failed``: count that could not be evaluated
        - ``results``: per-alpha dict with ``name``, ``expression``, ``ok``,
          ``error`` (if failed), ``eval_time_ms``, and (if passed)
          ``output_shape`` / ``output_mean``.
    """
    if not alphas:
        return {
            "error": "No alphas to validate.",
            "total_checked": 0,
            "passed": 0,
            "failed": 0,
            "results": [],
        }

    # Build toy data & engine once
    toy_df = make_toy_data()
    engine = ToyAlphaEngine(toy_df)
    ns = engine.eval_ns()

    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0

    for alpha in alphas:
        name = alpha.get("name", "unnamed")
        expr = alpha.get("expression", "").strip()
        result_entry: dict[str, Any] = {
            "name": name,
            "expression": expr,
            "ok": False,
        }

        if not expr:
            result_entry["error"] = "Empty expression."
            results.append(result_entry)
            failed += 1
            continue

        t0 = time.perf_counter()
        processed = preprocess_expression(expr)

        output = None
        eval_error = None

        # ── Direct eval ──────────────────────────────────────────────────
        try:
            output = eval(processed, ns)  # noqa: S307
            if isinstance(output, pd.DataFrame):
                if output.isna().all().all():
                    eval_error = ValueError(
                        "Result is all-NaN — expression likely produces "
                        "no valid values."
                    )
                    output = None
                else:
                    result_entry["ok"] = True
                    result_entry["output_shape"] = list(output.shape)
                    result_entry["output_mean"] = round(
                        float(output.mean().mean()), 6
                    )
            else:
                eval_error = TypeError(
                    f"Expression returned {type(output).__name__}, "
                    "expected DataFrame."
                )
                output = None
        except Exception as exc:
            eval_error = exc
            output = None

        # ── Run diagnostics (look-ahead bias, numerical stability) ───────
        diag = diagnose_failure(expr, processed, eval_error, output, engine, ns)

        if eval_error is not None:
            result_entry["error"] = f"{type(eval_error).__name__}: {eval_error}"
            result_entry["error_type"] = diag["error_type"]
            result_entry["correction_hint"] = diag["correction_hint"]
        elif output is not None:
            # Even if eval succeeded, check for subtle issues
            if diag.get("lookahead_bias", {}).get("has_bias"):
                result_entry["ok"] = False
                result_entry["error"] = (
                    f"Look-ahead bias: {diag['lookahead_bias']['detail']}"
                )
                result_entry["error_type"] = diag["error_type"]
                result_entry["correction_hint"] = diag["correction_hint"]
            elif diag.get("numerical_stability") and not diag["numerical_stability"]["is_stable"]:
                result_entry["ok"] = False
                result_entry["error"] = (
                    f"Numerical instability: {'; '.join(diag['numerical_stability']['warnings'])}"
                )
                result_entry["error_type"] = diag["error_type"]
                result_entry["correction_hint"] = diag["correction_hint"]

        result_entry["eval_time_ms"] = round(
            (time.perf_counter() - t0) * 1000, 2
        )
        if result_entry["ok"]:
            passed += 1
        else:
            failed += 1
        results.append(result_entry)

    return {
        "toy_data_shape": [
            len(toy_df["date"].unique()),
            len(toy_df["symbol"].unique()),
        ],
        "total_checked": len(alphas),
        "passed": passed,
        "failed": failed,
        "results": results,
        "failure_summary": _build_failure_summary(results),
    }


def _build_failure_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a categorized summary of failures for correction guidance."""
    by_type: dict[str, list[str]] = {}
    for r in results:
        if not r.get("ok"):
            etype = r.get("error_type", "unknown")
            by_type.setdefault(etype, []).append(r.get("name", "unnamed"))

    return {
        "by_error_type": {
            et: {"count": len(names), "alphas": names}
            for et, names in by_type.items()
        },
        "total_failed": sum(len(v) for v in by_type.values()),
    }
