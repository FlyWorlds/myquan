# myquan 架构分析报告（第 23 步 · 只读扫描）

> **日期**：2026-09-17  
> **性质**：重构前依赖与耦合扫描；**本轮未改任何业务代码**  
> **对照方案**：Nuxt + Python + AKQUANT 分层解耦（Strategy → Signal → Execution → Broker Adapter）  
> **仓库定位真源**：[`ARCHITECTURE.md`](ARCHITECTURE.md) — 研究回测 + 纸面盯盘，**不接券商实盘下单**

---

## 0. 一句话结论

本仓库**已有**清晰的「因子绑定 + `Decision` 协议 + 手工注册表 + akquant 回测」骨架，但**生产盯盘是另一套并行执行栈**。  
与目标架构差距最大的不是「缺功能」，而是：

1. **`holdingStocks/index.py` 巨石**（约 9400+ 行）把行情、信号、纸面成交、HTTP/WS、账本写在同一文件；
2. **盯盘热路径故意绕过 `get_decision_engine()`**，与回测 Decision 双轨；
3. **`strategy` ↔ `holdingStocks` 双向 import**；
4. **无**统一 `TradingSignal` / `Broker` Protocol / FastAPI Application Service / Event Bus。

---

## 1. 当前目录结构（运行时相关）

忽略：`.cursor/skills/`、`node_modules/`、`__pycache__/`、大量 `backtest/` 产物细节。

```text
myquan/
├── strategy/                 # 因子 / 策略注册 / 回测内核（akquant 边界）
│   ├── core/                 # MarketContext · Decision · 注册表 · Protocol
│   ├── factors/              # factor1..28 + cf1
│   ├── strategies/           # strategyN/{bindings,decision,__init__}
│   ├── chan/                 # 缠论研究
│   ├── base.py / runner.py / backtest.py / registry.py
│   ├── open_break.py         # 因子1 规则
│   ├── pullback_wave_stop.py # 因子26 止盈真源
│   └── akq_math.py / data.py / minute.py / costs.py / config.py
├── holdingStocks/            # 纸面盯盘运行时 + JSON 账本 + API
│   ├── index.py              # ★ 主循环 / 买卖 / HTTP / WS（巨石）
│   ├── watch_config.py / quote_feed.py / watch_snapshot.py
│   ├── trade_ledger.py / holdings_sync.py / wechat_notify.py
│   ├── *_watch.py            # 各策略叠加选股载荷
│   └── watch-ui/             # Nuxt 3（:3000）
├── backtest/                 # 回测 CLI + 产物目录（与代码混树）
├── sectors/                  # 板块轮动（通达信等）
├── data_cache/               # 日线 parquet 等
├── docs/                     # 专题文档
├── tests/ + 根目录 test_*.py
├── _misc/                    # akquant demo
└── READ.md / TODO.MD / requirements.txt
```

**不存在**：`backend/`、`ports/`、`adapters/akquant/`、`application/`、FastAPI `main.py`。

---

## 2. 逻辑拓扑（现状）

```text
                    watch-ui (Nuxt :3000)
                           │
              HTTP /api/*  +  WS /ws（直连 :8765）
                           │
                           ▼
              holdingStocks/index.py  ←── 巨石
                │  quote_feed / 纸面买卖 / 账本 / Handler
                │
        ┌───────┴────────┐
        ▼                ▼
   strategy/*       东财 SSE / 新浪 / akshare
   （规则函数、       （行情，非 akquant）
    bindings 只读）
        │
        ▼
   strategy/base.py → aq.run_backtest  ←── 仅回测路径
        │
        ▼
     backtest/ 产物
```

与目标方案对照：

| 目标层 | 现状对应 | 缺口 |
|--------|----------|------|
| API (FastAPI) | `ThreadingHTTPServer` + 手写 `_Handler` | 无 DI、无 OpenAPI、路由嵌在巨石 |
| Application Service | 无；API 直接读注册表 / 推快照 | 缺 |
| Strategy Engine | `DecisionEngine` + bindings（回测侧） | 盯盘**不用**引擎 |
| Signal Contract | `Decision` dataclass | 无 `TradingSignal`；盯盘用中文键 dict |
| Execution Engine | akquant 内置 / `apply_*` 纸面函数 | 双轨、无统一引擎 |
| Broker Protocol | **无** | 纸面 JSON ≠ Broker |
| AKQUANT Adapter | `strategy/base.py` 等直接 `import akquant` | 未隔离到 adapters/ |
| Event Bus | **无**；主循环 + 整包 Snapshot WS | 无领域事件 |

---

## 3. Strategy 相关文件

### 3.1 核心

| 路径 | 职责 |
|------|------|
| `strategy/core/context.py` | `MarketContext`、`Decision`（buy/sell/hold） |
| `strategy/core/decision.py` | `DecisionEngine` Protocol、`BaseDecisionEngine`、`get_decision_engine()` |
| `strategy/core/protocols.py` | `FactorSpec` / `FactorBinding` / `StrategySpec` |
| `strategy/core/factor_registry.py` | `FACTOR_REGISTRY` |
| `strategy/core/strategy_registry.py` | `STRATEGY_REGISTRY`、`register_strategy` |
| `strategy/registry.py` | **兼容层**（`StrategyEntry` / `get_strategy`）代理到 core |

### 3.2 策略包模式

每个已注册策略：

```text
strategy/strategies/strategyN/
  ├── bindings.py   # FACTOR_BINDINGS
  ├── decision.py   # BaseDecisionEngine 子类
  └── __init__.py   # register_strategy(StrategySpec(...))
```

**加载方式**：`strategy/strategies/__init__.py` **显式 import** strategy1…17（**非**目录自动发现）。

目录存在但**未**在 `__init__.py` 注册：`strategy11/`、`strategy13/`、`_unreg_s*`、`_legacy_*`。

### 3.3 新增策略当前成本

| 步骤 | 是否手工 |
|------|----------|
| 新建 `strategies/strategyN/` | 是 |
| `__init__.py` 内 `register_strategy` | 是 |
| **`strategies/__init__.py` 加一行 import** | **必须手工** |
| 新因子：`factors/factorX.py` + `factors/__init__.py` | 是 |
| 文档：`strategy/README.md` / `READ.md` / `docs/` | 是（仓库规则强制） |
| 盯盘：`watch_config` / `*_watch.py` / **`index.py` 分支** | 常需手工 |

→ 与目标「只加一个策略目录」差距：**聚合 import + 盯盘双写**。

---

## 4. Signal / Decision 相关

### 4.1 已有 Contract：`Decision`

位置：`strategy/core/context.py`

- `action`: `"buy" | "sell" | "hold"`
- `reason` / `price` / `size_mode` / `size_value` / `factor_id` / `meta`

**全库无** `TradingSignal` / `SignalAction` / `ExecutionEngine` / `Broker` / `EventBus`（Grep 0 命中）。

### 4.2 实际「信号」形态（多套并存）

| 层 | 形态 |
|----|------|
| 决策层 | `Decision` |
| 因子层 | `levels` / `signal` / `replay` → `dict` |
| 盯盘行 | 中文键：「买点」「过门OK」「预警」等 |
| 纸面卖出 | `paper_exit_decision(...) -> dict`（hit / fill_px / kind…） |
| 触买文案 | `watch_buy_signal.py` 常量 |

### 4.3 关键分叉（P0）

`holdingStocks/index.py` 文首（L13–15）自承：

> `collect_rows()` **不**调用 `get_decision_engine()`；registry/bindings 供回测。改 bindings 后须同步本文件 FACTOR_ID 分支。

数据流：

```text
quote_feed
  → collect_rows()          # 绕过 DecisionEngine
  → watch_buy_signal
  → apply_paper_slot_buy / paper_exit_decision / apply_exit_fill
  → holdings.json / trades.jsonl / trade_ledger.json
  → publish_watch_snapshot → /api/snapshot + WS
```

---

## 5. Execution 相关

### 5.1 回测执行

```text
backtest/*.py / strategy/run_*.py
  → strategy.runner / strategy.base.run_akquant_backtest
  → aq.run_backtest(...)
  → OpenBreak3Strategy / MomentumStrategy(Strategy).on_bar
      → order_target_percent / sell（akquant 内置撮合）
```

关键文件：`strategy/base.py`、`runner.py`、`backtest.py`、`momentum_strategy.py`。

### 5.2 盯盘纸面执行（同文件）

| 函数 | 约略行号 | 作用 |
|------|----------|------|
| `apply_paper_slot_buy` | ~3612 | 四槽买入 |
| `apply_exit_fill` | ~4172 | 平仓/半仓 |
| `paper_exit_decision` | ~4750 | 卖出唯一口径 dict |
| `collect_rows` | ~5949 | 行情→信号行 |
| `cmd_buy` / `cmd_sell` | ~8664+ | CLI 手工记账 |

**无**独立 Execution Engine；**不接券商**。

---

## 6. AKQUANT 直接依赖

### 6.1 直接 `import akquant` / `from akquant`

| 文件 | 用法 |
|------|------|
| `strategy/base.py` | `aq.run_backtest`；`Strategy` / `BacktestResult` / `CurrentClose`；`akquant.plot` |
| `strategy/runner.py` | `Strategy` / `CurrentClose` / `NextOpen` / `BacktestResult` |
| `strategy/backtest.py` | `OpenBreak3Strategy(Strategy)` + 下单 API |
| `strategy/momentum_strategy.py` | `MomentumStrategy(Strategy)` |
| `strategy/akq_math.py` | `vec_returns` / `vec_log_returns` / `vec_rolling_std`（数学原语） |
| `strategy/test_akq_math.py` | 单测 |
| `_misc/demo.py` / `_misc/quan.py` | 示例 |

### 6.2 间接依赖

| 区域 | 方式 |
|------|------|
| `holdingStocks/` | `from strategy.akq_math import ...`（涨跌幅/盯市）；**不** `run_backtest` |
| `backtest/` | 普遍 `from strategy.*`；**无**直接 `import akquant` |
| `sectors/` | 不依赖 akquant |

### 6.3 与方案目标对照

目标：绝大多数 AKQUANT import 仅在 `adapters/akquant/`。  
现状：**业务回测骨架直接依赖**；数学原语经 `akq_math` 渗入盯盘。

---

## 7. API / Web 层

| 项 | 现状 |
|----|------|
| 框架 | **非 FastAPI**；`http.server.ThreadingHTTPServer` |
| 端口 | Python `:8765`；Nuxt `:3000` |
| 路由 | `/api/snapshot`、`/api/strategies`、`/api/factors`、`/api/trades`、`/api/sectors/*`、`/ws` |
| 写路径 | HTTP 以 GET 为主；账本写入在主循环 / CLI |
| 策略执行 | API **不**调用 `decide()`；推送已算好的快照 |

前端：`watch-ui/nuxt.config.ts` 代理 `/api` → `:8765`；WS 由 composable **直连** `ws://host:8765/ws`。

---

## 8. 跨模块 Import 图（高耦合）

### 8.1 holdingStocks → strategy（强）

`index.py` 直接大量 import：

- `strategy.open_break`（因子1 常量/过滤器/levels/signal）
- `strategy.pullback_wave_stop`（因子26 全套）
- `strategy.akq_math` / `minute` / `data` / `close_momentum`
- `strategy.get_strategy_bindings`、`core.*_registry`（说明页）

其它：`watch_config.py`、`quote_feed.py`、`factor2_watch.py`、`strategy3/8/15_watch.py` 等。

### 8.2 strategy → holdingStocks（反向 · 危险）

| 文件 | import |
|------|--------|
| `strategy/near_high_hold.py` | `holdingStocks.watch_config.limit_up_pct_of` |
| `strategy/cf1_liquidity_gated_reversal.py` | 同上 |
| `strategy/strategies/strategy4/portfolio.py` | `WATCHLIST` / `limit_down_pct_of` / `sina_of` |
| `strategy4/run_*.py`、`strategy1/optimize_tests/*` | `watch_config` |

→ **架构环**：研究包依赖盯盘配置。

### 8.3 backtest → strategy

`backtest/` 下 **数十** 脚本 import `strategy.runner` / `open_break` / `pullback_wave_stop` 等；产物与入口同树。

### 8.4 Nuxt → Python

仅 HTTP/WS；不 import Python class。契约靠手写 TS（`types/snapshot.ts`）与 `watch_snapshot.py` 对齐。

---

## 9. 循环依赖迹象

| 类型 | 结论 |
|------|------|
| `strategy.core` 内部硬环 | 未见明显 A↔B 死环 |
| 胖 `__init__` 桶装 | `from strategy import X` 易拉起全部插件 |
| **holdingStocks ↔ strategy** | **双向依赖已成立**（架构环，非必然 import 死锁） |

---

## 10. 重复 Model / 重复业务逻辑

### 10.1 模型

| 概念 | 多处定义 |
|------|----------|
| 持仓 | `holdings.json` dict；前端 `HoldingRow`；无统一 Python dataclass |
| 成交/订单 | `trades.jsonl`；`trade_ledger.json`；akquant 成交；**无共享 Order** |
| Bar | akquant bar；`MarketContext` OHLC；分钟 DataFrame |
| 决策 | `Decision` vs `paper_exit_decision` dict vs 行上预警字符串 |

### 10.2 因子26 多路径编排（P0）

| 路径 | 实现 |
|------|------|
| 规则内核 | `pullback_wave_stop.eval_multi_tp_bar` / `simulate_factor26_day_1m` |
| DecisionEngine | `_factor26_decision.Factor26Decision` |
| 盯盘 | `paper_exit_decision` + `collect_rows`（**不**走引擎） |
| 日线 akquant | `OpenBreak3Strategy`（部分逻辑内联） |
| 1m 回测 | `backtest/strategy1_pool_1m/run.py` 直接调内核 |

**同源函数、多套编排** → bindings 变更易漂移（作者已注释警告）。

---

## 11. 高耦合区域排序

| 优先级 | 区域 | 为何危险 |
|--------|------|----------|
| **P0** | `holdingStocks/index.py` 巨石 | API+执行+信号+账本一体；改一处易牵全身 |
| **P0** | 盯盘绕过 `DecisionEngine` | 与回测双轨；改策略规则需双处同步 |
| **P0** | 因子26 多路径编排 | 业务规则变化传播面大 |
| **P1** | `strategy` → `holdingStocks.watch_config` | 反向依赖；阻碍 Strategy 独立测试/迁移 |
| **P1** | akquant 渗入 `base/runner/backtest` + `akq_math` 渗入盯盘 | 未 Adapter 化 |
| **P1** | 策略/因子手工 import 列表 | 新增策略必改核心聚合文件 |
| **P2** | `*_watch.py` 绑具体 strategyN | 可接受，但增策略要增叠加模块 |
| **P2** | Nuxt TS 与 Python 快照手写对齐 | 无 codegen，契约易漂 |
| **P2** | `backtest/` 代码与产物混树 | 维护噪音 |

---

## 12. 文件迁移 Mapping（建议 · 尚未执行）

> 渐进式；**不要一次性搬迁**。标记：`保留` / `可迁` / `勿动` / `新建`。

| 现状 | 目标（对照方案） | 标记 |
|------|------------------|------|
| `strategy/core/*` | `domain/strategy/` 或保持 `strategy/core` | **可迁**（优先稳定 API） |
| `strategy/factors/*` | `strategies` 旁或 `domain/factors` | **可迁** |
| `strategy/strategies/*` | `strategies/` 插件目录 | **可迁** |
| `strategy/registry.py` | 合并进 core 或兼容层暂留 | **可迁** |
| `open_break.py` / `pullback_wave_stop.py` | `domain/rules/` | **可迁**（勿拆散因子26 真源） |
| `base.py` `runner.py` `backtest.py` `momentum_strategy.py` | `adapters/akquant/` | **可迁**（最高优先级隔离） |
| `akq_math.py` | `adapters/akquant/math.py` 或 `shared/math` | **可迁** |
| `holdingStocks/index.py` | 拆为 `api/` + `execution/paper/` + `app/watch_loop.py` | **可迁（优先拆）** |
| `quote_feed.py` | `adapters/market/` 或 `infrastructure/marketdata` | **可迁** |
| `trade_ledger.py` `holdings_sync.py` | `adapters/ledger/` | **可迁** |
| `watch_config.py` | `infrastructure/config/`；涨跌停工具抽到 **domain** | **可迁（先解耦反向依赖）** |
| `watch_snapshot.py` `watch_buy_signal.py` | `api/schemas` + `domain/signal` | **可迁** |
| `*_watch.py` | `application/overlays/` | **可迁** |
| `watch-ui/` | 保持或改名 `frontend/` | **保留原位** |
| `sectors/` | 保持或 `adapters/sectors` | **可迁** |
| `backtest/*.py` 入口 | `scripts/backtest/` 或 `research/` | **可迁** |
| `backtest/**` 产物 | `artifacts/` / gitignore | **勿动逻辑；产物外置** |
| `data_cache/` | 保持 | **勿动** |
| `docs/` `READ.md` `strategy/README.md` | 保持 | **勿动**（文档真源） |
| — | `ports/broker.py` `ports/market.py` `ports/clock.py` | **新建** |
| — | `adapters/akquant/*` `adapters/simulation/*` | **新建** |
| — | `application/*_service.py` | **新建** |
| — | 统一 `TradingSignal` / `Order` / `Position` / `Bar` | **新建**（可从 `Decision` 演进） |
| — | FastAPI / Event Bus | **新建**（按需；勿过度设计） |

---

## 13. 与目标验收场景的现状差距

| 场景 | 目标 | 现状 |
|------|------|------|
| A 新增策略 | 只加目录 | 需改 `__init__.py` import + 常改盯盘 |
| B 改 AKQUANT | 只改 Adapter | 改 `base/runner/backtest` 等 |
| C 新 Broker | 只加 Adapter | **无 Broker 抽象**；仅有纸面+akquant |
| D 回测/实盘共用 Strategy | 同一 Strategy | Decision 与盯盘双轨；akquant Strategy 又是第三套 |
| E 改 Nuxt API | 不影响 Strategy | API 已相对外置，但快照字段与盯盘逻辑耦合 |
| F 单测 Strategy | 无 Nuxt/API/AKQUANT | Decision 可测；盯盘规则测常拉 `index`/`pullback` |

---

## 14. 建议的下一阶段顺序（仍不改代码，供人工拍板）

与方案第 24–29 步对齐，结合本仓库实情：

1. **确认边界**：继续「研究+纸面」还是要上真 Broker？（影响是否引入 Broker Protocol）
2. **Contract 先行**：以现有 `Decision` 为基，定义是否升级为 `TradingSignal`；统一 `Bar` / `Position` 纸面模型
3. **打断反向依赖**：把 `limit_up_pct_of` 等从 `watch_config` 抽到 `strategy`/`domain` 工具模块
4. **AKQUANT Adapter 化**：把 `base.py`/`runner.py` 的 `import akquant` 收敛
5. **盯盘接入 DecisionEngine 或显式「WatchAdapter」**：消除双写（最大业务风险点，须逐步、对照测试）
6. **拆分 `index.py`**：API / 纸面执行 / 主循环三分，再谈 FastAPI
7. **策略自动发现**：替换 `strategies/__init__.py` 手工列表
8. **最后**再考虑 Event Bus / FastAPI / 删除旧代码

---

## 15. 证据速查表

| 符号 / 现象 | 路径 |
|-------------|------|
| `MarketContext` / `Decision` | `strategy/core/context.py` |
| `register_strategy` | `strategy/core/strategy_registry.py` |
| 手工加载列表 | `strategy/strategies/__init__.py` L27–39 |
| akquant 回测入口 | `strategy/base.py` → `aq.run_backtest` |
| 盯盘绕过引擎 | `holdingStocks/index.py` L13–15 |
| 纸面买卖 | `apply_paper_slot_buy` / `paper_exit_decision` / `apply_exit_fill` |
| HTTP/WS | `index.py` `ThreadingHTTPServer`；`/api/*`、`/ws` |
| 反向依赖 | `strategy/near_high_hold.py` → `holdingStocks.watch_config` |
| 因子26 真源 | `strategy/pullback_wave_stop.py` |

---

## 16. 本轮交付说明

- **已完成**：全库只读扫描 + 本报告  
- **未执行**：任何代码迁移、删除、重构、依赖安装变更  
- **相关既有文档**：[`ARCHITECTURE.md`](ARCHITECTURE.md)（工程现状说明，非本耦合扫描）

---

*报告生成日期：2026-09-17。下一轮请基于本文件决定：保留 / 移动 / 勿动清单与重构优先级。*
