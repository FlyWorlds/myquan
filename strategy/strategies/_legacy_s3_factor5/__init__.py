"""旧策略三（因子5 Serenity 主题事件）— 归档，供历史回测脚本引用。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strategy.strategies._legacy_s3_factor5.portfolio import (
    simulate_factor5_event_slots_f1_stop,
)

__all__ = ["simulate_factor5_event_slots_f1_stop", "run_factor5_event_backtest"]


def run_factor5_event_backtest(
    *,
    start: str = "20260101",
    end: str = "20260815",
    max_themes: int = 3,
    max_positions: int = 5,
    max_per_theme: int = 1,
    hold_days: int = 5,
    initial_cash: float = 1_000_000.0,
    posts_path: str | Path | None = None,
) -> dict[str, Any]:
    from strategy.backtest_factor5_serenity import run_backtest
    from strategy.serenity_factor5 import DEFAULT_POSTS

    return run_backtest(
        start=start,
        end=end,
        max_themes=max_themes,
        max_positions=max_positions,
        max_per_theme=max_per_theme,
        hold_days=hold_days,
        use_factor1_stop=False,
        initial_cash=initial_cash,
        posts_path=posts_path or DEFAULT_POSTS,
    )
