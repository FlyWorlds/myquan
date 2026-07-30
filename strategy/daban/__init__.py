"""打板战法 — 涨停封板买、不连板卖。"""

from strategy.daban.rules import STRATEGY_RULES, is_limit_up_close, is_sealed_limit_up

__all__ = ["STRATEGY_RULES", "is_limit_up_close", "is_sealed_limit_up"]
