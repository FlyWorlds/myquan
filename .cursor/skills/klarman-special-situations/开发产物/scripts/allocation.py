"""分散押注建议器 —— Klarman 关键坑：借壳/重组失败率 30%+ 须分散。

不输出具体仓位、不输出交易指令。只输出：
  - max_weight_per_event（单事件权重上限，基于 Kelly-lite 折算）
  - suggested_positions（在给定权重上限下能承载多少候选）
  - concentration_risk（当前候选池的集中度警告）

用法：
    from allocation import suggest_diversification
    result = suggest_diversification(qualified_events, failure_rate=0.30)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class DiversificationAdvice:
    """
    仅指导性建议，不构成交易指令。

    max_weight_per_event  单事件权重上限（如 0.05 表示不建议超过 5%）
    suggested_positions   给定失败率下建议的最小持有数量
    concentration_flags   集中度风险标签列表
    rationale             解释性文字
    """
    max_weight_per_event: float
    min_positions: int
    concentration_flags: list[str]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_weight_per_event": self.max_weight_per_event,
            "min_positions": self.min_positions,
            "concentration_flags": list(self.concentration_flags),
            "rationale": self.rationale,
            "disclaimer": (
                "此为分散度指导，不是交易指令；不含具体仓位、方向、时点或收益承诺。"
            ),
        }


def _worst_case_dispersion_bound(
    failure_rate: float,
    tolerated_drawdown: float,
    permanent_loss_pct: float = 0.5,
) -> int:
    """基于二项失败次数的均值+2σ 上界估算最小持仓数。

    等权组合，单事件失败时永久损失 permanent_loss_pct（默认 50%——Klarman 保守估
    计而非 100%）。组合损失 ≈ (K/N) × permanent_loss_pct，其中 K 是失败数。
    K/N 的 mean+2σ ≈ p + 2√(p(1-p)/N)。要求
        (p + 2√(p(1-p)/N)) × permanent_loss_pct ≤ tolerated_drawdown
    解出 N。

    Klarman 参数下（p=0.30, loss=0.50, dd=0.10）：
        p×loss = 0.15 > 0.10 → 即便完美分散也超回撤。tolerated_drawdown
        必须 ≥ p×permanent_loss_pct 才有解。
    """
    if failure_rate <= 0:
        return 5
    expected_loss = failure_rate * permanent_loss_pct
    if tolerated_drawdown < expected_loss:
        # 无解：即使无限分散，期望损失就已超过忍受度
        return 999
    slack = tolerated_drawdown / permanent_loss_pct - failure_rate
    if slack <= 0:
        return 999
    var = failure_rate * (1 - failure_rate)
    n = int((2 * (var ** 0.5) / slack) ** 2 + 0.999)
    return max(n, 5)


def suggest_diversification(
    qualified_events: Iterable[Mapping[str, Any]],
    failure_rate: float = 0.30,
    tolerated_drawdown: float = 0.20,
    permanent_loss_pct: float = 0.50,
    hard_cap_per_event: float = 0.05,
) -> DiversificationAdvice:
    """给出分散度指导。

    Args:
        qualified_events: qualified_special_situation 候选事件序列。
        failure_rate: Klarman 关键坑参数，重组/借壳约 0.30。
        tolerated_drawdown: 可承受的最坏组合回撤（默认 20%）。必须 ≥
            failure_rate × permanent_loss_pct 才有解。
        permanent_loss_pct: 单事件失败时的永久损失比例（Klarman 保守 0.50）。
        hard_cap_per_event: 单事件权重硬顶（默认 5%）。
    """
    events = list(qualified_events)
    n_events = len(events)
    min_positions = _worst_case_dispersion_bound(
        failure_rate, tolerated_drawdown, permanent_loss_pct
    )
    max_weight = min(hard_cap_per_event, 1.0 / max(min_positions, 1))

    flags: list[str] = []
    if n_events == 0:
        flags.append("no_qualified_candidates")
    elif n_events < min_positions:
        flags.append(
            f"insufficient_diversification: 仅 {n_events} 个合格候选，"
            f"低于失败率 {failure_rate:.0%} 下建议的最小持仓数 {min_positions}"
        )

    situations: dict[str, int] = {}
    symbols: set[str] = set()
    for ev in events:
        st = str(ev.get("situation_type") or ev.get("result_type") or "unknown")
        situations[st] = situations.get(st, 0) + 1
        sym = str(ev.get("symbol") or "")
        if sym:
            symbols.add(sym)

    for st, cnt in situations.items():
        if n_events and cnt / n_events > 0.5:
            flags.append(
                f"situation_concentration:{st} 占 {cnt}/{n_events}, 超 50%"
            )

    if len(symbols) < n_events:
        flags.append(
            f"symbol_repetition: {n_events} 事件仅 {len(symbols)} 唯一股，存在同一标的多事件叠加"
        )

    rationale = (
        f"基于失败率 {failure_rate:.0%}、失败永久损失 {permanent_loss_pct:.0%}、"
        f"可承受回撤 {tolerated_drawdown:.0%}，建议至少持有 {min_positions} 个"
        f"独立事件，单事件权重上限 {max_weight:.1%}。当前候选 {n_events} 个。"
    )
    return DiversificationAdvice(
        max_weight_per_event=float(max_weight),
        min_positions=int(min_positions),
        concentration_flags=flags,
        rationale=rationale,
    )


if __name__ == "__main__":
    import json
    demo = [
        {"symbol": "600001.SH", "situation_type": "reorganization"},
        {"symbol": "600002.SH", "situation_type": "reorganization"},
        {"symbol": "000300.SZ", "situation_type": "distress_turnaround"},
    ]
    advice = suggest_diversification(demo)
    print(json.dumps(advice.to_dict(), ensure_ascii=False, indent=2))
