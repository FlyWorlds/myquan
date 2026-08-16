"""策略七 · 因子5事件候选池 + 因子1止损覆盖层。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy7"
STRATEGY_NAME = "策略七"

FACTOR_BINDINGS = (
    bind_factor(
        "factor5",
        label="Serenity前瞻主题候选池",
        role="universe",
        lookback_days=0,
        post_limit=0,
        max_themes=3,
        max_positions=5,
        max_candidates=5,
        max_per_theme=2,
        filter_desc=(
            "复核上一A股收盘后至当前时点的全部 Serenity 公开帖，再通过 Serenity "
            "Research Model Skill 语义筛选并映射前三主题的 A 股代理池；"
            "总数最多5只、单主题最多2只；"
            "空槽每日补仓；没有候选则保持现金"
        ),
        enabled=True,
    ),
    bind_factor(
        "factor1",
        label="因子1止损覆盖层",
        role="exit",
        stop_pct=0.025,
        filter_desc="仅对已持仓股票执行 T+1 后的开盘-2.5%盘中止损；不用于开仓",
        enabled=True,
    ),
)
