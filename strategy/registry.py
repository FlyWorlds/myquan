"""策略注册表：当前仅 OpenBreak3。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class StrategyEntry:
    id: str
    name: str
    run: Callable[..., Any]
    default_config: Any
    print_rules: Callable[[], str] | None = None


def _rules_open_break() -> str:
    from strategy.open_break import STRATEGY_RULES

    return STRATEGY_RULES.strip()


def _load_entries() -> dict[str, StrategyEntry]:
    from strategy.config import KAICHENG
    from strategy.runner import run_open_break

    return {
        "open_break3": StrategyEntry(
            id="open_break3",
            name="OpenBreak3 开盘±pct",
            run=run_open_break,
            default_config=KAICHENG,
            print_rules=_rules_open_break,
        ),
    }


REGISTRY: dict[str, StrategyEntry] = _load_entries()


def get_strategy(strategy_id: str) -> StrategyEntry:
    if strategy_id not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"未知策略 '{strategy_id}'，可选: {known}")
    return REGISTRY[strategy_id]


def list_strategies() -> list[StrategyEntry]:
    return list(REGISTRY.values())
