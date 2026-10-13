from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import QuoteRecord


@dataclass(frozen=True)
class QuoteDisagreement:
    code: str
    field: str
    severity: str
    message: str
    values: dict[str, float | str | None]


def _num(v: float | int | str | None) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _spread(values: dict[str, float | None]) -> tuple[float, float] | None:
    nums = [float(v) for v in values.values() if v is not None]
    if len(nums) < 2:
        return None
    return min(nums), max(nums)


def compare_quote_records(
    quotes: Iterable[QuoteRecord],
    *,
    price_abs_tol: float = 0.02,
    price_pct_tol: float = 0.002,
    fields: tuple[str, ...] = ("last", "open", "high", "low", "prev_close"),
) -> list[QuoteDisagreement]:
    """Compare normalized quotes from multiple sources.

    The helper only reports when at least two sources provide the same field.
    It does not decide trading behavior; callers can map disagreements to
    health severities.
    """
    by_code: dict[str, list[QuoteRecord]] = {}
    for q in quotes:
        by_code.setdefault(str(q.code).zfill(6), []).append(q)
    issues: list[QuoteDisagreement] = []
    for code, rows in by_code.items():
        if len({r.source for r in rows}) < 2:
            continue
        for field in fields:
            values = {r.source: _num(getattr(r, field)) for r in rows}
            span = _spread(values)
            if span is None:
                continue
            lo, hi = span
            base = max(abs(lo), 0.01)
            abs_diff = hi - lo
            pct_diff = abs_diff / base
            if abs_diff <= price_abs_tol and pct_diff <= price_pct_tol:
                continue
            issues.append(
                QuoteDisagreement(
                    code=code,
                    field=field,
                    severity="block_trading",
                    message=(
                        f"{code} {field} 多源不一致: "
                        f"min={lo:.4f}, max={hi:.4f}, diff={abs_diff:.4f}"
                    ),
                    values={k: v for k, v in values.items() if v is not None},
                )
            )
    return issues
