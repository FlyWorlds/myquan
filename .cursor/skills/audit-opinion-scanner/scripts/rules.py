"""Classification rules — map audit opinion fields to risk levels.

This is the core business logic of the scanner. The mapping table is based on
China's auditing standards (CAS 1501-1503). Unknown opinion values are flagged
as "needs_review" rather than silently classified.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------

RISK_LOW = 0        # 低风险：标准无保留意见
RISK_MEDIUM = 1     # 中风险：带强调事项段的无保留意见
RISK_HIGH = 2       # 高风险：保留意见
RISK_CRITICAL = 3   # 严重风险：否定意见 / 无法表示意见
RISK_UNKNOWN = -1   # 未知：需人工确认

RISK_LABELS: dict[int, str] = {
    RISK_LOW: "低风险",
    RISK_MEDIUM: "中风险",
    RISK_HIGH: "高风险",
    RISK_CRITICAL: "严重风险",
    RISK_UNKNOWN: "需人工确认",
}

# ---------------------------------------------------------------------------
# Opinion value → risk level mapping
#
# These keys are the literal string values returned by the get_audit_opinion
# API's `opinion` column. The known values come from the API documentation
# examples; the speculative values (commented) represent the standard audit
# opinion taxonomy and are enabled after real-data verification.
# ---------------------------------------------------------------------------

OPINION_RISK_MAP: dict[str, int] = {
    # --- Confirmed from API docs ---
    "unqualified_opinion":           RISK_LOW,
    "no_audit_performed":            RISK_UNKNOWN,  # quarterly reports — not audited

    # --- Standard audit opinion taxonomy ---
    "unqualified_opinion_with_emphasis": RISK_MEDIUM,   # 带强调事项段
    "qualified_opinion":                RISK_HIGH,      # 保留意见
    "adverse_opinion":                  RISK_CRITICAL,  # 否定意见
    "disclaimer_of_opinion":            RISK_CRITICAL,  # 无法表示意见
    "modified_unqualified":             RISK_MEDIUM,    # 带说明段

    # --- Verified from real data (2024q4 CSI1000) ---
    # 带强调事项段的无保留意见（两种英文变体）
    "unqualified_opinion_with_emphasis-of-matter_paragraph": RISK_MEDIUM,
    "unqualified_opinion_with_material_uncertainty":        RISK_MEDIUM,
    # 保留意见_带强调事项段
    "qualified_opinion_with_basis_for_qualification_paragraph": RISK_HIGH,
}

# ---------------------------------------------------------------------------
# audit_type values to include in the scan
# ---------------------------------------------------------------------------

# Only financial statement audit opinions matter for stock screening.
# Internal control (internal_control) audits are excluded by default
# but can be included with --include-internal-control.
DEFAULT_AUDIT_TYPES = {"financial_statements"}

# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


def classify_opinion(opinion: str) -> int:
    """Map a single opinion string to a risk level.

    Args:
        opinion: Raw opinion string from the API.

    Returns:
        Risk level integer (0-3, or -1 for unknown).
    """
    if not isinstance(opinion, str) or not opinion.strip():
        return RISK_UNKNOWN
    return OPINION_RISK_MAP.get(opinion.strip().lower(), RISK_UNKNOWN)


def classify_audit_type(audit_type: str) -> bool:
    """Check if an audit_type should be included in the risk scan.

    Args:
        audit_type: Raw audit_type string from the API.

    Returns:
        True if this audit type is part of the default scan scope.
    """
    if not isinstance(audit_type, str):
        return False
    return audit_type.strip().lower() in DEFAULT_AUDIT_TYPES


def get_risk_label(risk_level: int) -> str:
    """Human-readable risk label for a risk level integer."""
    return RISK_LABELS.get(risk_level, "未知")


def get_high_risk_symbols(classified_df: "pd.DataFrame") -> "pd.DataFrame":
    """Filter the classified DataFrame to only high-risk (>=RISK_HIGH) stocks.

    Args:
        classified_df: DataFrame with a 'risk_level' integer column.

    Returns:
        Subset of rows where risk_level >= RISK_HIGH.
    """
    import pandas as pd
    return classified_df[classified_df["risk_level"] >= RISK_HIGH]


def summarize(classified_df: "pd.DataFrame") -> dict:
    """Produce a summary dict of risk-level counts.

    Args:
        classified_df: DataFrame with a 'risk_level' integer column.

    Returns:
        Dict with keys: total, low, medium, high, critical, unknown, unknown_opinions.
    """
    import pandas as pd

    total = len(classified_df)
    counts = classified_df["risk_level"].value_counts().to_dict()

    unknown_opinions: list[str] = []
    if RISK_UNKNOWN in counts:
        unknown_mask = classified_df["risk_level"] == RISK_UNKNOWN
        unknown_opinions = (
            classified_df.loc[unknown_mask, "opinion"]
            .dropna()
            .unique()
            .tolist()
        )

    return {
        "total": total,
        "low": int(counts.get(RISK_LOW, 0)),
        "medium": int(counts.get(RISK_MEDIUM, 0)),
        "high": int(counts.get(RISK_HIGH, 0)),
        "critical": int(counts.get(RISK_CRITICAL, 0)),
        "unknown": int(counts.get(RISK_UNKNOWN, 0)),
        "unknown_opinions": unknown_opinions,
    }


def get_unknown_opinion_values(opinion_series: "pd.Series") -> list[str]:
    """Return opinion values not present in OPINION_RISK_MAP.

    Call this after a real-data run to discover new enumeration values.
    """
    known = set(OPINION_RISK_MAP.keys())
    seen = set(opinion_series.dropna().astype(str).str.lower().unique())
    return sorted(seen - known)


def suggest_mapping(unknown: str) -> str | None:
    """Suggest the closest known opinion value for an unknown one.

    Uses simple prefix/word-overlap heuristics — fast and interpretable.
    Returns the best-matching known key, or None if no plausible match.
    """
    if not unknown or not isinstance(unknown, str):
        return None
    u = unknown.strip().lower()
    if not u:
        return None
    known_keys = list(OPINION_RISK_MAP.keys())
    # 1. Exact prefix match (best)
    for k in known_keys:
        if u.startswith(k):
            return k
        if k.startswith(u):
            return k
    # 2. Token overlap: count shared tokens
    best, best_score = None, 0
    u_tokens = set(u.replace("-", "_").replace(" ", "_").split("_"))
    for k in known_keys:
        k_tokens = set(k.replace("-", "_").replace(" ", "_").split("_"))
        score = len(u_tokens & k_tokens)
        if score > best_score:
            best_score = score
            best = k
    if best_score >= 3:
        return best
    return None


def classify_opinion_with_suggestion(opinion: str) -> tuple[int, str | None]:
    """Like classify_opinion, but returns (level, suggested_known_key) for unknowns.

    When the opinion is unknown, the suggestion helps the user decide where
    to place it in OPINION_RISK_MAP.
    """
    level = classify_opinion(opinion)
    if level != RISK_UNKNOWN:
        return level, None
    suggestion = suggest_mapping(opinion)
    return level, suggestion
