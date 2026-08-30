# 任务清单（myquan）

> 与 [`READ.md`](READ.md) 总览、[`docs/STRATEGY.md`](docs/STRATEGY.md) 策略说明同步维护。  
> 文档变更规则：`.cursor/rules/docs-sync.mdc`  
> 策略/因子注册表见 [`strategy/README.md`](strategy/README.md)、[`READ.md`](READ.md) § 策略与因子注册表（**不在本文重复**）。

**最后整理**：2026-08-30

---

## 已完成 ✅

### P0 · 基础设施
- [x] WebSocket 实时行情（东财 SSE + 新浪兜底 + 本地 WS）
- [x] 策略信号 → 飞书 / 微信预警（OpenClaw）
- [x] P0.5 审查：`available=0`、当日盈亏盯市、标的池收敛、`Strategy1Decision` T+1、纸面仓等

### P1 · 选股与研究
- [x] 策略六：因子3 选票 + 因子1 止损（`backtest/compare_f3_select_f1_stop.py`）
- [x] **因子13 · 熊市盾牌 thr\* Top3**（WF + 个股阈值 + 防过拟合调参）
  - 锁定：`backtest/factor13_bear_shield/LOCKED.json`
  - 说明：[`docs/FACTOR13.md`](docs/FACTOR13.md)
  - 复现：`python strategy/run_factor13_bear_shield_wf.py`

### P2
- [x] 策略一挂载因子2（回撤阶梯预警，回测不注资）
- [x] 因子3 动量、因子5 Serenity、因子6/7 ETF 轮动等（见 `strategy/README.md`）

### 盯盘 · holdingStocks（2026-08-30）
- [x] 早盘节点 9:15/9:20/9:25/9:30 + 策略1-援军战法 Tab（阈值/过门）
- [x] `watch` 冷启动优化：仅新浪实时批量，不串行拉历史分钟 K
- [x] 股票名/代码跳转百度财经外链
- [x] 持仓置顶：凯盛 500、珠峰 700；天通已卖仍置顶跟踪
- [x] Nuxt watch-ui：策略/因子说明页、`--ui-dev` 热更新、WS 全局插件、API 端口注入

### 文档同步（2026-08-30）
- [x] **READ.md** 增加 § 策略与因子注册表（因子/策略摘要表）
- [x] **docs-sync.mdc** 策略/因子变更同步 READ + strategy/README

---

## 锁定 🔒（暂停改参）

| 项 | 说明 |
|----|------|
| **因子13 熊盾 Top3** | 2026 名单：东材 / 珠峰 / 雷赛；解锁前勿调门槛/TopK/thr 网格 |
| 入口 | `run_factor13_bear_shield_wf.py` |

---

## 进行中 / 待办

### P0（剩余）
- [ ] **持仓手工录入进数据库**：持仓、盈亏、总金额、统计（非代码录入）

### P1
- [ ] 盯盘 `collect_rows` 改为直接调用 Decision 引擎（规则已对齐，未替换旁路）
- [ ] 因子13 与盯盘合格池对接（锁定解除后再评估）
- [ ] 样本外稳定后，策略六/因子13 动态池接入日常盯盘

### P2
- [ ] 独立新因子：3K 反转、缠论结构深化
- [ ] 因子13 质量带（A 线）与熊盾（B 线）统一注册表文案

### P3
- [ ] 多因子组合回测、相关性检验
- [ ] 分散单一策略回撤（因子1+2 / 3+1 之外）

---

## 文档维护（随改随更）

**规则真源**：`.cursor/rules/docs-sync.mdc` · `strategy/README.md` § 文档维护规则

**新增/删因子或策略**：`strategy/README.md` → `docs/` → **READ.md**（摘要表）；**TODO.MD 只更新任务/锁定/已完成**，不写注册表。

| 文件 | 用途 |
|------|------|
| `strategy/README.md` | 因子/策略注册表（完整真源） |
| `READ.md` | 项目总览 + 因子/策略摘要表 |
| `docs/STRATEGY.md` | 策略专题 |
| `docs/FACTOR13.md` | 因子13 双轨 + 锁定 |
| `TODO.MD` | **本清单**（任务 / 锁定 / 里程碑） |
| `.cursor/rules/docs-sync.mdc` | Cursor Agent 文档同步规则 |
