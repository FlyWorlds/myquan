"""主板（非 ST / 非科创 / 非创业板）股票池。"""

from __future__ import annotations

import re

import akshare as ak
import pandas as pd

# 沪市主板 600/601/603/605；深市主板+原中小板 000/001/002
_MAIN_PREFIXES = ("600", "601", "603", "605", "000", "001", "002")
_EXCLUDE_PREFIXES = ("300", "301", "688", "689", "8", "4")


def _is_st_name(name: str) -> bool:
    n = str(name).upper().strip()
    if not n:
        return False
    if "ST" in n.replace(" ", ""):
        return True
    if "退" in n:
        return True
    return False


def code_to_symbol(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{c}"
    return f"sz{c}"


def is_main_board_code(code: str) -> bool:
    c = str(code).zfill(6)
    if any(c.startswith(p) for p in _EXCLUDE_PREFIXES):
        return False
    return any(c.startswith(p) for p in _MAIN_PREFIXES)


def fetch_main_board_universe() -> pd.DataFrame:
    """拉取 A 股列表并过滤：非 ST、非科创、非创业板。"""
    raw = ak.stock_info_a_code_name()
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    code_col = "code" if "code" in df.columns else df.columns[0]
    name_col = "name" if "name" in df.columns else df.columns[1]
    df["code"] = df[code_col].astype(str).str.zfill(6)
    df["name"] = df[name_col].astype(str)
    df = df[df["code"].map(is_main_board_code)]
    df = df[~df["name"].map(_is_st_name)]
    df["symbol"] = df["code"].map(code_to_symbol)
    return df[["code", "name", "symbol"]].drop_duplicates("code").reset_index(drop=True)
