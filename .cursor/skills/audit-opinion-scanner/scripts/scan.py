"""Quarterly audit opinion scanner — single-quarter CLI.

Scans audit opinions for stocks in a given index (default CSI300),
classifies them by risk level, and outputs CSV + Markdown reports.

Usage:
    python scripts/scan.py [--quarter 2024q4] [--index 000300.SH] [--output-dir output/]

Exit codes:
    0 = OK
    1 = panda_data interface / auth / network exception
    2 = target quarter has no audit opinion data
    3 = universe is empty
    4 = field self-check failure
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Allow both `python scripts/scan.py` and `python -m scripts.scan`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import data as data_mod
from scripts import report
from scripts import rules
from scripts import universe as uni_mod

REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A股审计意见风险扫描")
    p.add_argument(
        "--quarter", default=None,
        help="目标季度，如 '2024q4'；默认使用最近完成的季度（基于前一个自然季度推算）",
    )
    p.add_argument(
        "--index", default="000300.SH",
        help="指数代码，默认 000300.SH (CSI300)。也支持 000905.SH (CSI500) 等",
    )
    p.add_argument(
        "--start-quarter", default=None,
        help="扫描起始季度（用于多期批量扫描），格式 'YYYYqN'",
    )
    p.add_argument(
        "--end-quarter", default=None,
        help="扫描结束季度（用于多期批量扫描），格式 'YYYYqN'",
    )
    p.add_argument(
        "--include-internal-control", action="store_true",
        help="同时纳入内部控制审计意见（默认仅纳入财务报表审计意见）",
    )
    p.add_argument(
        "--output-dir", default=str(REPO_ROOT / "output"),
        help="输出目录",
    )
    return p.parse_args()


def _resolve_quarter(explicit: str | None) -> str:
    """Resolve the target quarter. If not provided, use the previous calendar quarter.

    Returns:
        Quarter string like "2024q4".
    """
    if explicit:
        _validate_quarter(explicit)
        return explicit

    from datetime import datetime

    now = datetime.now()
    # Previous quarter: map month → (year_offset, quarter)
    # month 1-3 → prev year q4, 4-6 → q1, 7-9 → q2, 10-12 → q3
    month = now.month
    if month <= 3:
        return f"{now.year - 1}q4"
    elif month <= 6:
        return f"{now.year}q1"
    elif month <= 9:
        return f"{now.year}q2"
    else:
        return f"{now.year}q3"


def _validate_quarter(quarter: str) -> None:
    """Raise ValueError if quarter format is invalid."""
    import re

    if not re.match(r"^\d{4}q[1-4]$", quarter, re.IGNORECASE):
        raise ValueError(f"Invalid quarter format: {quarter!r}. Expected like '2024q4'.")


def _resolve_quarters(start: str | None, end: str | None, default: str) -> tuple[str, str]:
    """Resolve start and end quarters for multi-quarter scanning.

    Returns:
        (start_quarter, end_quarter) tuple.
    """
    if start and end:
        _validate_quarter(start)
        _validate_quarter(end)
        return start, end
    if start:
        _validate_quarter(start)
        return start, start  # single quarter
    if end:
        _validate_quarter(end)
        return end, end
    return default, default


def _build_classified(
    opinions_df: pd.DataFrame,
    universe_symbols: list[str],
    include_internal_control: bool,
    name_map: dict[str, str],
) -> pd.DataFrame:
    """Apply classification rules and join with metadata.

    Args:
        opinions_df: Raw output from get_audit_opinion.
        universe_symbols: List of stock symbols to filter to.
        include_internal_control: If True, also include internal_control audit types.
        name_map: Dict mapping symbol → display name.

    Returns:
        DataFrame with added columns: risk_level, risk_label, name.
    """
    df = opinions_df.copy()

    # Filter to universe
    uni_set = set(universe_symbols)
    df = df[df["symbol"].isin(uni_set)]

    # Filter audit types
    if not include_internal_control:
        df = df[df["audit_type"].apply(rules.classify_audit_type)]

    if df.empty:
        return pd.DataFrame(
            columns=list(opinions_df.columns) + ["risk_level", "risk_label", "name"]
        )

    # Classify
    df["risk_level"] = df["opinion"].apply(rules.classify_opinion)
    df["risk_label"] = df["risk_level"].apply(rules.get_risk_label)
    df["name"] = df["symbol"].map(name_map).fillna("")

    # Sort: highest risk first
    df = df.sort_values(["risk_level", "symbol"], ascending=[False, True])

    return df


def main() -> int:
    args = _parse_args()

    # ---- 1. Auth ----
    try:
        data_mod.init_panda_data()
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[error] panda_data auth failed: {e}", file=sys.stderr)
        return 1

    # ---- 2. Resolve quarters ----
    try:
        default_q = _resolve_quarter(args.quarter)
        start_q, end_q = _resolve_quarters(args.start_quarter, args.end_quarter, default_q)
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    quarter_label = f"{start_q}" if start_q == end_q else f"{start_q}–{end_q}"
    print(f"[info] scanning quarters: {quarter_label}", file=sys.stderr)

    # ---- 3. Universe ----
    try:
        ref_date = data_mod.get_last_trade_date()
        weights = uni_mod.resolve_universe(index_symbol=args.index, date=ref_date)
        symbols = uni_mod.filter_universe(weights, exclude_st=True, reference_date=ref_date)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 3

    # ---- 4. Fetch audit opinions ----
    try:
        opinions = data_mod.load_audit_opinion(
            start_quarter=start_q,
            end_quarter=end_q,
        )
        data_mod._assert_columns(opinions, "audit_opinion")
    except ValueError as e:
        print(f"[error] field self-check failed: {e}", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"[error] panda_data call failed: {e}", file=sys.stderr)
        return 1

    if opinions.empty:
        print(f"[error] no audit opinion data for {quarter_label}", file=sys.stderr)
        return 2

    # ---- 5. Resolve stock names ----
    name_map = data_mod.load_stock_names(symbols)

    # ---- 6. Classify ----
    classified = _build_classified(
        opinions_df=opinions,
        universe_symbols=symbols,
        include_internal_control=args.include_internal_control,
        name_map=name_map,
    )

    summary = rules.summarize(classified)
    unknown_ops = rules.get_unknown_opinion_values(classified["opinion"])
    if unknown_ops:
        parts = []
        for op in unknown_ops:
            suggestion = rules.suggest_mapping(op)
            if suggestion:
                suggested_level = rules.classify_opinion(suggestion)
                parts.append(f"{op!r} → maybe {suggestion!r} (level={suggested_level})")
            else:
                parts.append(f"{op!r} — no suggestion")
        print(
            f"[warn] unknown opinion values detected. "
            f"After verifying real data, add them to OPINION_RISK_MAP in scripts/rules.py.\n"
            f"       Suggestions: {'; '.join(parts)}",
            file=sys.stderr,
        )

    # ---- 7. Write outputs ----
    out_dir = Path(args.output_dir)
    safe_label = quarter_label.replace("–", "_")
    csv_path = out_dir / f"audit_risk_{safe_label}.csv"
    md_path = out_dir / f"audit_risk_{safe_label}.md"

    report.write_csv(classified, str(csv_path))
    report.write_markdown(
        classified,
        str(md_path),
        quarter=quarter_label,
        meta=summary,
    )

    # ---- 8. Print summary ----
    print(f"[info] 扫描季度: {quarter_label}", file=sys.stderr)
    print(f"[info] 股票池: {args.index} ({len(symbols)} 只)", file=sys.stderr)
    print(f"[info] 审计意见记录数: {summary['total']}", file=sys.stderr)
    print(
        f"[info] 风险分布 — "
        f"低:{summary['low']} 中:{summary['medium']} "
        f"高:{summary['high']} 严重:{summary['critical']} "
        f"待确认:{summary['unknown']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
