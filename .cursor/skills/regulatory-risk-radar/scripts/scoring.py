"""
scoring.py — 6 类合规/监管风险的评分与分级

设计原则：
  - 每类事件给一个 0~100 的子分，综合分 = 各子分加权后取"风险聚合"（非简单平均，
    用 1-∏(1-p) 形式，避免多类轻风险被平均稀释）。
  - 子分 = 严重度基准 × 规模因子 × 时间邻近因子。
  - 映射：<25 low, 25~55 medium, >=55 high。

所有阈值与权重集中在此，references/risk-taxonomy.md 有依据说明。
"""
from __future__ import annotations
import math
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Any


def _parse(d: str | None):
    if not d:
        return None
    d = str(d).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(d, fmt)
        except ValueError:
            continue
    return None


def _days_between(a: datetime | None, b: datetime | None):
    if not a or not b:
        return None
    return (b - a).days


def _recency_factor(days_ago: int | None, half_life: int = 90) -> float:
    """越近的事件权重越高，半衰期 half_life 天。缺失时给中性 0.6。"""
    if days_ago is None:
        return 0.6
    if days_ago < 0:
        return 1.0  # 未来事件（如解禁）按最高时效
    return 0.5 ** (days_ago / half_life)


# 各风险源严重度基准（0~100）
BASE = {
    "reduction": 55,   # 减持计划
    "restricted": 45,  # 限售解禁
    "pledge": 40,      # 股权质押
    "placard": 25,     # 举牌（中性偏事件）
    "freeze": 60,      # 股权冻结（司法）
    "halt": 70,        # 停牌
    "st": 80,          # ST
}

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Trigger:
    kind: str          # reduction/restricted/pledge/placard/freeze/halt/st
    label: str         # 中文标签
    subscore: float
    evidence: dict = field(default_factory=dict)


@dataclass
class NameRisk:
    symbol: str
    name: str = ""
    score: float = 0.0
    severity: str = "low"
    triggers: list[Trigger] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def score_reduction(rows, today) -> list[Trigger]:
    out = []
    for r in rows:
        if r.get("direction") != "减持":
            continue
        ratio = r.get("ratio_up_limit") or 0.0  # 占总股本比例上限(%)
        days_ago = _days_between(_parse(r.get("info_date")), today)
        # 规模因子：减持占比越大越危险，1% 记满
        size = min(1.0, float(ratio) / 1.0) if ratio else 0.3
        holder = 1.15 if r.get("shareholder_type") in ("股东", "实际控制人") else 0.9
        sub = _clip(BASE["reduction"] * (0.4 + 0.6 * size) * _recency_factor(days_ago) * holder)
        out.append(Trigger("reduction", "股东减持计划", round(sub, 1), {
            "shareholder": r.get("shareholder_name"),
            "type": r.get("shareholder_type"),
            "ratio_up_limit_pct": ratio,
            "progress": r.get("progress"),
            "info_date": r.get("info_date"),
        }))
    return out


def score_restricted(rows, today) -> list[Trigger]:
    out = []
    for r in rows:
        relieve = _parse(r.get("relieve_date"))
        days_to = _days_between(today, relieve)  # 未来为正
        shares = r.get("relieve_shares") or 0.0
        # 临近解禁风险更高；已过去的忽略
        if days_to is not None and days_to < 0:
            continue
        sub = _clip(BASE["restricted"] * _recency_factor(days_to))
        out.append(Trigger("restricted", "限售解禁临近", round(sub, 1), {
            "relieve_date": r.get("relieve_date"),
            "relieve_shares": shares,
            "shareholder_type": r.get("shareholder_type"),
            "reason": r.get("relieve_reason"),
        }))
    return out


def score_pledge(rows, today) -> list[Trigger]:
    out = []
    for r in rows:
        acc = r.get("acc_pledge_total_ratio") or 0.0  # 累计质押占总股本(%)
        days_ago = _days_between(_parse(r.get("publish_date")), today)
        size = min(1.0, float(acc) / 30.0) if acc else 0.3  # 30% 累计质押记满
        sub = _clip(BASE["pledge"] * (0.4 + 0.6 * size) * _recency_factor(days_ago, half_life=180))
        out.append(Trigger("pledge", "股权质押", round(sub, 1), {
            "shareholder": r.get("shareholder_name"),
            "acc_pledge_total_ratio_pct": acc,
            "publish_date": r.get("publish_date"),
        }))
    return out


def score_placard(rows, today) -> list[Trigger]:
    out = []
    for r in rows:
        days_ago = _days_between(_parse(r.get("info_date")), today)
        sub = _clip(BASE["placard"] * _recency_factor(days_ago))
        out.append(Trigger("placard", "被举牌", round(sub, 1), {
            "shareholder": r.get("shareholder_name"),
            "ratio_pct": r.get("total_share_ratio"),
            "info_date": r.get("info_date"),
        }))
    return out


def score_freeze(rows, today) -> list[Trigger]:
    del today
    out = []
    seen = set()
    for r in rows:
        try:
            frozen = float(r.get("freeze"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(frozen) or frozen <= 0:
            continue
        key = (r.get("holder_name"), r.get("date"), frozen)
        if key in seen:
            continue
        seen.add(key)
        sub = _clip(BASE["freeze"] * 0.9)
        out.append(Trigger("freeze", "前十大股东股权冻结", round(sub, 1), {
            "holder": r.get("holder_name"),
            "freeze_shares": frozen,
            "date": r.get("date"),
        }))
    return out


def score_status(daily_rows, today) -> list[Trigger]:
    """从日线判定停牌/ST。取最近一条。"""
    out = []
    if not daily_rows:
        return out
    rows = sorted(daily_rows, key=lambda x: str(x.get("date", "")))
    last = rows[-1]
    name = last.get("name", "") or ""
    ts = last.get("trade_status")
    if ts is not None and int(ts) != 0:
        out.append(Trigger("halt", "停牌", BASE["halt"], {"date": last.get("date"), "trade_status": ts}))
    if "ST" in name.upper().replace("*", ""):
        out.append(Trigger("st", "ST 风险警示", BASE["st"], {"date": last.get("date"), "name": name}))
    return out


def aggregate(subscores: list[float]) -> float:
    """风险聚合：1 - ∏(1 - s/100)，多类风险叠加而非平均。"""
    prod = 1.0
    for s in subscores:
        prod *= (1 - min(1.0, s / 100.0))
    return round((1 - prod) * 100, 1)


def severity_of(score: float) -> str:
    if score >= 55:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def score_name(symbol, name, sources: dict, today) -> NameRisk:
    triggers: list[Trigger] = []
    triggers += score_reduction(sources.get("shareholder_change", []), today)
    triggers += score_restricted(sources.get("restricted", []), today)
    triggers += score_pledge(sources.get("pledge", []), today)
    triggers += score_placard(sources.get("placard", []), today)
    triggers += score_freeze(sources.get("top_holders", []), today)
    triggers += score_status(sources.get("daily", []), today)

    score = aggregate([t.subscore for t in triggers]) if triggers else 0.0
    triggers.sort(key=lambda t: t.subscore, reverse=True)
    return NameRisk(symbol=symbol, name=name, score=score,
                    severity=severity_of(score), triggers=triggers)
