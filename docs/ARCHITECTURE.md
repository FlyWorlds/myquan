# myquan 架构与技术栈报告

> 日期：2026-09-17  
> 范围：仓库整体分层、盯盘运行时、技术栈与数据边界  
> 性质：工程说明；研究/纸面用途，非投资建议，不接券商实盘下单

---

## 1. 摘要

**myquan** 是一套以 [AKQuant](https://github.com/akfamily/akquant) 为回测内核的 A 股量化研究仓库，叠加：

- **策略/因子注册表**（可插拔 bindings）
- **纸面盯盘**（四槽、多层止盈、实时行情）
- **Web 前端**（Nuxt 展示信号与账户）
- **微信出站推送**（OpenClaw，不走大模型）
- **JSON 账本**（持仓 / 成交流水 / 交割明细）

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
| `trade_ledger.py` | 交割单 JSON 账本 |
| `holdings_sync.py` | Win/Mac 账本推拉 `holdings-ledger` |
| `start_watch.py` | 一键启动 API + Nuxt |

---

## 4. 盯盘运行时数据流

```
行情（SSE 热池 + 新浪批量/叠加池）
    → collect_rows（过门、买点、因子26 1m 路径、开盘保护）
    → 纸面：apply_paper_slot_buy / apply_exit_fill
    → 账本：holdings.json · trades.jsonl · trade_ledger.json
    → publish_watch_snapshot → /api/snapshot + WS
    → 前端卡片 / 交割单页 /trades
    → 微信：扫描预警（连续竞价）+ 成交即时推送
```

**早盘窗口**

| 时刻 | 行为 |
|------|------|
| 9:15 | 状态重置；竞价参考；不写峰值/不结算 |
| 9:25 | 可算频率、挂单预览；不结算 |
| 9:30–11:30 / 13:00–15:00 | 连续竞价：触发买卖、结算、扫描预警 |
| 午休/收盘后 | 保留展示；扫描预警停；成交即时推仍可用 |

**端口**

| 端口 | 进程 |
|------|------|
| `8765` | Python 数据 API + WebSocket |
| `3000` | Nuxt 盯盘页 |
| OpenClaw Gateway（如 `18789`） | 微信通道 |

启动：`cd holdingStocks && python start_watch.py`

---

## 5. 账本与同步

| 文件 | 含义 |
|------|------|
| `holdings.json` | 持仓、现金、当日已实现、峰值等 |
| `trades.jsonl` | 成交流水（追加） |
| `trade_ledger.json` | 交割明细（结构化，供 `/trades`） |
| `holdings_watch.json` | **本机展示缓存**，非跨机真源 |

跨机：独立 Git 分支 `origin/holdings-ledger`（`holdings-push` / `holdings-pull`）。代码走 `main`，账本不进 main（gitignore）。

---

## 6. 技术栈

### 6.1 后端 / 量化

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.x |
| 回测引擎 | **akquant==0.3.21**（Rust 内核 + Python 策略层） |
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
