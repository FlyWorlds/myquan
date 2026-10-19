"""A 股代码 → 名称映射（板块成分股展示用，复用数据库 a_share_code_names）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_CACHE: dict[str, str] | None = None
_HOLDING_DIR = Path(__file__).resolve().parents[1] / "holdingStocks"
if str(_HOLDING_DIR) not in sys.path:
    sys.path.insert(0, str(_HOLDING_DIR))


def _load_from_holding_names() -> dict[str, str]:
    try:
        from stock_names import name_by_code

        return dict(name_by_code())
    except Exception:
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
    merged = _load_from_holding_names()
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
