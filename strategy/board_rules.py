"""A 股代码与涨跌停幅度规则（中立工具；strategy / holdingStocks 均可依赖）。

禁止本模块 import holdingStocks。
"""

from __future__ import annotations


def code_key(code: str) -> str:
    return "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]


def sina_of(code: str) -> str:
    c = code_key(code)
    return f"sh{c}" if c.startswith(("5", "6")) else f"sz{c}"


def market_of(code: str) -> str:
    return "上证" if sina_of(code).startswith("sh") else "深证"


def limit_down_pct_of(code: str) -> float:
    """主板约10%；创业板/科创板约20%；ETF 约10%。涨停幅度相同。"""
    c = code_key(code)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


limit_up_pct_of = limit_down_pct_of
