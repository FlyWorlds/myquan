### P0（剩余）
- [ ] **持仓手工录入进数据库**：持仓、盈亏、总金额、统计（非代码录入）
- [x] **Win/Mac 持仓远程同步**：账本 `holdings.json`+`trades.jsonl` 走 `origin/holdings-ledger`（`holdings-push` / `holdings-pull`）；`holdings_watch.json` 只当本机缓存，过期丢弃

### P1 · 策略十六算法审核跟进（2026-09-13，见 [`docs/PROJECT_AUDIT.md`](docs/PROJECT_AUDIT.md)）
- [x] **盯盘 10% 仍全清**：持仓记 `tp_stage` / `last_tp_ts`；10% 只卖一半并写「半仓止盈」；半仓后从触达分钟下一根继续盯剩余；`realized_today` 允许当日第二笔。不接券商，只出信号 + 纸面数量。
- [x] **因子22 绑定开着、生产成交关着**：策略十六默认 `factor22.enabled=False`；盯盘 / 默认 `pool_1m` 当日卖出后仍禁再买。研究对照脚本可显式打开。
- [x] **Decision 日线同 bar 前视**：无 `meta.path_hit_stop` 时不再用全日 low 成交。
- [x] **工作止损 dummy 假触发阶梯**：未触达时走 `working_stop_price`（过 10% 展示峰值回落 2%），不再用 OHLC=peak 撞 10%/15% 目标价。
- [x] **对账回测不计费**：`pool_1m` 现金/权益按 `strategy.costs` 扣佣金+杂费+印花+滑点。
- [x] **2026-09-30 因子27 重选**：`picks_quarter.json` as_of 2026-09-30（30只/18概念，有效至 2026-12-30）；HQ/东财失败走轮动缓存+新浪；0票不覆盖旧池。改池须重启 `start_watch`。名单见 [`docs/FACTOR27.md`](docs/FACTOR27.md)。
- [x] **2026-09-30 策略16 累计重置**：`STRATEGY_PNL_START=2026-10-08`（国庆后首个交易日才计策略累计）；纸面总收益仍 `PAPER_PNL_START=2026-09-09`。起算日前 simulator `skipped=before_pnl_start`。
- [ ] **近 7 日 1m + 阈值择优窗口太短**：`--fit-thr` 用 2026 至今日线夏普择优，再在近 7 日 1m 上看组合。只能当执行核对，不能当样本外期望；加长窗独立验证前勿把该数字当策略期望。
- [ ] **T1 已记依赖收盘进程仍活着**：买入日 `t1_trail` 只在收盘确认后落库；进程若提前退出，次日可能只剩硬保护。
- [ ] **无券商报单/持仓对账**：本地触发价必成，不能当实盘成交。

### Exit Decision 统一门槛（Phase 3A～3C+，2026-09-18）
- [x] **只读真实分钟 replay 入口**：`backtest/exit_decision_replay/run.py`；Legacy 与 Unified 同 Context 双跑，不成交、不写 ledger。
- [x] **第一批严格 parity**：真实 1m OHLC 上 8,077 次 evaluation，Legacy/Unified 各 SELL 25，25/25 action/price/quantity 一致，Mismatch 0；见 [`docs/DECISION_PARITY_PHASE3_REPLAY.md`](docs/DECISION_PARITY_PHASE3_REPLAY.md)。
- [x] **Phase 3C+ 路径覆盖**：[`docs/EXIT_COVERAGE_MATRIX.md`](docs/EXIT_COVERAGE_MATRIX.md) · [`docs/EXIT_COVERAGE_QUALIFICATION.md`](docs/EXIT_COVERAGE_QUALIFICATION.md)。`find_cases.py` + corpus；collision/boundary characterization PASS；Partial SELL 2/2 @0.5；Working Stop 赢家历史 0（信号 1944）。
- [x] **Production Shadow Readiness（3D）**：副作用审计、失败隔离、candidate/winner/`superseded_by`、mismatch replay。见 [`docs/SHADOW_SIDE_EFFECT_AUDIT.md`](docs/SHADOW_SIDE_EFFECT_AUDIT.md) · [`docs/SHADOW_VALIDATION_REPORT.md`](docs/SHADOW_VALIDATION_REPORT.md)。**Historical at 3D close：** 当时未打开 `SHADOW_UNIFIED_EXIT_ENGINE`。已被 Primary Reversal 取代。
- [x] **Unified 正式接管 paper（Primary Reversal）**：`USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`。Unified = Primary，Legacy = Shadow / fallback。不要删 `_paper_exit_decision_legacy`。Notification N1 已部署（`37b0c5c7`）；自然微信 runtime validation PENDING；N2 未开始。

### 锁定 · 盯盘可靠性（2026-09-14，禁止再犯）

当日纸面盯盘事故（空表、假锁、该平未平、信号不同步、平仓价看起来不对、断网无红字）根因都是**失败行情/残留锁仓/抬高止损被当成账本真源，或把本机 WS 当成外网行情**。细节见 [`holdingStocks/README.md`](holdingStocks/README.md)「实时可靠性」。下列为合并后的事故→解法；禁止列与之对应，改盯盘不得绕过。

| 当日现象 | 解法（已进代码） |
|----------|------------------|
| 行情失败后持仓/策略十六变成空表 | 先留上次可用快照再更新；未就绪不覆盖（`should_keep_last_snapshot` / `quoteStale`） |
| 合计 +764%、顶栏只剩现金、今日%乱跳 | 市值未齐不回写 `account_total` / 不锁仅现金日初；合计=浮盈+已平仓，今日%=当日基数 |
| 隔夜仓 `available=0`，「已触止损·暂不可卖」假锁 | 当买入日残留，每轮 `heal_watch_ledger` 解开；9:15 不是唯一解锁点 |
| 跨日「今日浮亏」仍显示买入日相对成本 | 9:15 / 跨日沿用快照按**昨收**重算；卡片不回退成本浮盈 |
| 指数空白/对不上 | 新浪批量；代码去前缀对齐；一边失败沿用上次点数 |
| 实仓缺现价仍自动入槽、因子2 权益被失败行情改掉 | `_position_quotes_ready` 为假则不入槽、不 sync 总资产 |
| 已触止损只绿底不平仓；中天/远东该平未平 | **全持仓同一套** `paper_exit_decision`：开盘保护 / 1m / 现价破当前卖价。昨收已过 3% 且今开低于回落一半 → **按开盘平**。禁止用全日最低去撞盘中抬高后的止损。T+1 只记不卖。买入日不算隔夜开盘保护。每轮 `settle_due_paper_stops` 扫全部实仓 |
| 黑猫涨停次日高开被「开盘保护」错卖；半仓记成开盘价 | 开盘保护峰值**不得含今日开盘/盘中新高**（峰值≥今开则回退昨收/成本）。`action_kind=full` 时忽略残留 `ladder_half_10`。1m 路径**跳过 09:30 前竞价 K**。半仓成交价=阶梯策略价。**002068 已按 1m 纠成**：半仓 11.14@09:31 + 峰值回落 10.92@09:32（`correct_realized_false_open_to_path_ladder`） |
| 天通买入日涨停仍标「止损已记」（反复） | **唯一落库口** `persist_stop_noted`：只接受 `hard_from_cost` / `t1_trail`，已记价不得高于成本。展示层禁止写账本。买入日只认现价仍在硬保护；中段卖价 / 今开撞抬高止损 / 盈≥3% / 涨停一律不记。**昨收/昨高**只经 `overnight_peak_px`（须 `overnight_session_high_ok`）；今日新买不用昨高。每轮 `purge_illegal_t1_stop_notes` 自清 |
| 远东平仓价 24.10「好像不对」；中天记成 34.13 | 远东 24.10=今开，规则对。已平仓**卖出侧冻结为成交价**（不要跟盘后止损 24.6）。中天应按开盘 33.84，错账 `correct_realized_open_protect_fill` 纠回 |
| 中国宝安平仓价 6.98（今开 6.88、最高 6.92 从未成交） | 竞价虚拟高 7.03@09:15 抬 HWM → 假中赚 6.98。**竞价不回写峰值**；**09:30–09:32 API high 高于今开/现价/1m 仍当虚高**（`usable_session_high`）；今开已破卖价且当日最高未印到 → **按开盘**；今日竞价戳 `peak_high` 压回已印出价。`correct_realized_open_protect_fill` 纠回 |
| 特发开盘保护卖出记成 09:32；PATH 触达价碰巧=今开被改成 09:30 | **仅** `open_bell` / `exit_kind=open_protect` 记竞价核 `09:30:00`（可覆盖缺 bar 的 09:31/09:32）。**禁止** `fill≈open` 反推开盘时刻；PATH 保持真实 `triggered_at`。见 [`docs/TEMPORAL_INTEGRITY.md`](docs/TEMPORAL_INTEGRITY.md) |

| 盯盘纸面槽位 | **四槽**：`MAX_PORTFOLIO_SLOTS=4`、日最多买 4、每槽约 25%（`SLOT_WEIGHT=0.25`） |
| 策略十六有信号，持仓「预警/其它」没有 | `is_holdings_tab_signal_row`：已触买/将买入/**策略持有**/回放止损 与策略十六图例同一口径；空仓无信号不进；前端拆「预警」与「策略持有」 |
| 触发了但看不到几点几分；入槽/平仓没有先后 | sticky 第一次记下 `buy_hit_ts` / `stop_hit_ts`；已入槽用 `buy_time`；成交/流水用触发时刻不是进程 `_now()`。**先平再买**（本轮平仓立刻补槽）。腾槽：平仓前已触买且现价≤买点+1% 按现价；否则其后新触发按买点 |
| 扫仓补平 `path_hit=False`，以为没有 1m | 5s 刷新就是实盘时钟。本轮行上带 `_path_hit` / `_path_fill_px` / `_path_ts`，扫仓能看见 1m；现价破卖价按**触发点**成交 |
| 改完 Python 页面仍是旧逻辑 | `start_watch` **不热更新**；改账本/结算后必须停掉再开当前进程 |
| 金安国纪 002636 昨日无仓、今日未触买点，09:30 却被「现价」买入并 09:30:15 止损，买单时间记成昨日 09:46（2026-09-29） | 9:15 清空前加载的扫描写卖出防抖时，`_sticky_put` 继承了**昨日** `buy_touched`/`buy_hit_ts` 并把 session 改成今日 → 伪造「今日已触买」+ 触发早于腾槽 → 第一梯队现价买入；buy_time=昨日绕过 T+1。现：粘滞只继承**同 session**（`_sticky_same_session`）；入槽跳过非当日触发（`STALE_BUY_TRIGGER`）；`apply_paper_slot_buy(session=)` 拒收跨日 buy_time。回归 `test_stale_sticky_crossday` |
| 多线程/多进程各自整份写 `holdings.json`，后写的旧数据盖掉先写的新数据（002636 根因） | `holdings_store.HoldingsStore`：进程内账本对象身份稳定；写盘串行（进程锁 + `holdings.json.lock` 文件锁）+ 写前版本检查（mtime_ns+size，被外部改过先三方合并，冲突以磁盘为准）+ 原子替换；容器只 `reset_container` 原地清空；9:15 重置持 `refresh_lock`。回归 `test_holdings_store` |
| 12 点断网，时钟停在 12 点多，没有红色「服务中断」 | 红字以前只认本机 WebSocket。断外网时 `:8765` 仍开、hub 缓存现价还能出表。现按 SSE/新浪是否还在收数打 `quoteStale`/`feedOk`/`quoteAt`；刷新卡住仍 2s 推时钟；前端 `updatedAt`>20s 或 HTTP 失败也红字「行情中断/网络异常/服务停滞」 |

| 禁止 | 正确做法 |
|------|----------|
| 行情全失败就把表写成空 | 沿用上次可用快照，未就绪不覆盖 |
| 有实仓、市值未到，把日初/合计写成仅现金 | 不回写总资产、不锁仅现金日初 |
| 隔夜 `available=0` 当券商不可卖 | `heal_watch_ledger` 解开买入日残留锁 |
| 「已触止损」只展示、或只处理某一只 | `paper_exit_decision` + `settle_due_paper_stops` 扫全部实仓 |
| 用全日最低 / 盘中抬高止损当成交价；已平仓卖出侧继续跟现价止损 | 开盘保护优先；卖出侧=锁定成交价；错账纠回开盘 |
| 竞价虚拟高/昨高残留写进 `peak_high`；从未成交的卖点当平仓价 | 9:15–9:30 **不抬 HWM**；09:30–09:32 API high 高于今开/现价/1m → 丢弃；今开已破卖价且当日最高未印到 → 按开盘；竞价戳脏峰压回 |
| 开盘保护成交时刻用首根 1m（09:31/09:32）；或用 fill≈open 把 PATH 改成 09:30 | 竞价核仅 `open_protect`→09:30；PATH/`triggered_at`/`exit_kind` **immutable** |

| 买入日用今开/中段卖价写「止损已记」，展示层再 persist 写回 | 唯一落库口只要硬保护/T1 哨兵；已记价≤成本；展示只读账本；非法已记每轮自清 |
| 过门触买不进预警；策略 Tab 有、持仓 Tab 无 | `is_today_alert_row` / `is_holdings_tab_signal_row` |
| 指数只按 akshare 表名精确匹配 | 新浪批量 + 失败沿用 |
| 缺现价仍入槽 / 回写因子2 | `_position_quotes_ready` 为假则停 |
| 只看本机 WebSocket 是否连接就当行情正常 | 外网断了也要 `quoteStale` 红字；时钟心跳与行情时刻分开 |
| 改完不重启当已修好 | 必须重启 `start_watch` |

- [x] **2026-09-14 上述防护已进代码**。再改盯盘若绕过这些，视为回归。

### 锁定 · 时间完整性（2026-09-24）

系统级 invariant（非个股补丁）：[`docs/TEMPORAL_INTEGRITY.md`](docs/TEMPORAL_INTEGRITY.md) · [`holdingStocks/temporal_integrity.py`](holdingStocks/temporal_integrity.py)。

| 规则 | 要求 |
|------|------|
| NO LOOK-AHEAD | `decision_at=T` 只用 `timestamp<=T` 的数据 |
| HWM CAUSALITY | `peak_high`+`peak_high_at` 原子更新，且 `peak_high_at<=decision_at` |
| EVENT IMMUTABILITY | `triggered_at`/`filled_at`/`exit_kind` 不得事后改写 |
| STALE DATA | 旧行情不得覆盖较新策略状态 |

- [x] 验收 **TEMPORAL INTEGRITY: PASS**；回归必跑 `cd holdingStocks && python run_regression_tests.py`（含 `test_temporal_integrity`）。
- [ ] **技术债 · Forming 1m 上游行情质量**（独立）：未完成分钟 K 若供应商提前写入最终 high，可能同分钟 look-ahead。**禁止**为修此债再改已验收的 trailing/HWM 因果逻辑；另开任务治理行情源/ bar 完成态。

### 审计登记 · Paper↔Backtest 语义（2026-09-24，只读）

见 [`docs/PAPER_BACKTEST_SEMANTIC_PARITY_AUDIT.md`](docs/PAPER_BACKTEST_SEMANTIC_PARITY_AUDIT.md)。

- [ ] **P0**：勿用 BT-Daily（`half_gain`）验证 Factor26 生产语义；文档钉死「简化研究」。
- [x] **P1**：akquant **PIN_0.3.22**（`requirements.txt`；回归 56 OK）。
- [x] **P1**：BT-1m Contract + Cross Harness（见 TRADING_ENGINE_CONTRACT）；编排 gap（open_protect/path 全链）仍待扩。
- [ ] **P1/P2**：Capital V2 / Fee 与回测不可比，直至显式对齐或降级为信号对照（PHASE CAPITAL/FEE）。

### 架构重定义 · Realtime First（2026-09-24）

见 [`docs/REALTIME_1M_ARCHITECTURE.md`](docs/REALTIME_1M_ARCHITECTURE.md)、[`docs/TRADING_ENGINE_CONTRACT.md`](docs/TRADING_ENGINE_CONTRACT.md)、[`docs/PHASE_LOCK_CONTRACT_REPORT.md`](docs/PHASE_LOCK_CONTRACT_REPORT.md)。

- [x] 目标钉死：Paper=实时成交驱动；正式回测=1m；**禁止**为 parity 降级盯盘粒度。
- [x] 登记并锁定 `CURRENT_INTRABAR_POLICY = PRIORITY_ENVELOPE` + `FACTOR26_EXIT_PRIORITY_1M` 单测。
- [x] Cross-resolution harness + 六类分类（Gate3）；歧义审计 metadata（不改成交）。
- [x] `akquant` **PIN 0.3.22**；回归 157 OK。
- [x] **Gate4 FULL_EXIT_ORCHESTRATION**：open_protect→path→last 竞争矩阵 + RealtimeFullExitRunner（生产函数）；见 PRODUCTION_EXIT_ORCHESTRATION_CONTRACT。
- [ ] 历史 quote 事件流充足后补 Production Replay（当前 INSUFFICIENT_REPLAY_DATA）。
- [ ] PHASE CAPITAL / FEE / PNL；SHARED PURE CORE EXTRACTION（编排 PASS 后允许启动）。
