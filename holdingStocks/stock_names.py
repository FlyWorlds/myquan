"""A 股 code/symbol → 中文名称（盯盘 / 选股共用）。"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_AK_CACHE = Path(__file__).resolve().parent / "cache" / "a_share_code_names.json"
_CACHE_MIN_SIZE = 5400
_CACHE_MAX_AGE_SEC = 3 * 86400


def code_from_symbol(sym: str) -> str:
    s = str(sym).strip().lower()
    if len(s) >= 8 and s[:2] in ("sh", "sz"):
        return s[2:].zfill(6)
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else s


def _is_bad_name(code: str, name: str) -> bool:
    c = str(code).zfill(6)
    n = str(name or "").strip()
    if not n:
        return True
    if n.lower().startswith(("sh", "sz")):
        return True
    if n.startswith("SYN"):
        return True
    if n.isdigit() and n.zfill(6) == c:
        return True
    return False


def _read_name_cache() -> dict[str, str]:
    if not _AK_CACHE.is_file():
        return {}
    try:
        raw = json.loads(_AK_CACHE.read_text(encoding="utf-8"))
        return {
            str(k).zfill(6): str(v).strip()
            for k, v in raw.items()
            if v and not _is_bad_name(str(k).zfill(6), str(v))
        }
    except Exception:  # noqa: BLE001
        return {}


def _write_name_cache(data: dict[str, str]) -> None:
    if not data:
        return
    _AK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _AK_CACHE.write_text(
        json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=0),
        encoding="utf-8",
    )


def _cache_stale(data: dict[str, str]) -> bool:
    if not data:
        return True
    if len(data) < _CACHE_MIN_SIZE:
        return True
    if not _AK_CACHE.is_file():
        return True
    return (time.time() - _AK_CACHE.stat().st_mtime) > _CACHE_MAX_AGE_SEC


def _fetch_akshare_full_map() -> dict[str, str]:
    """仅 CLI 刷新缓存时使用（akshare 非线程安全）。"""
    out: dict[str, str] = {}
    try:
        from strategy.data import AKSHARE_CALL_LOCK
        import akshare as ak

        with AKSHARE_CALL_LOCK:
            df = ak.stock_info_a_code_name()
        for _, r in df.iterrows():
            c = str(r.get("code", "")).zfill(6)
            n = str(r.get("name", "")).strip()
            if c and n and not _is_bad_name(c, n):
                out[c] = n
    except Exception:  # noqa: BLE001
        pass
    return out


def _fetch_baostock_full_map() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            return out
        day = pd.Timestamp.now().strftime("%Y-%m-%d")
        rs = bs.query_all_stock(day=day)
        if rs.error_code != "0":
            rs = bs.query_all_stock(day=pd.Timestamp.now().normalize().strftime("%Y-%m-%d"))
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            sym = str(row[0] or "")
            name = str(row[2] if len(row) > 2 else "").strip()
            code = "".join(ch for ch in sym if ch.isdigit())[-6:].zfill(6)
            if code and name and not _is_bad_name(code, name):
                out[code] = name
        bs.logout()
    except Exception:  # noqa: BLE001
        pass
    return out


def _merge_refresh_name_cache(existing: dict[str, str]) -> dict[str, str]:
    out = dict(existing)
    ak = _fetch_akshare_full_map()
    if ak:
        out.update(ak)
    else:
        bs = _fetch_baostock_full_map()
        for c, n in bs.items():
            out.setdefault(c, n)
    if out:
        _write_name_cache(out)
    return out


@lru_cache(maxsize=1)
def _local_name_map() -> dict[str, str]:
    """盯盘热路径：只读本地 JSON，不触发 akshare 网络。"""
    return _read_name_cache()


@lru_cache(maxsize=512)
def _lookup_name_online(code: str) -> str:
    """单票东财补查（不用 akshare，避免 py_mini_racer 崩溃）。"""
    c = str(code).zfill(6)
    if not c.isdigit() or len(c) != 6:
        return ""
    try:
        import requests

        secid = f"1.{c}" if c[0] in "569" else f"0.{c}"
        resp = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": secid, "fields": "f58"},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
            timeout=6,
        )
        data = (resp.json() or {}).get("data") or {}
        n = str(data.get("f58") or "").strip()
        if n and not _is_bad_name(c, n):
            _remember_name(c, n)
            return n
    except Exception:  # noqa: BLE001
        pass
    return ""


def _remember_name(code: str, name: str) -> None:
    c = str(code).zfill(6)
    n = str(name).strip()
    if _is_bad_name(c, n):
        return
    data = _read_name_cache()
    if data.get(c) == n:
        return
    data[c] = n
    _write_name_cache(data)
    _local_name_map.cache_clear()
    name_by_code.cache_clear()


@lru_cache(maxsize=1)
def name_by_code() -> dict[str, str]:
    """code → 中文名（results.csv 优先，其次宇宙表 / 定盘池 / 持仓登记 / 本地 JSON）。"""
    out: dict[str, str] = {}

    def _put(code: Any, name: Any) -> None:
        if code is None or name is None:
            return
        c = str(code).zfill(6)
        n = str(name).strip()
        if not c or not n or _is_bad_name(c, n):
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

    for c, n in _local_name_map().items():
        if c not in out:
            out[c] = n

    return out


def resolve_stock_name(*, symbol: str = "", code: str = "", name: str = "") -> str:
    """补全中文名称。"""
    sym = str(symbol or "").strip()
    c = str(code or "").strip() or code_from_symbol(sym)
    if c.isdigit():
        c = c.zfill(6)
    n = str(name or "").strip()
    if n and n not in {sym, c} and not _is_bad_name(c, n):
        return n
    hit = name_by_code().get(c)
    if hit:
        return hit
    hit = _read_name_cache().get(c)
    if hit:
        return hit
    online = _lookup_name_online(c)
    if online:
        return online
    return n if n and not _is_bad_name(c, n) else ""


def lookup_names_for_codes(codes: list[str]) -> dict[str, str]:
    """批量 code→中文名（池表/快照用，尽量不走逐码网络）。"""
    base = name_by_code()
    ak = _read_name_cache()
    out: dict[str, str] = {}
    for raw in codes:
        c = str(raw).zfill(6)
        if not c.isdigit():
            continue
        n = base.get(c) or ak.get(c)
        if not n:
            n = resolve_stock_name(code=c)
        if n:
            out[c] = n
    return out


def warm_name_cache() -> int:
    """watch 启动时预热名称表（仅本地 JSON，不拉 akshare）。"""
    invalidate_name_cache()
    table = name_by_code()
    return len(table)


def refresh_name_cache(*, force: bool = False) -> int:
    """手动刷新全量名称缓存（可走 akshare），返回条目数。"""
    existing = {} if force else _read_name_cache()
    stale = _cache_stale(existing)
    if force or stale:
        data = _merge_refresh_name_cache(existing)
    else:
        data = existing
    invalidate_name_cache()
    return len(data)


def invalidate_name_cache() -> None:
    name_by_code.cache_clear()
    _local_name_map.cache_clear()
    _lookup_name_online.cache_clear()
