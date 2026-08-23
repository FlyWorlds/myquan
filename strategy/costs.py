"""全策略统一费率。

A 股股票默认（相对成交金额）：
  买入：佣金万 0.86 + 杂费万 0.10 + 滑点 0.1%
  卖出：佣金万 0.86 + 杂费万 0.10 + 印花税万 5 + 滑点 0.1%
场内 ETF：印花税为 0，其余同股票。

akquant 只有「佣金 + 卖出印花」两档，杂费并入双边佣金
（ENGINE_COMMISSION_RATE）。研究模拟同样按此口径。
"""

from __future__ import annotations

COMMISSION_RATE = 0.000086
MISC_FEE_RATE = 0.000010
STAMP_TAX_RATE = 0.0005
ETF_STAMP_TAX_RATE = 0.0
SLIPPAGE_VALUE = 0.001

ENGINE_COMMISSION_RATE = COMMISSION_RATE + MISC_FEE_RATE

FEE_ROUND_TRIP = 2.0 * ENGINE_COMMISSION_RATE + STAMP_TAX_RATE
COST_ROUND_TRIP = FEE_ROUND_TRIP + 2.0 * SLIPPAGE_VALUE


def stamp_tax_for_code(code: str) -> float:
    """6 位代码：5/1 开头按 ETF 免印花，其余按股票印花。"""
    raw = str(code or "").lower().replace("sh", "").replace("sz", "")
    if raw.startswith(("5", "1")):
        return ETF_STAMP_TAX_RATE
    return STAMP_TAX_RATE


def fee_rules_text(*, etf: bool = False) -> str:
    stamp = ETF_STAMP_TAX_RATE if etf else STAMP_TAX_RATE
    return (
        f"佣金万{COMMISSION_RATE * 10000:.2f}；"
        f"杂费万{MISC_FEE_RATE * 10000:.2f}（买卖）；"
        f"印花税(卖)万{stamp * 10000:.1f}；"
        f"滑点{SLIPPAGE_VALUE * 100:.1f}%"
    )
