"""通达信概念成分索引（离线缓存）→ 代码↔题材映射。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

SKIP_CONCEPTS = frozenset(
    {
        "沪股通",
        "深股通",
        "融资融券",
        "同花顺果指数",
        "含H股",
        "含B股",
        "ST板块",
        "转融券标的",
        "MSCI概念",
    }
)


def members_index_mtime() -> float:
    from sectors.tdx import TDX_MEMBERS_INDEX

    p = Path(TDX_MEMBERS_INDEX)
    try:
        return float(p.stat().st_mtime) if p.is_file() else 0.0
    except OSError:
        return 0.0


@lru_cache(maxsize=4)
def load_concept_maps(
    codes_key: tuple[str, ...],
    members_mtime: float = 0.0,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """返回 (code→概念列表, 概念→成分代码列表)，仅保留宇宙内且成员≥3 的概念。

    `members_mtime` 纳入缓存键：通达信成分文件更新后自动换图，不沿用进程内旧表。
    """
    del members_mtime
    from sectors.tdx import load_members_index

    universe = set(codes_key)
    raw = load_members_index().get("概念") or {}
    code_to_concepts: dict[str, list[str]] = {}
    concept_to_codes: dict[str, list[str]] = {}
    for name, members in raw.items():
        if name in SKIP_CONCEPTS:
            continue
        filtered = sorted({str(c).zfill(6) for c in members if str(c).zfill(6) in universe})
        if len(filtered) < 3:
            continue
        concept_to_codes[name] = filtered
        for code in filtered:
            code_to_concepts.setdefault(code, []).append(name)
    return code_to_concepts, concept_to_codes


def theme_lu_stats(
    code: str,
    lu_codes: set[str],
    *,
    code_to_concepts: dict[str, list[str]],
    concept_to_codes: dict[str, list[str]],
) -> tuple[int, str, int]:
    """返回 (题材涨停同伴数, 最强题材名, 题材内总同伴数含自身宇宙)。"""
    best_cnt = 0
    best_name = ""
    best_members = 0
    for concept in code_to_concepts.get(code, []):
        members = concept_to_codes.get(concept, [])
        cnt = sum(1 for c in members if c in lu_codes)
        if cnt > best_cnt:
            best_cnt = cnt
            best_name = concept
            best_members = len(members)
    return best_cnt, best_name, best_members
