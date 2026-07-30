"""策略注册表：huice 或脚本可按 id 选择策略。"""

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


def _rules_yin_yang() -> str:
    from strategy.yin_yang.rules import STRATEGY_RULES

    return STRATEGY_RULES.strip()


def _load_entries() -> dict[str, StrategyEntry]:
    from strategy.config import KAICHENG, ZZ500_ETF
    from strategy.daban.config import KAICHENG_DABAN
    from strategy.daban.runner import run_daban
    from strategy.runner import run_open_break
    from strategy.yin_yang.config import KAICHENG_YIN_YANG
    from strategy.yin_yang.runner import run_yin_yang

    return {
        "open_break3": StrategyEntry(
            id="open_break3",
            name="OpenBreak3 开盘±pct",
            run=run_open_break,
            default_config=KAICHENG,
            print_rules=_rules_open_break,
        ),
        "open_break3_zz500": StrategyEntry(
            id="open_break3_zz500",
            name="OpenBreak3 中证500ETF",
            run=run_open_break,
            default_config=ZZ500_ETF,
            print_rules=_rules_open_break,
        ),
        "yin_yang": StrategyEntry(
            id="yin_yang",
            name="日线阴阳 阳买阴卖",
            run=run_yin_yang,
            default_config=KAICHENG_YIN_YANG,
            print_rules=_rules_yin_yang,
        ),
        "oversold_bounce": StrategyEntry(
            id="oversold_bounce",
            name="超跌反弹形态统计",
            run=lambda cfg, **kw: run_oversold_scan(cfg),
            default_config=_oversold_cfg(),
            print_rules=_rules_oversold,
        ),
        "daban": StrategyEntry(
            id="daban",
            name="打板战法 涨停封板",
            run=run_daban,
            default_config=KAICHENG_DABAN,
            print_rules=_rules_daban,
        ),
    }


def _oversold_cfg():
    from strategy.oversold_bounce.stats import ScanConfig

    return ScanConfig(symbol="sh600552", symbol_name="凯盛科技", start_date="20200101")


def _rules_oversold() -> str:
    from strategy.oversold_bounce.rules import STRATEGY_RULES

    return STRATEGY_RULES.strip()


def _rules_daban() -> str:
    from strategy.daban.rules import STRATEGY_RULES

    return STRATEGY_RULES.strip()


def run_oversold_scan(cfg):
    from strategy.oversold_bounce.stats import run_scan

    return run_scan(cfg)


REGISTRY: dict[str, StrategyEntry] = _load_entries()


def get_strategy(strategy_id: str) -> StrategyEntry:
    if strategy_id not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"未知策略 '{strategy_id}'，可选: {known}")
    return REGISTRY[strategy_id]


def list_strategies() -> list[StrategyEntry]:
    return list(REGISTRY.values())
