"""可插拔因子 / 策略规格（Protocol + 不可变描述）。

设计要点：
  · Factor：可复用信号/过滤/价位规则；多个策略可共用同一因子
  · Strategy：编排一个或多个因子，并通过 FactorBinding 为「本策略下的该因子」
    单独设置参数与过滤器（同因子在不同策略条件可不同）
  · 开闭原则：新增因子/策略只需新文件 + register_*，不改旧模块
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class FactorSpec:
    """因子规格（全局定义，不含策略侧参数）。"""

    id: str
    name: str
    description: str = ""
    rules_text: str = ""
    implemented: bool = True
    levels: Callable[..., dict[str, Any]] | None = None
    filters_ok: Callable[..., bool] | None = None
    signal: Callable[..., dict[str, Any]] | None = None
    replay: Callable[..., dict[str, Any]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FactorBinding:
    """策略侧因子绑定：同一因子可在不同策略下用不同参数/过滤器。

    例：
      策略一：factor1 + params={{entry_pct:0.025}} + filter=阴/小阳
      策略二：factor1 + params={{entry_pct:0.03}}  + filter=仅阴线
    """

    factor_id: str
    # 传给 levels / filters_ok / signal 的策略专属参数（覆盖因子默认）
    params: dict[str, Any] = field(default_factory=dict)
    # 策略专属附加过滤：(*args, **merged_params) -> bool；True 才允许该因子生效
    filter: Callable[..., bool] | None = None
    # 过滤器说明（写入规则文本）
    filter_desc: str = ""
    # 在本策略中的角色：entry / exit / both / custom
    role: str = "both"
    # 本策略内别名（可选）
    label: str = ""
    enabled: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    def display_name(self) -> str:
        return self.label or self.factor_id

    def merged_params(self, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
        out = dict(base or {})
        out.update(self.params)
        return out

    def passes_filter(self, *args: Any, **kwargs: Any) -> bool:
        """先合并 params，再跑策略侧 filter；无 filter 则默认通过。"""
        if not self.enabled:
            return False
        merged = self.merged_params(kwargs)
        if self.filter is None:
            return True
        return bool(self.filter(*args, **merged))


def bind_factor(
    factor_id: str,
    *,
    params: Mapping[str, Any] | None = None,
    filter: Callable[..., bool] | None = None,
    filter_desc: str = "",
    role: str = "both",
    label: str = "",
    enabled: bool = True,
    **param_kwargs: Any,
) -> FactorBinding:
    """快捷构造绑定：params 与 **param_kwargs 合并。"""
    p = dict(params or {})
    p.update(param_kwargs)
    return FactorBinding(
        factor_id=str(factor_id),
        params=p,
        filter=filter,
        filter_desc=filter_desc,
        role=role,
        label=label,
        enabled=enabled,
    )


@dataclass(frozen=True)
class StrategySpec:
    """策略规格：因子绑定列表（含每策略过滤器/参数）。"""

    id: str
    name: str
    description: str = ""
    # 优先使用 bindings；若为空则回退 factor_ids（无额外过滤）
    factor_bindings: tuple[FactorBinding, ...] = ()
    factor_ids: tuple[str, ...] = ()
    run: Callable[..., Any] | None = None
    default_config: Any = None
    strategy_cls: type | None = None
    print_rules: Callable[[], str] | None = None
    # 决策层工厂：StrategySpec -> DecisionEngine（只决策、不下单）
    decision_factory: Callable[..., Any] | None = None
    aliases: tuple[str, ...] = ()
    implemented: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # frozen dataclass：用 object.__setattr__ 规范化
        if self.factor_bindings:
            ids = tuple(b.factor_id for b in self.factor_bindings if b.enabled)
            object.__setattr__(self, "factor_ids", ids)
        elif self.factor_ids:
            binds = tuple(FactorBinding(factor_id=fid) for fid in self.factor_ids)
            object.__setattr__(self, "factor_bindings", binds)

    def factor_id_list(self) -> list[str]:
        return list(self.factor_ids)

    def bindings(self, *, enabled_only: bool = True) -> list[FactorBinding]:
        rows = list(self.factor_bindings)
        if enabled_only:
            rows = [b for b in rows if b.enabled]
        return rows

    def binding_for(self, factor_id: str) -> FactorBinding | None:
        for b in self.factor_bindings:
            if b.factor_id == factor_id and b.enabled:
                return b
        return None


def ensure_factor_ids(factor_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(x) for x in factor_ids)
