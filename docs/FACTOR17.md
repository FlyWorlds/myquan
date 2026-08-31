# 因子17 · 缠论笔盈亏比

> 研究评估因子，不构成投资建议。不产生独立买卖指令。

原 **策略七** 研究入口已归入因子池（分类：**缠论**）。CLI `run_strategy7()` 仍可用。

## 做什么

用 CZSC **日线笔** 切段，把 **因子1**（开盘突破）费用后闭环交易按「买入所在笔」归因：

- 卖点落在另一笔时，卖价差价平移记入买入笔
- 输出盈亏比、向上笔让利、向下笔防守

## 和因子8 / 策略二的区别

| 条目 | 角色 |
|------|------|
| 因子8 | 缠论结构买卖点（信号） |
| 策略二 | 用因子8 做完整交易 |
| **因子17** | 用因子1 模拟交易 + 用笔做归因评估 |

## 挂到新策略

因子已注册为 `factor17`，任意策略的 `bindings.py` 可写：

```python
from strategy.core.protocols import bind_factor

FACTOR_BINDINGS = (
    bind_factor("factor17", label="缠论笔盈亏比", role="custom"),
    # 需要买卖时再叠因子1 / 因子8
)
```

当前 Web 策略栏不展示旧策略七；`run_strategy7()` 仅作 CLI 兼容。

真源：`strategy/bi_pl_ratio.py` · 注册：`strategy/factors/factor17.py`
