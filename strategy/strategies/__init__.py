"""策略模块（可插拔）。

每个策略包分层：
  · bindings.py  — 策略层：因子绑定 / 参数 / 过滤器
  · decision.py  — 决策层：MarketContext → Decision（buy/sell/hold）
  · __init__.py  — 注册 StrategySpec（含 decision_factory / run）

新增策略：在 strategies/ 下建 strategyN/ 包并 register_strategy；
一般无需再改本文件（自动 discovery）。

故意未纳入现行注册表的目录见 _SKIP_AUTO_IMPORT（如研究中的 strategy13）。
"""

from __future__ import annotations

import importlib
import pkgutil

# 策略注册前先确保因子已注册（多策略共用因子）
import strategy.factors  # noqa: F401

# 目录存在且含 register_strategy，但现行生产/文档未纳入注册表 → 跳过自动 import
_SKIP_AUTO_IMPORT = frozenset(
    {
        "strategy11",  # 无完整包 / 未启用
        "strategy13",  # 周频轮动研究包：有 register，但未进原手工列表
    }
)


def _discover_and_import() -> tuple[str, ...]:
    """扫描 strategies 子包并 import（副作用：register_strategy）。"""
    loaded: list[str] = []
    pkg_name = __name__
    for info in pkgutil.iter_modules(__path__, prefix=f"{pkg_name}."):
        short = info.name.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue
        if short in _SKIP_AUTO_IMPORT:
            continue
        if not short.startswith("strategy"):
            continue
        importlib.import_module(info.name)
        loaded.append(short)
    return tuple(sorted(loaded))


_DISCOVERED = _discover_and_import()

from strategy.core.strategy_registry import (  # noqa: E402
    STRATEGY_REGISTRY,
    get_strategy_spec,
    list_strategy_specs,
)

__all__ = [
    "STRATEGY_REGISTRY",
    "get_strategy_spec",
    "list_strategy_specs",
    "_DISCOVERED",
    "_SKIP_AUTO_IMPORT",
]
