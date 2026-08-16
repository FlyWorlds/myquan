from __future__ import annotations

from factor_grouped_wrapper.grouping import balanced_groups


def test_balanced_groups_are_deterministic_complete_and_nearly_equal() -> None:
    factors = [f"alpha101_{index:03d}" for index in range(11)] + [
        f"alpha191_{index:03d}" for index in range(8)
    ]
    first = balanced_groups(
        factors,
        seed=42,
        source_prefixes=["alpha101_", "alpha191_"],
        target_group_count=6,
    )
    second = balanced_groups(
        reversed(factors),
        seed=42,
        source_prefixes=["alpha101_", "alpha191_"],
        target_group_count=6,
    )
    assert first == second
    assert sorted(name for group in first for name in group) == sorted(factors)
    assert max(map(len, first)) - min(map(len, first)) <= 1


def test_group_size_allows_a_balanced_non_tiny_last_group() -> None:
    groups = balanced_groups([f"f{index}" for index in range(23)], seed=7, group_size=10)
    assert sorted(map(len, groups)) == [7, 8, 8]
