# 持仓盯盘
# 浏览器打开：http://127.0.0.1:3000/

本地持仓记录 + 盘中盯盘：**与默认策略十六（因子27 + 因子26 + 因子2 + 因子22）同步**。

**行情分层（可扩至数百只观察池）**：
- **热池**（持仓 + 默认策略十六 + 自选，硬帽 ≤48）：东财 SSE + 新浪（约 1s）；走完整 `collect_rows` 信号/四槽。
- **叠加观察池**（如紫阳真君，可 100～500+）：**独立后台**新浪分块轮询（约 3s/轮）；**不占 SSE、不进信号扫描、不挡启动**；Tab 只展示现价/涨幅等轻量行。
- **现价快刷**：独立线程约 **0.4s** 把最新 tick 写进快照（现价/涨跌幅/持仓市值盈亏）并 WS 推送，**不重跑** `collect_rows`；买卖信号/入槽仍按原扫描节奏。
- 同花顺/通达信是专有推送；免费 HTTP 源不能「一只票一条长连接」，否则 500 只根本起不来。

**Python 只提供数据**（行情、信号、JSON/WebSocket）；**盯盘页面只用 Web**（`watch-ui`）。Mac / Windows 同一套启动方式。

可插拔架构见 `../strategy/README.md`。

## 策略锁定 · 策略十六（因子27 + 因子26 + 因子2 + 因子22）

- **买（因子26）**：开盘阈值 `high ≥ ceil(open×(1+entry))`；前日阴线或小阳；禁双阳跨日≥5%；T+1。**触达按 1 分钟顺序**
- **卖（因子26）**：亏损≥2.5%硬保护（低开已破按开盘卖）；买入日收盘<3%记到次日按隔夜高点回落2.5%（不得低于买点硬保护；**昨收/昨高只经 `overnight_peak_px`，仅昨日策略持有或策略买入才并入**）；中赚（>3%且<10%）回落一半与动态高点回落 0.5×近20日日频σ 谁先碰到走谁；大赚阶梯 **10% 半仓** / 15% 全清，其后峰值回落2%清。**盯盘 10% 记减半**（`tp_stage` + `last_tp_ts`，信号「半仓止盈」；不接券商，人工按信号下单）。买入日盈利≥3%不记、其余都记；**触达按 1 分钟 K 顺序**（`first_session_exit_fill`，无个股特例）；策略回放近 **7** 交易日 1m；定盘池短窗回测见 `backtest/strategy1_pool_1m/`
- **选股/过滤**：日线（阴小阳、双阳）；**因子2 回撤**日线权益预警（不注资）
- **因子2**：账户回撤加减仓**预警**（**不自动改现金**）
- **因子22**：研究路径保留；**三槽执行下，当日止损/已记卖出的标的当日禁再买**（不再用因子22 同日回补该票）
- **纸面持仓（Capital V2）**：同时最多 **5** 只；每个交易日最多新开 **2** 个 symbol；单票入场目标 ≤ 权益 **20%**；BUY 受可用现金约束（不得买成负现金）；禁止加仓。**仅默认策略池入槽**；**先平再买**。平仓腾总槽但不恢复当日新增额度。成交价规则不变：平仓前已触买且现价≤买点+1%→现价，否则新触发→买点。
- 交易池：**因子27 选股池** ∪ **公共自选池**（天通/凯盛/东材/金安 · `SELF_WATCHLIST_PICKS`；策略一/十五/十六与盯盘并集均并入）
- 参数与 `strategy16` / `pullback_wave_stop` 同源；`USE_FACTOR4=False`（不叠牛市止损）

完整规则：`from strategy import get_strategy; print(get_strategy("strategy16").print_rules())`

## 默认定盘宇宙（因子27 ∪ 公共自选池）

编辑 **`watch_config.py`**：
- **因子池**：刷新 `picks_quarter.json`（`python strategy/run_core_leader_pool.py`）
- **公共自选池**：改 `SELF_WATCHLIST_PICKS`（旧名 `STRATEGY16_EXTRA_PICKS` 仍兼容；**全策略共用**，非仅策略十六）。「选股/池名单」在策略 Tab **底部折叠面板**（默认收起，展开后按分类 Tab 查看）；上方实时信号表整表展示。

**当前**：因子27 滚动近3个月名单（每概念≤2、约30只）+ 自选四票；剔ST/百元股/科创/创业。改池后需重启 `start_watch.py`。

回测产物：`backtest/strategy16_core_leader/`。**策略十六开盘阈值**只认 `thr_2026.json`（缺省 `DEFAULT_PCT=2.5%`），不走策略一遗留 `_WATCH_PCT` / 置顶名单里的 pct。

**持仓补盯盘**（`PORTFOLIO_PINNED_WATCHLIST`，即使不在默认池也继续展示；策略十六下 **pct 不覆盖** `thr_2026`）：

| 代码 | 名称 | 说明 |
|------|------|------|
| 600552 | 凯盛科技 | 公共自选 / 展示补集 |
| 600330 | 天通股份 | 公共自选 / 展示补集 |
| 600338 | 西藏珠峰 | 展示补集 |
| 601208 | 东材科技 | 公共自选 / 展示补集 |
| 002636 | 金安国纪 | 公共自选 / 展示补集 |

**公共自选池**（入三槽与各策略默认交易宇宙，与因子27并列）：天通、凯盛、东材、金安。

策略三默认三票保留为 `S7_WATCHLIST`（含因子4，历史命名 S7）。切换时改：

```python
STRATEGY_ID = "strategy3"
USE_FACTOR4 = True
WATCHLIST = list(S7_WATCHLIST)
```

## 信号触发规则（盘中对齐回测）

**盯盘 Tab**：仅 **策略1 / 策略3 / 策略8 / 策略15 / 策略16**（有实时面板）。**策略16** 开盘买入阈值来自 `backtest/strategy16_core_leader/thr_2026.json`（2026 至今日线 {2/2.5/3}% 夏普择优；卖仍因子26 硬保护 2.5%）。**策略说明**按盯盘 / 完整 / 因子组合 / 研究分区；缠论笔盈亏比在 **`/factors` → 缠论**。

| 时刻 | 行为 |
|------|------|
| **9:15 前** | 可启动 watch；盘前不触发信号；无成交价用昨收/日线垫现价；**先留上次可用快照再更新，行情未就绪不覆盖成空表** |
| **9:15** | 开始拉竞价行情；**进程内定时任务** `holdings-auction-milestones` 触发：**全日状态重置**（sticky / 非当日 realized / 微信防抖）+ **昨仓今日盈亏按昨收重算**；只留 qty>0 实仓；启动时若已过 9:15 且本日未重置会补跑；报单可撤；**竞价价可展示，禁止止损结算 / 禁止「待卖出」**（预警用「竞价观察」） |
| **9:20** | 竞价不可撤单；同上，仍不可 `apply_exit_fill` |
| **9:25** | 开盘价确定 → 算过门（阴/小阳）/买点/止损，**可挂单**（建议买/卖价）；可亮「竞价止损预警 / 将买入」，**不计已触发、不结算、不「待卖出」** |
| **9:30** | 连续竞价 → **已触发**买卖 / 止损**结算** / 微信（**11:30–13:00 午休、15:00 后不自动成交**）；此时才允许持仓态「待卖出」与【模拟卖出】 |
| **已触止损展示** | 路径触达或现价≤卖价即标「是」并绿底预警；**午休/收盘后仍保留展示**；自动卖出仅连续竞价 |
| **已触买展示** | 过门且盘中触及买点 → 标「已触买」（槽满/未入槽仍预警）；卡片/策略表展示**触发时刻（时分秒）**；**进预警栏后当天不摘**；不降成空仓；自动买入仅连续竞价 |

优先级（9:30 起）：

1. **买入当日（T+1）**：不可卖。盘中盈利未到 3% **只预告**「将记到次日」，**不**把状态打成已触止损、**不**武装当日卖价。收盘确认后才落库武装次日峰值回落。硬保护被路径打到且现价仍在硬保护附近才记「止损已记」，**下一交易日隔夜仓可卖**（`available=0` 当买入日残留，自动解开，不永久锁仓）。**昨收/昨高**只经 `overnight_peak_px`（须 `overnight_session_high_ok`）；今日新买不用昨收/昨高。**唯一落库口** `persist_stop_noted`：只接受 `hard_from_cost` / `t1_trail`，已记价不得高于成本。盈利≥3%、涨停、中段卖价、今开撞当日抬高卖价：**不记、已记作废、禁止写回**。每轮 `heal_watch_ledger` 清掉非法已记。
2. **持有中（全持仓同一套 `paper_exit_decision`）**：非 T+1、可卖则平。盯盘 **5 秒刷新即成交**（现价破卖价按**卖点**记，滑点在策略成本里不加第二次）。1 分钟路径用来排先后、进程迟到时补第一笔触达。昨收已过 3% 且今开低于回落一半 → 按开盘平。**竞价核 = 9:30 开盘价成交**（触发时刻固定 `09:30:00`，不用缺 09:30 的首根 1m 标签 09:31/09:32）。开盘保护用 **9:15 冻结的隔夜峰值**（`overnight_peak`），禁止盘中新高回写后再抬保护（涨停次日高开误杀）；高开且峰值≥今开回退成本/昨收，低开仍用昨高；1m **跳过 09:30 前竞价 K**；开盘保护强制全清（忽略残留 `ladder_half_10`）。禁止用全日最低去撞盘中抬高后的止损。扫仓 `settle_due_paper_stops` 能看见本轮 1m 触达，不再 `path_hit=False`。已平仓卖出侧=锁定成交价。T+1 只记不卖。**10% 只减半**
3. **当日卖出后再买**：**禁止**（止损/已记卖出的标的当日不可再买）
4. **仓位（Capital V2）**：同时最多 5；日新开最多 2 symbol；单票入场 ≤ 权益 20%；现金约束、禁止负现金买入、禁止加仓；**先平再买**；腾槽价规则同前
5. **空仓**：过滤通过且触买点 → **买入信号预警必须进持仓预警栏**（待买入 / 已触买）；**入槽是成交**，槽满/日额度满/现金不足仍可发「已触买·槽满/未入槽」或挂单说明「资金规则未开仓」。策略回放止损不当当日禁买。**未过门不算触买、不预警**
6. **数据**：买入触达 **5 秒现价/最高 ≥ 买点即成交**。新触发（含开盘空槽）成交价=**买点**；平仓腾槽后第一梯队（平仓前已触买）成交价=**现价**，且现价不得超过买点 1%。有 1m 则用触达分钟的时分秒排入槽先后。卖出同口径。`信号时间` 来自 sticky / `buy_time` / 1m `touch_ts` / 行情 `last_ts`，已入槽后本轮不再算触买也要显示。禁止用收盘后抬高的止损去撞今开。

（**9:15–9:25 竞价**：只拉行情参考，**不算**买点/动态止盈/触达、**不**回写峰值。  
**9:25–9:30**：开盘价已定，**可挂单**（阈值/将买入/将止损），**不**结算、**不**推微信。  
**9:30 起**：已触发买卖 / 止损结算 / 微信。因子26 实仓触达用当日 1m 缓存。）

（策略三开启 `USE_FACTOR4` 时：牛市可放宽/暂停止损，见 `factor4_watch.py`。）

**盯盘卡片 · 持仓状态**：
1. **待买入**：真·空仓 + 当日可买 + 进入买入预警带（含已触买但未入槽）
2. **待卖出**：实仓 + 止损预警带（可执行；T+1 当日不可卖）
3. **已经买入**：实仓入槽（同时最多 **4** 只）
4. **策略持有**：日线回放仍持仓、本地未登记数量
5. **今日平仓**：仅四槽实仓当日纸面卖出（`realized_today`）；策略回放止损 / 历史买档残留不进；角标「已触止损」；持仓页单独栏不占槽，次日清
6. **空仓**：可买日但未进买入预警带

**持仓 Tab（Capital V2）**：同时最多 **5** 只（仅 `qty>0` 占槽）；每个交易日最多新开 **2** 个 symbol（从 `trades.jsonl` BUY 重建，restart 不重置）；单票入场目标 = 决策时权益 × **20%**，再受 available cash 约束（不得负现金）。**入槽宇宙 = 当前默认策略池**。SELL 释放总槽但不恢复当日新增额度。

登记示例：`python index.py set-cost 002015 --cost 16.122 --qty 600`；或在 `holdings.json` 加 `"portfolio_pool": ["002015"]`。

**策略16 Tab**：默认池信号表，按 **距买点% 升序**（最近在前）；可点表头按 **日内涨跌** / **策略累计** 排序（高→低→默认）。状态列同时标 **纸面**（空仓/已经买入…）与 **回放**（回放持有/回放空仓，来自 `策略累计持有`，禁止用收益%反推）；二者独立、互不覆盖。状态列打「已触买·槽满/未入槽」等标记（与持仓预警同一口径）；**今日已入槽**另标「今日触买」，图例「已经买入」计纸面实仓、「已触买」含已入槽的当日触买，**T+1 止损已记不算「已触止损」筛选**。标「槽位候选」；展示日内涨跌、**策略累计%**（自 `STRATEGY_PNL_START`=2026-09-09，单票因子1虚拟账本累计；虚拟持有时 mark 现价、已平冻结；字段 `策略收益%`）与**单笔收入%**（`已触发因子价`→现价的理论收益率；触买即可算、无需入槽；≠持仓成本收益、≠策略累计）。状态图例可点筛选、可多选，旁有重置。买入信号口径真源：`watch_buy_signal.py`。

**浮盈/结算（名称旁）**：**今日盈亏 / 今日浮亏** = 四槽持仓 `session_day_pnl`（**今买相对买入价，昨仓相对昨收**；9:15 / 跨日沿用快照时按昨收重置）+ **今日平仓**记账 `day_pnl`（只认 `已实现`，**隔日平仓留痕不计**）。卡片不回退展示「相对成本」的浮盈当今日浮亏。**总资产** = 日初锁定（优先昨收结算 `account_total`；**日初锚跟日历信号日 `trading_session_date`**，不用行情盘前滞后的行上「交易日」；跨日 heal 幂等，不依赖正好 9:15 在线）+ **今日盈亏**（与分票加总同动）。账户摘要「今日盈亏率」= 今日盈亏 / 日初锁定 `account_total_open`（单票「当日盈亏%」仍用该票当日基数）。**总收益** = 总资产 − 纸面本金（`paper_equity_base`，默认 30 万，自 **`PAPER_PNL_START`=2026-09-09**），即「昨收累计 + 今日盈亏」。**15:00 日结** = `POSITION_SETTLEMENT`（收盘盯市，**不改 qty/cost、不写 SELL**）；下一交易日 `account_total_open` = 昨收 `closing_equity`。账户摘要「当前持仓成本」= 剩余仓 `成本额`，**不含**今日已平仓成本。每日收盘后写一次 `holdings.daily_settlements[交易日]`（终稿；盘中可更新草稿；次日 heal/9:15 补记未终稿日），含今日盈亏 vs 权益日变差额核对。**今日平仓**卡片锁定平仓价；策略回放持有不进账户合计。

**Paper 卖出**：`paper_exit_decision` 当前 **Unified Primary**（`USE_UNIFIED_EXIT_ENGINE=True`），Legacy 只做 Shadow / fallback（`SHADOW_UNIFIED_EXIT_ENGINE=True`）。Shadow 比较不成交、不发微信。

**微信推送（N1）**：预警与成交分模板。扫描只发 **【策略预警】**（将买入 / 已触买未成交 / 槽满 / 将止损 / T+1 暂不可卖 / 跌停不可卖）；**真实 paper 成交**在 `apply_paper_slot_buy` / `apply_exit_fill` 写入仓位与 ledger 之后发 **【模拟买入】** / **【模拟卖出】**（含 reason_code：WORKING_STOP / OPEN_PROTECT / PATH / HALF / EOD_RESERVE）。已成交事件不再被扫描重复推。预警扫描仅默认策略池（strategy16）；实仓 SELL 即使已离开默认池仍推成交通知。Shadow 不发微信。`start_watch --no-wechat` / `watch --no-wechat`：**预警与买卖成交都不推**，不影响 paper execution。

**会话失效自动恢复**：`prepare failed` / `ret=-2` 识别为 `SESSION_INVALID`（不空转重试）。盘中改为异步入队（daemon worker），暂停出站并将通知写入有限 pending（同票同预警类型去重）；轮询 `~/.openclaw/openclaw-weixin/accounts/*.context-tokens.json` 的 mtime，检测到 inbound 刷新后再探测发送并 flush。持续失效超过约 5 分钟只打一次 `[WECHAT][ACTION REQUIRED]`。OpenClaw 发送与恢复不阻塞行情/策略/paper。

**channels login**：`openclaw channels login --channel openclaw-weixin` 解决的是**通道账号登录**（常需扫码），不等于刷新出站 `context_token`。默认 **不会每次启动都跑**（会阻塞扫码）。行为由 `wechat_notify.json` 控制：`login_on_channel_fail=true`（默认）仅在通道未就绪/自检 prepare failed 时引导 login；若要每次启动都 login，设 `"login_on_start": true`，或启动加 `--wechat-login`。自然 BUY/SELL 微信覆盖仍在积累（**PENDING**），不能当成已完成。

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
| `trade_ledger.py` | 交割单 JSON 账本（`trade_ledger.json`）；买入入槽/卖出平仓落库；API 读模型对仍持仓 BUY 按现价盯市「单笔盈亏」（不写回 ledger） |
| `index.py` | 盯盘主程序 / JSON 推送 / 微信 / 买卖记账 |
| `holdings_sync.py` | Win/Mac 账本：`holdings-push` / `holdings-pull` → `origin/holdings-ledger` |
| `start_watch.py` | 一键启动 API+Nuxt；默认先拉远程持仓；`--stop` / `--force` 回收端口 |
| `watch_process.py` | Windows 端口/PID 回收（Ctrl+C 孤儿进程） |
| `quote_feed.py` | 行情聚合 |
| `wechat_notify.py` | 微信推送 |

## 前端 watch-ui（Nuxt 3 + Vue 3 + Pinia + Tailwind）

浏览器 **http://127.0.0.1:3000/sectors** 为板块轮动热力表。**优先通达信概念**（本地配置同步 + pytdx）；行情失败时仅复用**同一交易日且今日列已有排名**的通达信磁盘缓存（≤2 天）。**隔日缓存作废**；通达信只拉到 1 日时拼回磁盘历史，禁止整表覆盖。**启动分步**：先推盯盘/策略快照并实时刷新，板块通达信全市场行情放到首屏之后的后台线程（约 5s）；主循环不再同步 `build_sectors_live_payload`。历史列来自 `/api/sectors/rotation`（约 1 小时缓存，「重载历史」才重拉）；**今日列与成分股现价走盯盘 WebSocket**。点格子只为展开成分名单；再点一次进概念详情（先 lite 出 K 线，再补波段龙头；因子16 评分后置）。

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

**启动顺序**：`watch` **先绑定并开始接受** `:8765`（HTTP `/api` + WebSocket `/ws`），再后台做冷启动（新浪批量、**强制按信号交易日重拉日线**、东财 SSE、首屏快照）。日线末根须覆盖「最近已收盘工作日」（15:15 前不含当日）；缺则增量/全量补拉，避免过门/前日沿用旧 parquet。周六日信号日锚定上周五；周一「前日」自然为上周五。`start_watch.py` 等 API 端口就绪后再自己开 Nuxt（并传 `--no-ui-dev`，避免两套前端抢 `:3000`）。此前若等首屏算完才绑端口，池子变大后会超过 120s，页面红字「推送断开，等待重连…」。冷启动期间若有上次 `holdings_watch.json` **且不比 `holdings.json` 旧** 会先展示旧快照，否则丢掉过期缓存并推 `boot` 占位。首屏/轮询**先记录再更新**：行情全失败或持仓/策略十六被滤空时沿用上一份可用快照（`quoteStale`），不覆盖成空表；账本 `occupied` 变了才出新快照。

**顶栏红字不只看本机 WebSocket**。`:8765` 在本机，断外网时 WS 仍可能显示已连接、hub 里还有断开前的现价。快照带 `feedOk` / `quoteStale` / `quoteAt`（最近一次东财 SSE 或新浪批量成功）；超过约 40s 没收外网行情，顶栏红字「行情中断，数据停在 HH:MM:SS」。刷新线程卡住时仍有 **2s 时钟心跳**，页面时钟继续走，不要把「本机 WS 还开着」当成行情正常。前端 `updatedAt` 超过 20s 也红字「服务停滞」。午休无成交只要新浪兜底还通，不红。

loop 内「快照已推送」默认**每 12 次**输出一条（冷启动仍打印；业务无变化跳过写盘，仍广播时钟/行情健康度）；恢复每次：`WATCH_SNAPSHOT_LOG_EVERY=1 python index.py watch …`

**实时可靠性（行情未齐不写账本）**：每轮先 `heal_watch_ledger`（隔夜 `available=0` 解锁、仅现金日初修复、清掉已记价高于成本的非法「止损已记」），再 `settle_due_paper_stops` 按 `paper_exit_decision` 扫全部实仓补平。实仓缺现价/市值时**不**回写 `account_total`、**不**自动入槽、**不**用失败行情覆盖可用快照。盯盘是纸面信号，不下券商单；数字错了会误导实盘，所以失败只沿用上次可用状态。禁止再犯清单见仓库 [`TODO.MD`](../TODO.MD)「锁定 · 盯盘可靠性」。

**性能（安全组合，不影响结算）**：每轮仍全量 `collect_rows`（含止损结算）；`holdings.json` 进程内缓存、`replay` 按日缓存；快照业务指纹相同时跳过写盘，仍推时钟与 `quoteStale`。

API：

| 路径 | 说明 |
|------|------|
| `GET /api/snapshot` | 最新 WatchSnapshot v1 |
| `GET /api/shadow/status` | 只读 Shadow telemetry（metrics / buffer 长度 / 最近一条；无 reset） |
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
python index.py clear-all    # 清仓+重置状态+归档当日成交；账户回到 DEFAULT_ACCOUNT_TOTAL（现 30 万）
python index.py buy 600552 15.50 400
python index.py sell 600552 16.20 400
python index.py holdings-push   # 本机账本 → origin/holdings-ledger（给另一台 Mac/Win）
python index.py holdings-pull   # 远程账本 → 本机；丢掉 holdings_watch.json 旧缓存
```

**Win / Mac 同一份持仓**：当前生产真源仍是本机 `holdings.json` + `trades.jsonl` + `trade_ledger.json`（交割明细），经独立分支 `holdings-ledger` 同步（不进 `main`）。`holdings_watch.json` 只是本机盯盘展示缓存；账本更新后启动会丢掉过期缓存。`start_watch.py` 默认先 `holdings-pull`。盘后在有成交的那台 `holdings-push`，另一台开盯盘前会自动拉。离线用 `--no-ledger-pull`。

**Remote Paper State（Phase R1，未切生产）**：目标改为远程 PostgreSQL 单真源 + 单 writer lease（防双机重复成交）。本阶段仅落地 `paper_state/` 接口、schema、迁移 dry-run 与单测；**watch 仍写本地 JSON**。设计与命令见 [`docs/REMOTE_PAPER_STATE.md`](docs/REMOTE_PAPER_STATE.md)。

**交割单**：持仓卡片现价旁 **价格**（外网行情）/ **交割**（跳转 `/trades?code=`）；顶栏与账户卡也可进 `/trades`。明细含代码、名称、买卖价、仓位、金额、单笔盈亏、账户余额、买卖理由；API `GET /api/trades`。单笔盈亏：仍持仓 BUY = `(现价−成本)×剩余仓`（浮动，复用快照/持仓现价）；SELL = 成交时 realized（冻结）。仓位列为 `qty→after_qty`（本笔数量→成交后持仓），非 lot remaining。无独立 FIFO lot，盯市挂在该代码最近一笔仍开仓 BUY、remaining=当前持仓 qty。

## 如何扩展

1. **改定盘池/阈值**：策略十六改 `picks_quarter.json` + 重跑 `python backtest/strategy16_core_leader/fit_thr.py`；策略一遗留池才改 `_FIT_WATCH` / `_WATCH_PCT`
2. **策略三 Tab**：股池=中证1000 **昨日收盘涨停全池**；**T-1 情绪**（涨停家数→冰点/正常/高潮 + 连板梯度）决定今日可否做；因子1 ±阈值、**不过阴/小阳过门**。回测另含首板/gap 等见 `backtest/strategy3_first_board/`
3. **策略八 Tab**：**当日涨停**定热题材（≥3），盘中随涨停变化重算（不读回测末日名单）→ 题材内联动候选；T-1 情绪 + **当日**因子1 ±阈值（不要求昨日涨停）。回测见 `backtest/strategy8_theme_linkage/`
4. **策略十五 Tab**：同策略一池叠加；T-1 连板梯度定 F22/F25；震荡启用因子25（30m 确认止损/动态半仓/卖飞回补提示）；回测 `backtest/strategy15_m30_chop/`
5. **策略十七 Tab（紫阳真君）**：武汉紫阳东路近3个月龙虎榜成交池（因子28）；买卖规则同因子26；**非默认交易池**；刷新 `python strategy/run_ziyang_pool.py`
6. **新因子叠加入口**：在 `index.py` 信号环对齐对应 `get_strategy_bindings` / decision
