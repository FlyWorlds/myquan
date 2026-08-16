#!/usr/bin/env python3
"""Alpha expression formula contract — field names, function signatures, and LLM prompts.

This module is the single source of truth for what fields and functions are
available in alpha expressions. Both the generation and validation scripts
import from here.

Usage::

    from formulas import HELPER_DOCS, ALLOWED_FIELDS, ALLOWED_FUNCTIONS, build_generation_prompt
"""

from __future__ import annotations

from pathlib import Path

# ─── Load HELPER_DOCS from references/alpha_ops.md ───────────────────────────
_REF_DIR = Path(__file__).resolve().parent.parent / "references"
_ALPHA_OPS_MD = _REF_DIR / "alpha_ops.md"

try:
    HELPER_DOCS: str = _ALPHA_OPS_MD.read_text(encoding="utf-8")
except FileNotFoundError:
    HELPER_DOCS = """\
AVAILABLE FIELD VARIABLES (each is a date × symbol DataFrame):
  open, high, low, close, volume, amount
  (use _ref("field_name") to access other fields by name)
  IMPORTANT: Only these 6 fields exist. Do NOT use vwap or any other field.

AVAILABLE FUNCTIONS:
  rank(x)               — cross-sectional percentile rank at each date (0–1)
  zscore(x)             — cross-sectional z-score at each date
  ts_rank(x, n)         — time-series percentile rank over n periods
  ts_zscore(x, n)       — rolling z-score over n periods
  delay(x, n)           — lag x by n periods
  delta(x, n)           — x - delay(x, n)
  returns(x, n=1)       — pct_change over n periods (default x=close)
  adv(n)                — rolling mean of volume over n periods
  ts_mean(x, n)         — rolling mean
  ts_std(x, n)          — rolling standard deviation
  ts_max(x, n)          — rolling maximum
  ts_min(x, n)          — rolling minimum
  ts_sum(x, n)          — rolling sum
  ts_argmax(x, n)       — periods since rolling maximum within the last n bars
  ts_argmin(x, n)       — periods since rolling minimum within the last n bars
  correlation(x, y, n)  — rolling Pearson correlation per symbol
  covariance(x, y, n)   — rolling covariance per symbol
  scale(x, a=1)         — cross-sectional rescaling so |sum| == a
  decay_linear(x, n)    — linearly-decayed weighted moving average
  sign(x), log(x), abs(x), power(x, n), signed_power(x, n)
  min(x, y), max(x, y), clip(x, lower, upper)
  Standard arithmetic:  +, -, *, /  between DataFrames and scalars
"""

# ─── Allowed identifiers (single source of truth) ────────────────────────────

ALLOWED_FIELDS = frozenset({"open", "high", "low", "close", "volume", "amount"})
"""The 6 OHLCV field variables available in every alpha expression."""

ALLOWED_FUNCTIONS = frozenset({
    "rank",
    "zscore",
    "ts_rank",
    "ts_zscore",
    "delay",
    "delta",
    "returns",
    "adv",
    "ts_mean",
    "ts_std",
    "ts_max",
    "ts_min",
    "ts_sum",
    "ts_argmax",
    "ts_argmin",
    "correlation",
    "covariance",
    "scale",
    "decay_linear",
    "sign",
    "log",
    "abs",
    "power",
    "signed_power",
    "min",
    "max",
    "clip",
})
"""The 27 helper functions available in every alpha expression."""

ALLOWED_IDENTIFIERS = ALLOWED_FIELDS | ALLOWED_FUNCTIONS | {"_ref"}
"""All valid identifiers: 6 fields + 27 functions + ``_ref`` accessor."""


# ─── Anti-bias & stability rules (injected into every generation prompt) ────

ANTI_BIAS_RULES = """
CRITICAL — LOOK-AHEAD BIAS PREVENTION:
- delay(x, n), delta(x, n), and returns(x, n) MUST use n ≥ 1.
  n ≤ 0 peeks into the future → REJECTED.
- All rolling functions (ts_mean, ts_std, ts_rank, etc.) inherently
  use only past data when n ≥ 1 — this is correct.
- Do NOT reference fields at relative offsets like close[-1] or close[+1].
  Use delay(close, 1) instead of close[-1].

CRITICAL — NUMERICAL STABILITY:
- NEVER divide by something that could be zero. Use max(denom, 1e-8) or
  clip(denom, 1e-8, 1e8) as a guard.
- NEVER take log(x) without ensuring x > 0. Use log(max(x, 1e-8)) or
  log(clip(x, 1e-8, 1e8)).
- Avoid expressions that can overflow (e.g., power(x, 20) on large x).
  Prefer signed_power() for large exponents.
- Rank-based and zscore-based expressions are naturally stable. Prefer them.
"""


# ─── Prompt builders ─────────────────────────────────────────────────────────

def build_generation_prompt(text: str, n: int) -> str:
    """Build the LLM prompt for generating N alpha expressions from text.

    Args:
        text: Document text to derive alphas from.
        n: Number of alphas to generate.

    Returns:
        Full prompt string ready for the LLM.
    """
    return f"""You are a quantitative researcher. Based on the following document, generate exactly {n} novel alpha factor expressions for stock selection.

DOCUMENT:
{text}

REQUIREMENTS:
- Each alpha must be inspired by ideas, metrics, or insights from the document.
- Each expression must be directly computable using only the fields and functions listed below.
- Use ONLY the 6 field names (open, high, low, close, volume, amount) and helper functions listed below.
- Do NOT use vwap, adjfactor, or any other field.
- Do not use pseudo-code, unsupported functions, unsupported fields, or invented operators.
- Prefer concise expressions that can be evaluated on standard OHLCV-style market data.
- For each alpha provide: name, expression, description, and the rationale linking it to the document.
- Output ONLY a valid JSON array of objects with keys: "name", "expression", "description", "rationale".
{ANTI_BIAS_RULES}

SUPPORTED FIELD / FUNCTION CONTRACT:
{HELPER_DOCS}

OUTPUT (JSON array of {n} alphas):"""


def build_correction_prompt(
    failed_alphas: list[dict[str, Any]],
    original_text: str = "",
) -> str:
    """Build a prompt for the LLM to correct failed alpha expressions.

    Each failed alpha dict should have at least ``name``, ``expression``,
    ``error_type``, and ``correction_hint`` (from the validator output).

    Args:
        failed_alphas: List of failed alpha dicts with error diagnostics.
        original_text: Optional original document text for context.

    Returns:
        Correction prompt string ready for the LLM.
    """
    if not failed_alphas:
        return "No failed alphas to correct."

    lines: list[str] = []
    lines.append(
        "You are a quantitative researcher. The following alpha factor "
        "expressions FAILED validation. For EACH failed alpha, output a "
        "CORRECTED version that fixes the specific error while preserving "
        "the original idea."
    )
    lines.append("")

    if original_text:
        lines.append("ORIGINAL DOCUMENT CONTEXT:")
        lines.append(original_text[:2000])
        lines.append("")

    lines.append("FAILED ALPHAS (fix each one):")
    lines.append("")

    for i, alpha in enumerate(failed_alphas, 1):
        lines.append(f"--- Failed Alpha {i}: {alpha.get('name', 'unnamed')} ---")
        lines.append(f"Expression: {alpha.get('expression', 'N/A')}")
        lines.append(f"Error type: {alpha.get('error_type', 'unknown')}")
        lines.append(f"Correction hint: {alpha.get('correction_hint', 'No hint available.')}")
        if alpha.get("error"):
            lines.append(f"Raw error: {alpha['error']}")
        lines.append("")

    lines.append("CORRECTION RULES:")
    lines.append(ANTI_BIAS_RULES.strip())
    lines.append("")
    lines.append(
        "OUTPUT: A valid JSON array of CORRECTED alpha objects with keys: "
        "name, expression, description, rationale. "
        "Keep the original name so we can track corrections. "
        "Output ONLY the JSON array."
    )

    return "\n".join(lines)
