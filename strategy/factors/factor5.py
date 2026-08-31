"""因子5：Serenity 公开前瞻 thesis → A 股主题研究候选池。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.serenity_factor5 import DEFAULT_OUTPUT, write_snapshot


FACTOR_ID = "factor5"
FACTOR_NAME = "因子5-Serenity前瞻主题"

_RULES = """\
================================================================================
  因子5 · Serenity 公开前瞻主题（研究池）
================================================================================
  · 输入：Serenity Research Model Skill 的公开帖子材料。
  · 处理：通过 Serenity Research Model Skill 做主题提取与语义复核；先取
    最近一个已完成 A 股交易日 15:00（北京时间）后至当前时点的全部帖子，
    再剔除引用污染、回顾收益与明显空头表述。
  · 输出：光通信/CPO、存储、数据中心电力、机器人、算力基础设施、半导体等主题对应的 A 股候选池。
  · 容量：总候选最多5只，单主题最多2只；按主题信号强度轮询分配席位。
  · 映射：A 股代码是主题代理，不代表 Serenity 点名、持有或推荐该 A 股公司。
  · 更新：python -m strategy.run_factor5_serenity --refresh
  · 用途：研究筛选；需叠加公告、客户认证、流动性和独立风控验证，不能直接生成交易指令。
================================================================================
""".strip()


def signal(**kwargs: Any) -> dict[str, Any]:
    """生成最新研究候选快照，供策略或盯盘层读取。"""
    output = write_snapshot(
        kwargs.get("output", DEFAULT_OUTPUT),
        posts_path=kwargs.get("posts_path") or None,
        asof=kwargs.get("asof"),
        lookback_days=kwargs.get("lookback_days", 0),
        post_limit=kwargs.get("post_limit", 0),
        max_candidates=kwargs.get("max_candidates", 5),
        max_per_theme=kwargs.get("max_per_theme", 2),
    )
    return {
        "factor_id": FACTOR_ID,
        "action": "research_candidates_updated",
        "snapshot": str(output),
        "source_skill": "serenity-research-model",
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "读取 Serenity 公开帖的前瞻主题并映射 A 股概念代理池；"
        "动态研究筛选，不是纯价量因子或跨市场跟单。"
    ),
    rules_text=_RULES,
    implemented=True,
    signal=signal,
    meta={
        "kind": "public_thesis_theme_selector",
        "source_skill": "serenity-research-model",
        "default_lookback_days": 0,
        "max_candidates": 5,
        "max_per_theme": 2,
        "default_post_limit": 3,
        "refresh_command": "python -m strategy.run_factor5_serenity --refresh",
        "output": str(DEFAULT_OUTPUT),
        "research_only": True,
    },
)

register_factor(SPEC, replace=True)
