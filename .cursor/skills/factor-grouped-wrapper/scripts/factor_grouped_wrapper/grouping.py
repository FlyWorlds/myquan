from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Iterable


def _source(name: str, prefixes: Iterable[str]) -> str:
    return next((prefix for prefix in prefixes if name.startswith(prefix)), "__other__")


def _source_seed(seed: int, source: str) -> int:
    suffix = int(hashlib.sha256(source.encode("utf-8")).hexdigest()[:8], 16)
    return int(seed) ^ suffix


def balanced_groups(
    factors: Iterable[str],
    *,
    seed: int,
    source_prefixes: Iterable[str] = (),
    target_group_count: int | None = None,
    group_size: int | None = None,
) -> list[tuple[str, ...]]:
    names = sorted(set(str(name) for name in factors))
    if not names:
        return []
    if (target_group_count is None) == (group_size is None):
        raise ValueError("Set exactly one of target_group_count or group_size")
    count = min(len(names), int(target_group_count or math.ceil(len(names) / int(group_size))))
    if count < 1:
        raise ValueError("Group count must be positive")

    buckets: dict[str, list[str]] = defaultdict(list)
    for name in names:
        buckets[_source(name, source_prefixes)].append(name)
    groups: list[list[str]] = [[] for _ in range(count)]
    for source_name in sorted(buckets):
        values = buckets[source_name]
        random.Random(_source_seed(seed, source_name)).shuffle(values)
        offset = _source_seed(seed, source_name) % count
        for item_index, factor in enumerate(values):
            minimum = min(len(group) for group in groups)
            eligible = [index for index, group in enumerate(groups) if len(group) == minimum]
            target = eligible[(offset + item_index) % len(eligible)]
            groups[target].append(factor)
    normalized = [tuple(sorted(group)) for group in groups if group]
    if max(map(len, normalized)) - min(map(len, normalized)) > 1:
        raise AssertionError("Balanced grouping invariant failed")
    flattened = [factor for group in normalized for factor in group]
    if sorted(flattened) != names:
        raise AssertionError("Grouping lost or duplicated factors")
    return normalized


def groups_for_stage(factors: Iterable[str], stage: dict, seed: int, prefixes: Iterable[str]) -> list[tuple[str, ...]]:
    kwargs = {}
    if stage.get("target_group_count") is not None:
        kwargs["target_group_count"] = int(stage["target_group_count"])
    else:
        kwargs["group_size"] = int(stage["group_size"])
    return balanced_groups(factors, seed=seed, source_prefixes=prefixes, **kwargs)
