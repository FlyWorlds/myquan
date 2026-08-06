"""策略骨架共用工具。"""

from __future__ import annotations

from typing import Any, Sequence

from strategy.core.factor_registry import get_factor
from strategy.core.protocols import FactorBinding, FactorSpec, StrategySpec, bind_factor


def load_factors(factor_ids: Sequence[str]) -> list[FactorSpec]:
    return [get_factor(fid) for fid in factor_ids]


def load_bindings(spec: StrategySpec) -> list[tuple[FactorBinding, FactorSpec]]:
    out: list[tuple[FactorBinding, FactorSpec]] = []
    for b in spec.bindings(enabled_only=True):
        out.append((b, get_factor(b.factor_id)))
    return out


def compose_rules(
    strategy_name: str,
    factor_ids: Sequence[str] | None = None,
    *,
    bindings: Sequence[FactorBinding] | None = None,
) -> str:
    parts = [f"【{strategy_name}】"]
    if bindings is not None:
        parts[0] += "因子绑定(含策略侧过滤器/参数):"
        for b in bindings:
            if not b.enabled:
                continue
            f = get_factor(b.factor_id)
            status = "生效" if f.implemented else "占位未实现"
            role = b.role or "both"
            params_txt = ", ".join(f"{k}={v!r}" for k, v in b.params.items()) or "(默认)"
            filt_txt = b.filter_desc or ("(无附加过滤)" if b.filter is None else "(自定义filter)")
            parts.append(
                f"\n----- {b.display_name()} → {f.name}({f.id}) "
                f"[{status}] role={role} -----\n"
                f"策略参数: {params_txt}\n"
                f"策略过滤器: {filt_txt}\n"
                f"{f.rules_text}"
            )
        return "\n".join(parts)

    ids = list(factor_ids or [])
    parts[0] += f"因子组合: {', '.join(ids) or '(无)'}"
    for fid in ids:
        f = get_factor(fid)
        status = "生效" if f.implemented else "占位未实现"
        parts.append(f"\n----- {f.name}({f.id}) [{status}] -----\n{f.rules_text}")
    return "\n".join(parts)


def compose_rules_from_spec(spec: StrategySpec) -> str:
    return compose_rules(spec.name, bindings=spec.bindings(enabled_only=False))


def not_implemented_runner(strategy_id: str):
    def _run(cfg: Any = None, **kwargs: Any) -> None:
        raise NotImplementedError(
            f"{strategy_id} 尚未实现回测入口。"
            f"请在 strategy/strategies/{strategy_id}/__init__.py 绑定 run，"
            f"并配置 bindings.py 中的 factor_bindings。"
        )

    return _run


__all__ = [
    "bind_factor",
    "load_factors",
    "load_bindings",
    "compose_rules",
    "compose_rules_from_spec",
    "not_implemented_runner",
]
