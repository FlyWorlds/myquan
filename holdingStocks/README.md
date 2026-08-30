# 持仓盯盘
# 浏览器打开：http://127.0.0.1:8765/

本地持仓记录 + 盘中盯盘：**与核心策略一（因子1 + 因子2）同步**。

可插拔架构见 `../strategy/README.md`。

## 策略锁定 · 策略一（因子1 + 因子2）

- **因子1 买**：`high ≥ ceil(open×(1+entry))`；前日阴线或小阳；禁双阳跨日≥5%；T+1
- **因子1 卖**：`low ≤ floor(open×(1−stop))` 全清；个股阈值见 `watch_config`
- **因子2**：账户回撤加减仓**预警**（**不自动改现金**）
- 参数与 `strategy1` / `open_break` 同源；`USE_FACTOR4=False`（不叠牛市止损）

完整规则：`from strategy import get_strategy; print(get_strategy("strategy1").print_rules())`

## 默认定盘宇宙（置顶三票 + 拟合池）

编辑 **`watch_config.py`** 的 `PINNED_WATCHLIST` / `FIT_WATCHLIST`（`index.py` 从此导入 `WATCHLIST`）。

**置顶定案（卡片排序优先，2026-08-30）：**

| 代码 | 名称 | 因子1 | 备注 |
|------|------|-------|------|
| 600552 | 凯盛科技 | ±2.5% | **持仓 500 股** |
| 600338 | 西藏珠峰 | ±2.5% | **持仓 700 股** |
| 600330 | 天通股份 | ±3.0% | 已卖出，仍置顶盯买/卖信号 |

东材科技等在拟合池其余；科创综指 ETF 已移出置顶。

其后为中证拟合池其余（去重置顶三票），个股阈值见 `_WATCH_PCT`。

策略三默认三票保留为 `S7_WATCHLIST`（含因子4，历史命名 S7）。切换时改：

```python
STRATEGY_ID = "strategy3"
USE_FACTOR4 = True
WATCHLIST = list(S7_WATCHLIST)
```

## 信号触发规则（盘中对齐回测）

**策略 Tab（`策略N-名称`）**：自注册表列出全部已实现策略；每 Tab 展示挂载因子 ID、因子名称、角色与说明。**策略1-援军战法** 另含早盘过门/阈值实时表（盯盘默认）。

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
4. **策略持有**：日线回放仍持仓、本地未登记数量 — 只盯止损
5. **当日禁买**：今日已止损/卖出
6. **空仓**：可买日但未进买入预警带

**微信推送**：P0=因子已触发；P1=触发预警带。有仓只推止损；空仓只推买入。

## 依赖

```bash
pip install -r ../requirements.txt
```

## 模块

| 文件 | 职责 |
|------|------|
| `watch_config.py` | 策略 ID、置顶三票 + 拟合池、阈值、竞价窗口；S7 备用 |
| `factor2_watch.py` | 账户回撤预警 |
| `factor4_watch.py` | 牛市 regime（策略三 + 因子4 时） |
| `index.py` | 盯盘主程序 / JSON 推送 / 微信 / 买卖记账 |
| `quote_feed.py` | 行情聚合 |
| `wechat_notify.py` | 微信推送 |

## 前端 watch-ui（Nuxt 3 + Vue 3 + Pinia + Tailwind）

栈对齐 PandaAI 官网：**Nuxt 3 / Vue 3 / Pinia / Vite（Nuxt 内置）**，叠加 **Tailwind** 与 **自研 `--ui-*` design token**（黑底卡片风）。Python `watch` 只推送 **JSON 快照**（WebSocket `/ws`），不再每次生成 HTML。

```bash
# 开发（Python watch 与 Nuxt 并行）
cd holdingStocks && python index.py watch --port 8765 --no-wechat
cd holdingStocks/watch-ui && npm install && npm run dev   # http://127.0.0.1:3000

# 生产构建（nuxt generate → 复制到 dist/，Python 静态托管）
cd holdingStocks/watch-ui && npm run build
cd holdingStocks && python index.py watch --port 8765 --no-wechat
# 打开 http://127.0.0.1:8765/
```

API：

| 路径 | 说明 |
|------|------|
| `GET /api/snapshot` | 最新 WatchSnapshot v1 |
| `GET /api/strategies` | 策略 Tab + 因子绑定 |
| `WS /ws` | 推送 snapshot（与 `/api/snapshot` 同结构） |

CLI 单次刷新（非 watch）：`python index.py` 终端输出；若 watch 已在跑则同步 JSON 并可选打开前端。

## 常用命令

```bash
cd holdingStocks
python index.py              # 终端查看行情 + 持仓
python index.py watch        # 长驻盯盘：Nuxt 前端 + WebSocket JSON
python index.py buy 600552 15.50 400
python index.py sell 600552 16.20 400
```

## 如何扩展

1. **改置顶/阈值**：只改 `watch_config.PINNED_WATCHLIST` / `_WATCH_PCT`
2. **切策略三三票（含因子4）**：`STRATEGY_ID="strategy3"`、`USE_FACTOR4=True`、`WATCHLIST=list(S7_WATCHLIST)`
3. **新因子叠加入口**：在 `index.py` 信号环对齐对应 `get_strategy_bindings` / decision
