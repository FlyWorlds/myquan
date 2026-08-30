"""A 股 code/symbol → 中文名称（盯盘 / 选股共用）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]


def code_from_symbol(sym: str) -> str:
    s = str(sym).strip().lower()
    if len(s) >= 8 and s[:2] in ("sh", "sz"):
        return s[2:].zfill(6)
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else s


@lru_cache(maxsize=1)
def name_by_code() -> dict[str, str]:
    """code → 中文名（results.csv 优先，其次宇宙表 / 定盘池 / 持仓登记）。"""
    out: dict[str, str] = {}

    def _put(code: Any, name: Any) -> None:
        if code is None or name is None:
            return
        c = str(code).zfill(6)
        n = str(name).strip()
        if not c or not n:
            return
        if n.isdigit() and n.zfill(6) == c:
            return
        if n.lower().startswith(("sh", "sz")):
            return
        if n.startswith("SYN"):
            return
        out[c] = n

    results_csv = _MYQUAN / "backtest/universe_zz500_1000/results.csv"
    if results_csv.is_file():
        df = pd.read_csv(results_csv)
        for _, r in df.iterrows():
            _put(r.get("code"), r.get("name"))

    for rel in (
        "backtest/universe_zz500_1000/zz500_univ.parquet",
        "backtest/universe_zz500_1000/zz1000_univ.parquet",
        "backtest/strategy3_first_board/zz1000_univ.parquet",
    ):
        p = _MYQUAN / rel
        if not p.is_file():
            continue
        df = pd.read_parquet(p)
        for _, r in df.iterrows():
            _put(r.get("code"), r.get("name"))

    try:
        import json
        import sys

        hs = Path(__file__).resolve().parent
        hp = hs / "holdings.json"
        if hp.is_file():
            data = json.loads(hp.read_text(encoding="utf-8"))
            for code, pos in (data.get("positions") or {}).items():
                if isinstance(pos, dict):
                    _put(code, pos.get("name"))

        if str(hs) not in sys.path:
            sys.path.insert(0, str(hs))
        from watch_config import WATCHLIST, code_key

        for w in WATCHLIST:
            _put(code_key(str(w.get("code", ""))), w.get("name"))
    except Exception:  # noqa: BLE001
        pass

    return out


def resolve_stock_name(*, symbol: str = "", code: str = "", name: str = "") -> str:
    """补全中文名称。"""
    sym = str(symbol or "").strip()
    c = str(code or "").strip() or code_from_symbol(sym)
    if c.isdigit():
        c = c.zfill(6)
    n = str(name or "").strip()
    if n and n not in {sym, c} and not n.lower().startswith(("sh", "sz")) and not n.startswith("SYN"):
        if not (n.isdigit() and n.zfill(6) == c.zfill(6)):
            return n
    hit = name_by_code().get(c)
    if hit:
        return hit
    return n if n and not n.lower().startswith(("sh", "sz")) and not (n.isdigit() and n.zfill(6) == c) else ""


def invalidate_name_cache() -> None:
    name_by_code.cache_clear()
