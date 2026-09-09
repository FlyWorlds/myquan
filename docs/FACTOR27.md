# 因子27 · 核心龙头（滚动近 3 个月冻结）

> 研究用途，不构成投资建议。  
> 注册表见 [`strategy/README.md`](../strategy/README.md)；挂载 **策略十六·核心龙头**。

**最后更新**：2026-09-09

---

## 定义

- **数据源**：通达信概念现价成交额（活跃度）+ 概念成分实时行情（`sectors/tdx.py`）
- **偏高概念**：截面成交额 **≥ 中位数**，最多扫成交额 **Top25**
- **概念内龙头**：过滤后按涨跌幅、成交额取前 **3**（每概念至多 3 只）
- **池规模**：去重后约 **20** 只（不够则继续加概念，满 20 停）
- **过滤**：非创业板、非科创板、非北交所、非 ST、现价 **< 100**
- **周期**：滚动 **近 3 个月**（选股日往前 3 个月～当日；名单用到选股日后 3 个月，非自然季度 Q1/Q2/Q3）；产物 `backtest/strategy16_core_leader/picks_quarter.json`
- **盘前**：概念成交额/个股涨跌幅可能为空，则回退最近一轮板块缓存；开盘后请重跑 CLI 按涨跌幅取龙头

## 与策略十六的关系

| 步骤 | 说明 |
|------|------|
| 选股 | 因子27 近3个月池（本因子） |
| 买/卖 | **同策略一**：因子26 多层止盈 + 因子2 回撤预警 + 因子22 收盘动量再买 |
| 盯盘 | 持仓盯盘 **策略16** Tab；不占策略一三槽、不进持仓 Tab 预警（除非已登记持仓） |

## 真源

- `strategy/core_leader_universe.py`
- `strategy/factors/factor27.py`
- CLI：`python strategy/run_core_leader_pool.py`
- 近 7 日 1m 回测（先拟合 2026 至今开盘阈值）：`PYTHONPATH=. python backtest/strategy1_pool_1m/run.py --pool strategy16 --days 7 --fit-thr`
- 只拟合阈值：`python backtest/strategy16_core_leader/fit_thr.py` → `thr_2026.json`
