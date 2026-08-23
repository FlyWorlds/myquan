"""策略三 · 因子5事件候选池：单主题一只、固定持有五日。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy3"
STRATEGY_NAME = "策略三·主题事件"

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
        max_per_theme=1,
        hold_days=5,
        filter_desc=(
            "复核上一A股收盘后至当前时点的全部 Serenity 公开帖，再通过 Serenity "
            "Research Model Skill 语义筛选并映射前三主题的 A 股代理池；"
            "仅中证500/1000主板非ST成分股；"
            "总数最多5只、单主题最多1只、固定持有5日；"
            "新事件同主题替换旧持仓，不同主题满仓时替换最早入池持仓；"
            "没有候选则保持现金"
        ),
        enabled=True,
    ),
)
