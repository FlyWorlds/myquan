# 因子14 · 题材共振（theme_lu_count）

> 研究用途，不构成投资建议。  
> 注册表见 [`strategy/README.md`](../strategy/README.md)；挂载 **策略八·题材联动**。

**最后更新**：2026-08-30

---

## 定义

- **数据源**：通达信概念成分（离线 `tdx_members_index.json`）
- **统计口径**：**当日**与本股共享至少一个概念、且**当日收盘涨停**的同伴数量 → `theme_lu_count`
- **入池门槛**：`theme_lu_count ≥ 3`（同题材至少 3 只当日涨停，视为题材共振）
- **联动候选**：未当日涨停但 `theme_lu_count ≥ 3` → 题材内联动票（策略八默认 `pool=linkage`，排除当日涨停龙头）

## 与策略八的关系

| 步骤 | 说明 |
|------|------|
| 定题材 | **当日**收盘涨停池 → 按概念聚合 |
| 选股 | 因子14 过滤 `theme_lu ≥ 3`；默认取联动补涨票 |
| 执行 | **当日**因子1 ±阈值突破买入（非次日晋级买） |
| 情绪 | T-1 连板梯度门槛（连板≥2、最高板 2～5），与策略三同源 |

因子15（晋级低开带）为可选过滤，策略八**默认关闭**（`apply_gap_filter=false`）。

## 真源

- `strategy/factors/factor14.py`
- `strategy/strategies/strategy8/theme_linkage.py`
- 回测：`backtest/strategy8_theme_linkage/run.py`

## 回测参考（2025-01-02 → 2026-08-11，linkage 池，因子15 关）

| 阈值 | 总收益 | 最大回撤 | 笔数 |
|------|--------|----------|------|
| ±2.5% | +6.1% | 4.4% | 179 |
| ±3.0% | +9.1% | 2.9% | 184 |

详见 [`backtest/strategy8_theme_linkage/REPORT.md`](../backtest/strategy8_theme_linkage/REPORT.md)。
