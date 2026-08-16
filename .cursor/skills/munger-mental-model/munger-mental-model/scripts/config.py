"""
Configuration module for Munger mental model analysis tool.

Provides constants, environment-based thresholds, and credential management.
Enforces Python 3.10+ with proper type hints.
"""

from __future__ import annotations

import os


# Global constants (immutable)
DATA_VERSION: str = "real-v1"
DIM_KEYS: tuple = ("fin", "comp", "incentive", "psych", "neg")
VERDICTS: frozenset = frozenset({"pass", "fail", "veto", "insufficient_data"})

# Mapping of logical field names to get_fina_reports SDK field names
# ROE is computed from is_n_income_attr_p / avg(bs_total_hldr_eqy_exc_min_int) in fetch_fina()
FINA_FIELDS: dict = {
    "roe": None,                    # computed: net_profit / avg_equity * 100
    "gross_profit": "is_gross_profit",       # 主营业务利润(元), divided by revenue in fetch_fina
    "operating_revenue": "is_revenue",
    "ocf": "cfs_net_cash_operating",
}

# Fields needed from get_fina_reports to compute derived metrics
FINA_REPORT_FIELDS: list = [
    "is_gross_profit",
    "is_revenue",
    "cfs_net_cash_operating",
    "is_n_income_attr_p",            # net profit attributable to parent
    "bs_total_hldr_eqy_exc_min_int", # equity attributable to parent (period-end)
]


def pass_threshold() -> float:
    """
    Get pass score threshold from MUNGER_PASS_THRESHOLD env var.

    Returns:
        float: Threshold value (default 60.0)

    Raises:
        ValueError: If env var cannot be converted to float
    """
    value = os.getenv("MUNGER_PASS_THRESHOLD", "60.0")
    return float(value)


def pledge_max() -> float:
    """
    Get pledge ratio maximum from MUNGER_PLEDGE_MAX env var.

    Returns:
        float: Max pledge ratio (default 0.50)

    Raises:
        ValueError: If env var cannot be converted to float
    """
    value = os.getenv("MUNGER_PLEDGE_MAX", "0.50")
    return float(value)


def ir_months() -> int:
    """
    Get investor relations query window from MUNGER_IR_MONTHS env var.

    Returns:
        int: Number of months (default 12)

    Raises:
        ValueError: If env var cannot be converted to int
    """
    value = os.getenv("MUNGER_IR_MONTHS", "12")
    return int(value)


def get_credentials() -> tuple[str, str]:
    """
    Load Panda Data credentials from environment variables.

    Returns:
        tuple[str, str]: (username, password) pair

    Raises:
        RuntimeError: If either PANDA_DATA_USERNAME or PANDA_DATA_PASSWORD
                     is not set in environment
    """
    username = os.getenv("PANDA_DATA_USERNAME")
    password = os.getenv("PANDA_DATA_PASSWORD")

    if not username or not password:
        raise RuntimeError(
            "Credentials not found in environment. "
            "Set PANDA_DATA_USERNAME and PANDA_DATA_PASSWORD."
        )

    return (username, password)
