# myquan 架构与技术栈报告

> 日期：2026-10-15
> 范围：仓库整体分层、盯盘运行时、技术栈与数据边界  
> 性质：工程说明；研究/纸面用途，非投资建议，不接券商实盘下单

---

## 1. 摘要

**myquan** 是一套以 [AKQuant](https://github.com/akfamily/akquant) 为回测内核的 A 股量化研究仓库，叠加：

- **策略/因子注册表**（可插拔 bindings）
- **纸面盯盘**（五槽、每日新增两只、多层止盈、实时行情）
- **Web 前端**（Nuxt 展示信号与账户）
- **微信出站推送**（OpenClaw，不走大模型）
- **MySQL权威状态**（行情最新快照 / 持仓 / 成交流水 / 交割明细 / 独立策略收益；JSON仅旧迁移输入或显式离线测试）

策略16当前实时顺序：优先接收行情 → 后台持久化最新快照 → 确认后分发计算信号/估值 → 版本化事务提交成交。分钟采集为首屏后独立研究备份，不参与实时执行。最新表不等同于完整逐笔归档；具体时间、价格与过期拒绝规则见 `QUOTE_DRIVEN_STRATEGY16.md`。

定位：**研究 + 纸面模拟**，不是券商交易系统。

---

## 2. 逻辑架构

### 2.1 策略分层（开闭原则）

```
因子层 (factors)              → 价位 / 信号 / 通用过滤
策略层 (bindings)             → 本策略挂哪些因子、参数、专属过滤器
决策层 (decision)             → MarketContext → Decision(buy|sell|hold)
执行层 (runner / backtest / 盯盘) → 回测、纸面成交、预警推送
```

| 层 | 职责 | 主要位置 |
|----|------|----------|
| 因子 | 选股、买卖价、止盈止损规则 | `strategy/factors/`、`strategy/pullback_wave_stop.py`、`strategy/open_break.py` |
| 策略绑定 | 组合因子与默认参数 | `strategy/strategies/strategy*/bindings.py` |
| 决策 | 统一买卖决策接口 | `strategy/strategies/*/decision.py` |
| 执行 | 回测产物、盯盘结算、推送 | `backtest/`、`holdingStocks/` |

### 2.2 系统拓扑

```
┌──────────────────────────────────────────────────────────────┐
│  watch-ui（Nuxt 3 · :3000）                                    │
│  持仓盯盘 / 策略 Tab / 板块轮动 / 交割单 / 策略·因子说明         │
└────────────────────────────▲─────────────────────────────────┘
                             │ HTTP /api/*  +  WebSocket /ws
┌────────────────────────────┴─────────────────────────────────┐
│  holdingStocks（Python · :8765）                               │
│  quote_feed → collect_rows → 四槽纸面买卖 → 快照/微信/交割账本  │
└───────────┬───────────────────────────────┬──────────────────┘
            │                               │
┌───────────▼──────────┐         ┌──────────▼──────────────────┐
│ strategy/            │         │ 数据源                       │
│ 因子·绑定·1m 止盈内核 │         │ 东财 SSE / 新浪 / akshare     │
└───────────┬──────────┘         │ 通达信 pytdx（板块）          │
            │                    └─────────────────────────────┘
┌───────────▼──────────┐
│ backtest/ + akquant  │  日线 / 1m 回测 → csv / json / report
└──────────────────────┘
```

### 2.3 当前生产默认（盯盘）

| 项 | 配置 |
|----|------|
| 策略 | **策略十六** |
| 选股宇宙 | **因子27** 核心龙头 ∪ **公共自选池**（天通/凯盛/东材/金安） |
| 买卖 | **因子26** 开盘频率买 + 多层止盈 |
| 账户预警 | **因子2**（回测不注资） |
| 因子22 | 默认关闭（研究对照） |
| 仓位 | 物理四槽，每槽约 25%；先平再买；10% 半仓止盈 |
| Paper 卖出 | **Unified Primary** + **Legacy Shadow**（`USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`） |

真源注册表：[`strategy/README.md`](../strategy/README.md) · 摘要：[`READ.md`](../READ.md)。

---

## 3. 目录与模块职责

| 路径 | 职责 |
|------|------|
| `strategy/` | 因子/策略注册、CLI、止盈内核、选股脚本 |
| `holdingStocks/` | 盯盘主程序、行情、账本、微信、交割 JSON |
| `holdingStocks/watch-ui/` | 盯盘 SPA（Nuxt） |
| `backtest/` | 回测入口与产物（含锁定配置如因子13B） |
| `sectors/` | 板块轮动（通达信概念活跃度等） |
| `docs/` | 专题文档（因子/策略/审计） |
| `data_cache/` | 日线等本地缓存（parquet 等） |
| `.cursor/skills/` | Agent 研究技能（旁路，非运行时必装） |

### 3.1 盯盘关键文件

| 文件 | 职责 |
|------|------|
| `index.py` | 盯盘主循环、HTTP/WS、纸面买卖、API |
| `watch_config.py` | 策略 ID、池、竞价窗口、四槽参数 |
| `quote_feed.py` | SSE / 新浪行情聚合 |
| `pullback_wave_stop.py`（strategy） | 因子26 多层止盈真源 |
| `wechat_notify.py` | OpenClaw 微信出站 |
| `trade_ledger.py` | 数据库交割单读模型 |
| `database_holdings.py` | Java/MySQL账户读写、版本校验 |
| `holdings_sync.py` | 历史local_json离线工具，不是生产同步入口 |
| 根目录 `start_project.py` | 一键管理Java、Python及可选Nuxt开发服务 |

---

## 4. 盯盘运行时数据流

```
行情（SSE 热池 + 新浪批量/叠加池）
    → collect_rows（过门、买点、因子26 1m 路径、开盘保护）
    → 纸面：apply_paper_slot_buy / apply_exit_fill
    → Java事务 → MySQL持仓、账户、成交流水与交割记录
    → publish_watch_snapshot → /api/snapshot + WS
    → 前端卡片 / 交割单页 /trades
    → 微信：扫描预警（交易日连续竞价）+ 成交即时推送；休市日不扫
```

**早盘窗口**

| 时刻 | 行为 |
|------|------|
| 9:15 | 状态重置；竞价参考；不写峰值/不结算 |
| 9:25 | 可算频率、挂单预览；不结算 |
| 9:30–11:30 / 13:00–15:00 | **交易日**连续竞价：触发买卖、结算、扫描预警 |
| 午休/收盘后/休市 | 保留展示；扫描预警停；休市日也不自动成交 |

**端口**

| 端口 | 进程 |
|------|------|
| `3306` | MySQL数据库 |
| `8080` | Java账户读写后台 |
| `8765` | Python 数据 API + WebSocket + 静态前端 |
| `3000` | 可选Nuxt开发服务 |
| OpenClaw Gateway（如 `18789`） | 微信通道 |

统一启动入口：根目录 `bash start.sh` 启动全部；`bash start.sh --service java|python|frontend` 只启动/替换指定服务，其余保持运行（实际命令三选一，不输入竖线）。详见根目录 [READ.md](../READ.md)。Python不再创建Nuxt子进程，也不强制回收未知端口。

---

## 5. 账本与同步

| 文件 | 含义 |
|------|------|
| MySQL账户及持仓表 | 生产持仓、现金、账户统计等，由Java事务更新 |
| MySQL成交及交割表 | 成交流水与订正记录，供交割读模型使用 |
| `holdings.json` / `trades.jsonl` / `trade_ledger.json` | 已迁入 MySQL 后删除的历史文件；`backend/logs/` 备份仍保留 |
| `app_documents.strategy_simulator_state` | 策略虚拟账本（单笔累计 / 策略收益），接口读写 |
| `app_documents.strategy_simulator_events` | 策略模拟成交事件 |
| `strategy_sim_voided_events` | 已作废的策略模拟事件 |
| `app_documents.watch_snapshot` | 盯盘展示快照，不是账本真源 |

跨机一致性依赖访问同一个Java后台/MySQL，不通过Git同步生产持仓。各设备的localhost数据库彼此独立；Git只同步代码。

---

## 6. 技术栈

### 6.1 后端 / 量化

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.x |
| 回测引擎 | requirements固定 **akquant==0.3.22**；本机已安装0.3.21的差异待对齐，启动器提示但不自动升级 |
| 行情/基本面拉取 | akshare、baostock、requests |
| 实时报价 | 东财 SSE、新浪 hq |
| 板块 | pytdx（通达信） |
| 数值 | pandas、numpy、pyarrow |
| 缠论等 | czsc |
| 回测图 | plotly |
| HTTP | 标准库 `ThreadingHTTPServer` + 自研 WS Hub |
| 推送 | OpenClaw + `@tencent-weixin/openclaw-weixin`（出站，不走 LLM） |

依赖清单：[`requirements.txt`](../requirements.txt)。同级 `../akquant/` 源码仅供研读，不自动进 `PYTHONPATH`。

### 6.2 前端

| 类别 | 技术 |
|------|------|
| 框架 | Nuxt 3、Vue 3、TypeScript |
| 状态 | Pinia |
| 样式 | Tailwind + 自研 `--ui-*` token |
| 图表 | ECharts |
| 联调 | Vite/Nitro 代理 `/api` → `:8765`；WS 直连 |

### 6.3 工程

| 类别 | 做法 |
|------|------|
| 版本 | Git；账本分支与代码分支分离 |
| 文档 | `READ.md` + `strategy/README.md` + `docs/` + `TODO.MD`；变更同步见 `.cursor/rules/docs-sync.mdc` |
| 持久化 | 无传统业务库；JSON/JSONL 纸面账本 |
| 测试 | `unittest`（盯盘规则、止盈路径等） |

---

## 7. AKQuant 回测数据流（对照）

```
akshare / panda DataFrame
  → normalize / load_bar_from_df
  → Bar → Strategy.on_bar → Execution → Statistics
  → BacktestResult（写入 backtest/ 产物）
```

盯盘 **不** 走 `get_decision_engine()` 热路径做全市场决策引擎挂载；纸面卖出统一 `paper_exit_decision` + 因子26 `eval_multi_tp_bar` / 1m path。

---

## 8. 边界与非目标

| 是 | 否 |
|----|----|
| 研究回测、纸面四槽、信号预警 | 券商报单 / 实盘持仓对账 |
| 本地 JSON 账本与交割展示 | 生产级数据库与清算 |
| 微信出站提醒 | 微信内 Agent 闲聊（会触发模型鉴权） |
| 文档与锁定配置可审计 | 收益承诺或投资建议 |

---

## 9. 相关文档

| 文档 | 说明 |
|------|------|
| [`READ.md`](../READ.md) | 总览、运行命令、因子/策略摘要 |
| [`strategy/README.md`](../strategy/README.md) | 注册表真源 |
| [`holdingStocks/README.md`](../holdingStocks/README.md) | 盯盘可靠性与窗口 |
| [`holdingStocks/weChat接入.md`](../holdingStocks/weChat接入.md) | 微信通道 |
| [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md) | 策略十六 / 因子26 算法审核 |
| [`TODO.MD`](../TODO.MD) | 任务与锁定事故表 |

---

*报告生成日期：2026-09-17。架构若有变更，请同步更新本文与 READ.md。*
