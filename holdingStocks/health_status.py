"""Health issue classification for watch operations.

Classifications are intentionally small and machine-readable so the backend,
UI, and reports can agree on whether a problem blocks paper trading, only
affects notifications, or is display-only.
"""

from __future__ import annotations

from typing import Any

BLOCK_TRADING = "block_trading"
NOTIFICATION_ONLY = "notification_only"
DISPLAY_ONLY = "display_only"
OK = "ok"

_SEVERITY_RANK = {
    OK: 0,
    DISPLAY_ONLY: 1,
    NOTIFICATION_ONLY: 2,
    BLOCK_TRADING: 3,
}


def classify_health_issue(issue: str, **ctx: Any) -> dict[str, Any]:
    kind = str(issue or "").strip().lower()
    if kind in {"quote_stale", "feed_stale"}:
        return {
            "issue": kind,
            "severity": BLOCK_TRADING,
            "reason": "行情源过期，禁止自动买卖，只能沿用旧快照展示。",
        }
    if kind in {"daily_missing", "daily_gap", "daily_source_failed"}:
        return {
            "issue": kind,
            "severity": BLOCK_TRADING,
            "reason": "日线缺失会影响过门、前日过滤和回放，禁止产生新交易动作。",
        }
    if kind in {"quote_partial", "snapshot_cache_stale"}:
        return {
            "issue": kind,
            "severity": DISPLAY_ONLY,
            "reason": "展示可能不完整，但不能单独作为交易阻断依据。",
        }
    if kind in {"wechat_failed", "wechat_session_invalid", "notification_failed"}:
        return {
            "issue": kind,
            "severity": NOTIFICATION_ONLY,
            "reason": "通知通道异常，不影响本地模拟账本和行情计算。",
        }
    return {
        "issue": kind or "unknown",
        "severity": DISPLAY_ONLY,
        "reason": "未知健康事件，默认按展示风险处理并保留人工检查。",
    }


def aggregate_health(issues: list[dict[str, Any]]) -> dict[str, Any]:
    if not issues:
        return {"healthLevel": OK, "healthIssues": [], "blockTrading": False}
    level = max((str(i.get("severity") or DISPLAY_ONLY) for i in issues), key=lambda x: _SEVERITY_RANK.get(x, 1))
    return {
        "healthLevel": level,
        "healthIssues": issues,
        "blockTrading": level == BLOCK_TRADING,
    }


def classify_snapshot_health(snapshot: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if bool(snapshot.get("quoteStale")) or snapshot.get("feedOk") is False:
        issues.append(
            classify_health_issue(
                "quote_stale",
                quoteAt=snapshot.get("quoteAt"),
                quoteAgeSec=snapshot.get("quoteAgeSec"),
            )
        )
    if bool(snapshot.get("dailyMissing")) or bool(snapshot.get("dailyGap")):
        issues.append(classify_health_issue("daily_missing"))
    if bool(snapshot.get("wechatError")) or bool(snapshot.get("wechatSessionInvalid")):
        issues.append(classify_health_issue("wechat_session_invalid"))
    return aggregate_health(issues)
