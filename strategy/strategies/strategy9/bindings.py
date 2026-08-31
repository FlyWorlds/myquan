"""策略九 · 低开跌停情绪（无个股交易因子，大盘情绪研判）。"""

from __future__ import annotations

STRATEGY_ID = "strategy9"
STRATEGY_NAME = "策略九·低开跌停情绪"

# 本策略为大盘情绪研判，不绑定个股买卖因子
FACTOR_BINDINGS: tuple = ()
