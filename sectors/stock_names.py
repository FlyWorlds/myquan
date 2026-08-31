"""A 股代码 → 名称映射（板块成分股展示用）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CACHE: dict[str, str] | None = None
_CACHE_PATH = (
    Path(__file__).resolve().parents[1] / "holdingStocks" / "cache" / "a_share_code_names.json"
)


def _load_cache_file() -> dict[str, str]:
    if not _CACHE_PATH.is_file():
        return {}
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k).zfill(6): str(v) for k, v in raw.items()}
    except Exception:
        return {}
    return {}


def _load_akshare() -> dict[str, str]:
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            return {}
        code_col = "code" if "code" in df.columns else df.columns[0]
        name_col = "name" if "name" in df.columns else df.columns[1]
        return {
            str(c).zfill(6): str(n)
            for c, n in zip(df[code_col], df[name_col], strict=False)
            if str(c).strip()
        }
    except Exception:
        return {}


def stock_name_map(*, refresh: bool = False) -> dict[str, str]:
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    merged = _load_cache_file()
    if len(merged) < 1000:
        merged = {**_load_akshare(), **merged}
    _CACHE = merged
    return _CACHE


def stock_name_of(code: Any, *, fallback: str = "") -> str:
    c = str(code or "").strip()
    if c.startswith(("sh", "sz", "SH", "SZ")):
        c = c[2:]
    c = c.zfill(6)
    name = stock_name_map().get(c, "").strip()
    return name or fallback or c
