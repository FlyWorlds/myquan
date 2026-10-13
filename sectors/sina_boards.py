"""新浪板块摘要行情。

这个源返回的是板块级汇总，不需要逐个成分股聚合，适合 Web 首屏快速展示。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests

SINA_INDUSTRY_URL = "https://money.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_CONCEPT_URL = "https://money.finance.sina.com.cn/q/view/newFLJK.php?param=class"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn",
}


@dataclass(frozen=True)
class SinaBoard:
    code: str
    name: str
    count: int | None
    avg_price: float | None
    change: float | None
    chg_pct: float | None
    volume: float | None
    amount: float | None
    leader_code: str
    leader_chg_pct: float | None
    leader_price: float | None
    leader_change: float | None
    leader_name: str


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str | None) -> int | None:
    num = _to_float(value)
    return int(num) if num is not None else None


def _extract_var_object(script: str) -> dict[str, str]:
    m = re.search(r"=\s*(\{.*\})\s*;?\s*$", script.strip(), flags=re.S)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def parse_sina_board_script(script: str) -> list[SinaBoard]:
    """解析新浪板块脚本变量。

    每行 value 是逗号分隔字段：
    code,name,count,avg_price,change,chg_pct,volume,amount,leader_code,
    leader_chg_pct,leader_price,leader_change,leader_name
    """
    rows: list[SinaBoard] = []
    for value in _extract_var_object(script).values():
        parts = value.split(",")
        if len(parts) < 13:
            continue
        name = parts[1].strip()
        if not name:
            continue
        rows.append(
            SinaBoard(
                code=parts[0].strip(),
                name=name,
                count=_to_int(parts[2]),
                avg_price=_to_float(parts[3]),
                change=_to_float(parts[4]),
                chg_pct=_to_float(parts[5]),
                volume=_to_float(parts[6]),
                amount=_to_float(parts[7]),
                leader_code=parts[8].strip(),
                leader_chg_pct=_to_float(parts[9]),
                leader_price=_to_float(parts[10]),
                leader_change=_to_float(parts[11]),
                leader_name=parts[12].strip(),
            )
        )
    return rows


def _fetch_script(url: str, *, timeout: float) -> str:
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.content.decode("gbk", "ignore")


def fetch_sina_boards(kind: str = "concept", *, timeout: float = 3.0) -> list[SinaBoard]:
    """拉取新浪行业/概念板块摘要。kind: concept 或 industry。"""
    url = SINA_CONCEPT_URL if kind != "industry" else SINA_INDUSTRY_URL
    return parse_sina_board_script(_fetch_script(url, timeout=timeout))


def fetch_sina_concept_spot_fast(*, timeout: float = 3.0) -> dict[str, dict[str, Any]]:
    """返回与 conceptToday 兼容的概念板块快照。"""
    out: dict[str, dict[str, Any]] = {}
    for row in fetch_sina_boards("concept", timeout=timeout):
        out[row.name] = {
            "code": row.code,
            "name": row.name,
            "涨跌幅": row.chg_pct,
            "close": row.avg_price,
            "资金": row.amount,
            "资金口径": "新浪板块成交额",
            "成分数": row.count,
            "领涨代码": row.leader_code[-6:] if row.leader_code else "",
            "领涨名称": row.leader_name,
            "领涨涨幅": row.leader_chg_pct,
            "领涨现价": row.leader_price,
        }
    return out
