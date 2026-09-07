# 持仓盯盘
# 浏览器打开：http://127.0.0.1:3000/

本地持仓记录 + 盘中盯盘：**与核心策略一（因子1 + 因子2 + 因子22）同步**。

**Python 只提供数据**（行情、信号、JSON/WebSocket）；**盯盘页面只用 Web**（`watch-ui`）。Mac / Windows 同一套启动方式。

可插拔架构见 `../strategy/README.md`。

## 策略锁定 · 策略一（因子1 + 因子2 + 因子22）

- **因子1 买**：`high ≥ ceil(open×(1+entry))`；前日阴线或小阳；禁双阳跨日≥5%；T+1
- **因子1 卖**：`low ≤ floor(open×(1−stop))` 全清；个股阈值见 `watch_config`
- **因子2**：账户回撤加减仓**预警**（**不自动改现金**）
- **因子22**：当日止损后，`收盘 ≥ 当日最低×(1+1%)` 可同日再买（默认 1%）
- **三槽持仓**：最多 3 槽×约 30%；空槽按距买点补候选，触买纸面入仓；触卖释放槽+当日留痕
- 参数与 `strategy1` / `open_break` 同源；`USE_FACTOR4=False`（不叠牛市止损）

完整规则：`from strategy import get_strategy; print(get_strategy("strategy1").print_rules())`

## 默认定盘宇宙（因子13A+16 宽宇宙换池 · 无置顶）

编辑 **`watch_config.py`** 的 `_FIT_WATCH` / `FIT_WATCHLIST`（`index.py` 从此导入 `WATCHLIST`）。

**当前定盘池（20 只；2026-09-02 换池 · 剔ST/百元股/科创/创业）：**

| 代码 | 名称 | 因子1 阈值 |
|------|------|-----------|
| 002104 | 恒宝股份 | ±2.5% |
| 603301 | 振德医疗 | ±3.0% |
| 600301 | 华锡有色 | ±3.0% |
| 002093 | 国脉科技 | ±3.0% |
| 600552 | 凯盛科技 | ±2.5% |
| 601020 | 华钰矿业 | ±3.0% |
| 601609 | 金田股份 | ±2.0% |
| 600353 | 旭光电子 | ±3.0% |
| 002779 | 中坚科技 | ±3.0% |
| 601068 | 中铝国际 | ±3.0% |
| 600967 | 内蒙一机 | ±2.5% |
| 002273 | 水晶光电 | ±2.0% |
| 002015 | 协鑫能科 | ±2.5% |
| 002929 | 润建股份 | ±2.5% |
| 000581 | 威孚高科 | ±2.0% |
| 601519 | 大智慧 | ±3.0% |
| 002922 | 伊戈尔 | ±2.0% |
| 002152 | 广电运通 | ±2.5% |
| 603920 | 世运电路 | ±3.0% |
| 002065 | 东华软件 | ±2.5% |

选股链：因子13A 质量带初选≤80 → 因子16 OOS 盈亏比排序 Top20；宇宙剔科创/创业/北交、ST、收盘价≥100元；**无置顶**，及格才入池。回测产物：`backtest/s1_f13_refit_2025/`；写回盯盘：`python backtest/s1_f13_refit_2025.py --apply-watch`。

个股非默认阈值见 `_WATCH_PCT`。

策略三默认三票保留为 `S7_WATCHLIST`（含因子4，历史命名 S7）。切换时改：

```python
STRATEGY_ID = "strategy3"
USE_FACTOR4 = True
WATCHLIST = list(S7_WATCHLIST)
```

## 信号触发规则（盘中对齐回测）

**盯盘 Tab**：仅 **策略1 / 策略3 / 策略8**（有实时面板）。**策略说明**按盯盘 / 完整 / 因子组合 / 研究分区；缠论笔盈亏比在 **`/factors` → 缠论**。

| 时刻 | 行为 |
|------|------|
| **9:15 前** | 可启动 watch；盘前不触发信号 |
| **9:15** | 开始拉竞价行情；报单可撤 |
| **9:20** | 竞价不可撤单 |
| **9:25** | 开盘价确定 → 算过门（阴/小阳）/买点/止损，**策略1-援军战法 Tab 展示** |
| **9:30** | 连续竞价 → 触发买卖/止损结算/微信 |

优先级（9:30 起）：

1. **买入当日（T+1）**：不可卖
2. **持有中**：触止损 → 按止损价自动结算全清
3. **止损/卖出当日禁买**：当天已平仓不再进「待买入」
4. **空仓**：过滤通过且触买点 → 待买入 / 已触买推送

（9:15–9:30 仅刷新实时行情与阈值预览，**不**结算止损、**不**推微信；不拉历史分钟 K。）

（策略三开启 `USE_FACTOR4` 时：牛市可放宽/暂停止损，见 `factor4_watch.py`。）

**盯盘卡片 · 持仓状态**：
1. **待买入**：真·空仓 + 当日可买 + 进入买入预警带
2. **待卖出**：实仓 + 止损预警带（可执行；T+1 当日不可卖）
3. **持有**：实仓且无卖出预警
4. **策略持有**：日线回放仍持仓、本地未登记数量 — 默认只盯止损；**若今日触买/近买点仍亮买入信号**（防漏单）
5. **当日禁买**：今日已止损/卖出
6. **空仓**：可买日但未进买入预警带

**持仓 Tab（三槽池）**：最多 **3 槽**，每槽约 **3 成仓**。仅 `qty>0` 占槽；触卖清仓后 **释放槽位**，当日通过 `realized_today` **留痕一天**（qty=0，次日移出）。空槽从策略一定盘池按 **距买点升序** 取候选；**9:30 后触买** 则纸面自动记 `qty`+成本（整手）。**当日预警票**（将买入/已触买/近买点/槽位候选等）也会出现在持仓界面，**仅展示、不登记持仓**。名称仍以 `holdings.json` 为准。策略1 Tab 为定盘池完整信号。

登记示例：`python index.py set-cost 002015 --cost 16.122 --qty 600`；或在 `holdings.json` 加 `"portfolio_pool": ["002015"]`。

**策略1 Tab**：定盘池信号表，按 **距买点% 升序**（最近在前）；标「槽位候选」；展示日内涨跌与策略收益%（自 `STRATEGY_PNL_START`；不含持仓浮盈金额，浮盈仅在「持仓」Tab）。

**浮盈/结算（名称旁）**：实仓按登记**买入成本 × 持仓**随现价动态；当日卖出后显示**结算**盈亏（锁定成交价）；策略回放持有（未登记仓）按策略买入因子价单股测算。

**微信推送**：P0=因子已触发；P1=触发预警带。有仓只推止损；空仓只推买入。**策略回放持有若今日触买**，仍推买入侧 P0。

## 依赖

```bash
pip install -r ../requirements.txt
```

## 模块

| 文件 | 职责 |
|------|------|
| `watch_config.py` | 策略 ID、定盘池 `_FIT_WATCH`、阈值、竞价窗口；S7 备用 |
| `factor2_watch.py` | 账户回撤预警 |
| `factor4_watch.py` | 牛市 regime（策略三 + 因子4 时） |
| `index.py` | 盯盘主程序 / JSON 推送 / 微信 / 买卖记账 |
| `start_watch.py` | 一键启动 API+Nuxt；`--stop` / `--force` 回收端口 |
| `watch_process.py` | Windows 端口/PID 回收（Ctrl+C 孤儿进程） |
| `quote_feed.py` | 行情聚合 |
| `wechat_notify.py` | 微信推送 |

## 前端 watch-ui（Nuxt 3 + Vue 3 + Pinia + Tailwind）

浏览器 **http://127.0.0.1:3000/sectors** 为板块轮动热力表。**优先通达信概念**（本地配置同步 + pytdx）；行情失败时仅复用**同一交易日且今日列已有排名**的通达信磁盘缓存（≤2 天）。**隔日缓存作废**；通达信只拉到 1 日时拼回磁盘历史，禁止整表覆盖。前端用盯盘 `conceptToday` 写入最左「今日」列（以服务器 `clock` 为准）。**点击格子加载成分股**；再点一次进概念详情（先 lite 出 K 线，再补波段龙头；因子16 评分后置）。

栈对齐 PandaAI 官网：**Nuxt 3 / Vue 3 / Pinia / Vite（Nuxt 内置）**，叠加 **Tailwind** 与 **自研 `--ui-*` design token**（黑底卡片风）。Python `watch` 只推送 **JSON 快照**（HTTP `/api` + WebSocket `/ws`），不生成 HTML、不托管页面。

```bash
# 推荐：一键（Mac / Windows）
cd holdingStocks && python start_watch.py --no-wechat
# 浏览器 http://127.0.0.1:3000/  ·  数据 API/WS :8765

# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_watch.ps1 --no-wechat
# 端口占用 / Ctrl+C 后启不动：
python start_watch.py --stop      # 停服务并释放 8765、3000
python start_watch.py --force     # 强制停旧实例并启动
# 或：python index.py watch-stop

# macOS
./start_watch.sh --no-wechat

# 或分两终端
cd holdingStocks && python index.py watch --no-wechat
cd holdingStocks/watch-ui && npm install && npm run dev
```

loop 内「快照已推送」默认**每 12 次**输出一条（冷启动仍打印；业务无变化跳过写盘/WS 时不计次）；恢复每次：`WATCH_SNAPSHOT_LOG_EVERY=1 python index.py watch …`

**性能（安全组合，不影响结算）**：每轮仍全量 `collect_rows`（含止损结算）；`holdings.json` 进程内缓存、`replay` 按日缓存；快照业务指纹相同时跳过写盘与 WebSocket 广播。

API：

| 路径 | 说明 |
|------|------|
| `GET /api/snapshot` | 最新 WatchSnapshot v1 |
| `GET /api/strategies` | 策略 Tab + 因子绑定（注册表同源） |
| `GET /api/factors` | 因子说明 + 挂载策略（注册表同源） |
| `WS /ws` | 推送 snapshot（与 `/api/snapshot` 同结构） |

前端路由（Nuxt SPA）：

| 路径 | 说明 |
|------|------|
| `/` | 持仓盯盘（首页） |
| `/strategies` | 策略说明（全量注册表） |
| `/factors` | 因子说明（全量注册表 + 规则摘要） |

顶栏可跳转；**新增/改策略或因子**后更新 `strategy/` 注册表并**重启 watch**，说明页自动同步（无需改前端静态文案）。

CLI 单次刷新（非 watch）：`python index.py` 终端输出；若 watch 已在跑则同步 JSON 并可选打开前端。

## 常用命令

```bash
cd holdingStocks
python start_watch.py        # 推荐：数据 API + Web 盯盘（Mac/Windows）
python index.py              # 终端查看行情 + 持仓
python index.py watch        # 仅数据后端（不启页面）
python index.py buy 600552 15.50 400
python index.py sell 600552 16.20 400
```

## 如何扩展

1. **改定盘池/阈值**：改 `watch_config._FIT_WATCH` / `_WATCH_PCT`，或跑 `python backtest/s1_f13_refit_2025.py --apply-watch`
2. **策略三 Tab**：股池=中证1000 **昨日收盘涨停全池**；**T-1 情绪**（涨停家数→冰点/正常/高潮 + 连板梯度）决定今日可否做；因子1 ±阈值、**不过阴/小阳过门**。回测另含首板/gap 等见 `backtest/strategy3_first_board/`
3. **策略八 Tab**：**当日涨停**定热题材（≥3），盘中随涨停变化重算（不读回测末日名单）→ 题材内联动候选；T-1 情绪 + **当日**因子1 ±阈值（不要求昨日涨停）。回测见 `backtest/strategy8_theme_linkage/`
4. **新因子叠加入口**：在 `index.py` 信号环对齐对应 `get_strategy_bindings` / decision
