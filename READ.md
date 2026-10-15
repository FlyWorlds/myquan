# myquan - 基于 AKQuant 的 A 股量化盯盘与回测项目

本项目基于 [AKQuant](https://github.com/akfamily/akquant) 构建，面向 A 股策略研究、回测、模拟盘盯盘和纸面交易状态管理。

当前主线是 **策略十六：因子27 核心龙头池 + 因子26 多层止盈 + 因子29 竞价末段按开盘撮合 + 因子2 回撤预警**。盯盘端支持分阶段异步加载：先出持仓，再出默认策略，最后补齐其它策略和观察池。

## 快速启动

### 一键启动（推荐，macOS/Linux）

在项目根目录执行：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan
bash start.sh
```

Mac 也可以双击根目录的 `start.command`。启动器依次检查 MySQL、启动/核验 Java、检查数据库账户，再启动 Python；日常前端由 Python 提供，打开 `http://127.0.0.1:8765/`。命令完成后服务在后台运行，关闭启动终端不会停止服务。

```bash
bash start.sh --status                 # 查看状态
bash start.sh --stop                   # 停止启动器管理的服务，保留 MySQL
bash start.sh --restart                # 重启启动器管理的服务，代码修改后使用
bash start.sh --ui-dev                 # 开发模式：Nuxt 前端 :3000
bash start.sh --no-open                # 不自动打开浏览器
bash start.sh --no-wechat              # 关闭微信通知，不改变模拟交易逻辑
```

- 已有服务须通过本项目目录和健康接口核验后才复用；不会强制杀掉占用端口的未知进程。重复执行不会重复启动交易进程。
- 之前手工启动的服务只复用、不接管；`--stop` 不会停止它们，仍需在原终端 `Ctrl+C`。启动器自己启动的服务才纳入停止管理，停止顺序为前端 → Python → Java。
- Mac 的 Homebrew MySQL 未运行时会尝试启动；Linux 或其它数据库安装方式须先启动数据库。没有数据库账户时会停止启动，不自动导入本地持仓或重置账户。
- Java JAR 缺失或源码更新时自动编译并测试；按源码与产物内容摘要判断，不依赖可复现JAR的固定时间戳。静态前端缺失或源码更新时自动构建，已有最新构建时跳过编译。
- Python 不自动安装依赖：优先使用项目 `.venv/bin/python`，其次本机 `/opt/homebrew/bin/python3`；必须已经安装项目依赖。可显式指定：

```bash
MYQUAN_PYTHON=/path/to/project/python bash start.sh
MYQUAN_NODE=/path/to/node bash start.sh --ui-dev
```

- 会检查 Python 的 pandas、AKShare、AKQuant 能否导入，AKQuant版本与requirements不一致时明确提示，不自动升级用户环境。启动接口就绪不等于依赖版本与回测口径已通过审核。
- 首次前端构建/开发需要 Node 22.12+、npm；缺少前端依赖时执行 `npm ci`。后端构建需要 JDK 21+、Maven。构建依赖下载需要网络。
- 日志及进程管理记录位于 `backend/logs/project-launcher/`，不提交 Git；启动失败只清理本次新启动的应用进程，保留已有服务与 MySQL。
- `--status` 中 Java/Python 就绪表示接口可用，仍可能正在预热行情和策略，不等于交易数据全部就绪。
- 可使用 `--backend-port`、`--port`、`--ui-port` 指定不同端口。已有启动器管理的服务变更端口前，先 `--stop`。本入口仅面向本机服务；Windows 暂使用下面的分步方式并替换路径/命令。

### 各服务的职责与启动顺序

**MySQL → Java 后台 → Python 盯盘 → 打开前端页面**。日常运行只需两个终端：Java 一个，Python 一个；MySQL 为后台服务，前端静态页面由 Python 一起提供，不必另外启动 Node。

| 服务 | 职责 | 本机地址 |
| --- | --- | --- |
| MySQL | 保存持仓、现金、成交流水、交割记录和账户统计 | `127.0.0.1:3306/myquan` |
| Java / Spring Boot | 连接数据库，提供账户读写、版本校验和事务接口 | `http://127.0.0.1:8080` |
| Python | 拉行情、运行策略/模拟交易，提供页面、API 和 WebSocket | `http://127.0.0.1:8765` |
| 前端日常模式 | 已构建的 Nuxt 页面，由 Python 提供 | `http://127.0.0.1:8765/` |
| 前端开发模式 | Nuxt 热更新服务，仅修改前端时使用 | `http://127.0.0.1:3000/` |

当前实际项目根目录为 `/Users/wangxiangyu/Documents/akquan回测/myquan`。以下命令针对这台 Mac；其它设备替换为自己的项目路径和已安装依赖的 Python。Java 后台需要 JDK 21+、Maven 3.6.3+；前端开发/构建建议 Node 22.12+。日常静态模式不需要启动 Node。

### 1. 启动数据库

本机使用已有的 Homebrew MySQL，不需要新建或清空数据库：

```bash
brew services start mysql
brew services list
```

确认 `mysql` 状态为 `started` 即可，已运行时不用重启。连接配置位于 `backend/config/application-local.properties`；数据库名默认 `myquan`，端口默认 `3306`。HexHub 只是数据库管理工具，打开 HexHub 不代表 MySQL 服务已启动。

### 2. 启动 Java 后台（终端一）

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan
bash backend/run.sh
```

保持该终端运行。另开终端检查连接：

```bash
curl http://127.0.0.1:8080/actuator/health
curl http://127.0.0.1:8080/api/system/status
curl http://127.0.0.1:8080/api/paper/state
```

健康检查应返回 `UP`，完整账户接口应返回持仓与版本号。启动会自动执行尚未应用的 Flyway 表结构迁移。本机账户已迁入数据库，**不要再次执行导入、账户重置或清库**。其它设备首次使用空库时，需要另行确认账户初始化/迁移；只拉取 Git 代码不会带上 MySQL 数据。

### 3. 启动 Python 与日常前端（终端二，推荐）

本机已经安装项目依赖的 Python 为 `/opt/homebrew/bin/python3`：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan
HOLDINGS_STORAGE=database PAPER_BACKEND_URL=http://127.0.0.1:8080 /opt/homebrew/bin/python3 holdingStocks/index.py watch --no-ui-dev --wechat-optional
```

`--no-ui-dev` 使用已构建的前端；`--wechat-optional` 使微信自检失败不阻止盯盘启动，但不表示微信通知已成功。需要完全关闭通知时改用 `--no-wechat`。不想自动打开浏览器时再加 `--no-open`。

打开以下地址：

- 前端：[持仓与策略页面](http://127.0.0.1:8765/)
- 板块轮动：[板块页面](http://127.0.0.1:8765/sectors)
- 交割单：[成交页面](http://127.0.0.1:8765/trades)
- 账户数据库接口：`http://127.0.0.1:8765/api/holdings/state`
- WebSocket：`ws://127.0.0.1:8765/ws`

该模式前端与 Python 共用 `8765`，不需要运行 `npm run dev`。行情、日线及策略数据会分阶段补齐；缺行情期间的收益空值不是 0%，不能用来判断交易数据已就绪。

### 前端开发模式（替代上述 Python 命令）

仅在修改 Vue/TypeScript 页面、需要热更新时使用。MySQL 和 Java 仍按前两步启动，Python 改用：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan
/opt/homebrew/bin/python3 holdingStocks/index.py watch --ui-dev --wechat-optional
```

Python 会尝试启动 Nuxt 开发服务；前端打开 `http://127.0.0.1:3000/`，Python API 仍为 `8765`。不要同时再启动另一个 Python 盯盘进程。首次缺前端依赖时，先在 `holdingStocks/watch-ui` 目录执行 `npm ci`。

如需自己控制前端进程：Python 用 `--no-ui-dev`，另开终端三执行：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan/holdingStocks/watch-ui
npm run dev
```

此时开发页面也打开 `3000`，请求通过 Nuxt 配置转发到 Python。Java 不是 Nuxt 的直接替代服务；只启动 Java，页面不会获得实时行情和策略结果。

### 修改代码后如何生效

- Python：在对应终端 `Ctrl+C`，重新执行 Python 启动命令。
- Java：在对应终端 `Ctrl+C`，重新执行 `bash backend/run.sh`。
- 前端开发模式：Vue/TypeScript 修改通常自动热更新。
- 前端日常模式：需要先重新构建静态页面，然后刷新浏览器：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan/holdingStocks/watch-ui
npm run build
```

构建脚本会将产物复制到 `dist`，供 Python 的 `8765` 页面使用。若提示缺少 `dist`，也先执行该构建命令；不要把未构建页面当作服务启动失败。

### 停止与常见问题

正常停止顺序：先停止 Python，再停止 Java；MySQL 可继续作为本机服务运行。确需关闭数据库时执行 `brew services stop mysql`。

| 问题 | 检查与处理 |
| --- | --- |
| `8080` / `8765` / `3000` 端口占用 | 先确认原进程是否已运行，不要重复启动或直接加 `--force` |
| Java 提示数据库连接失败 | 检查 `brew services list`、MySQL 端口和本地配置文件 |
| Python 提示数据库不可用或未迁移 | 先检查 Java 的 `/api/paper/state`；生产模式不回退本地文件 |
| `No module named ...` | 使用已安装项目依赖的 Python；本机不要混用不同版本的 `python` / `python3` |
| Nuxt / Node 版本错误 | 确认 `node --version`；日常运行可用 `--no-ui-dev` 避免依赖开发服务器 |
| 页面有持仓但行情/收益空白 | 等待有效行情与完整扫描补齐，并检查行情源健康状态 |
| 另一台设备没有相同持仓 | 必须访问同一个 Java 后台/数据库；各自的 `localhost` 不是同一个数据库 |

检查本机监听端口：

```bash
lsof -nP -iTCP:8080 -iTCP:8765 -iTCP:3000 -sTCP:LISTEN
```

停止旧进程应优先使用其终端的 `Ctrl+C`。当前仅本机访问，不要直接将无认证的后台暴露到公网。

### 其它启动入口与日志

旧脚本只负责 Python 盯盘及前端，不会代替启动 MySQL / Java：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan/holdingStocks
/opt/homebrew/bin/python3 start_watch.py --no-wechat
/opt/homebrew/bin/python3 start_watch.py --stop
```

启动日志应依次出现：

```text
持仓首屏已推送
默认策略快照已推送
全量快照已推送
```

日线预热线程数可调：

```bash
WATCH_DAILY_WARM_WORKERS=16 /opt/homebrew/bin/python3 holdingStocks/index.py watch --no-ui-dev --wechat-optional
```

## Java 后台与本地数据库

数据库备份与恢复验证：`python backend/backup_database.py --verify-restore`（恢复至独立测试库，不覆盖当前库）。只读账户/策略对账：`python holdingStocks/audit_database_account.py`，输出 `backend/logs/account-audit.json`。第一批逻辑审查及尚待补证的历史问题见 `docs/ACCOUNT_DB_AUDIT_20261014.md`。

新增独立目录 [`backend/`](backend/README.md)：Java 21 语言目标、Spring Boot 3.5.16、JDBC/HikariCP、Flyway，连接本地 MySQL `127.0.0.1:3306/myquan`。数据库使用截图中确认的 MySQL，不再按此前 PostgreSQL 建设建议实施。

从项目根目录启动：

```bash
bash backend/run.sh
```

- 健康检查：`http://127.0.0.1:8080/actuator/health`
- 数据库状态：`http://127.0.0.1:8080/api/system/status`
- 测试/打包：`bash backend/run.sh test` / `bash backend/run.sh package`
- 本机用户名和密码固定写在 `backend/config/application-local.properties`，按用户要求纳入 Git，仅用于本地开发；其他机器可修改该文件或使用 `SPRING_DATASOURCE_USERNAME`、`SPRING_DATASOURCE_PASSWORD` 覆盖，不要在公网环境复用。

后台与 Python 盯盘独立启动，先启动 Java 后台，再启动原来的盯盘命令。持仓、现金、成交流水和交割明细已切换为 MySQL 权威账本，默认 `HOLDINGS_STORAGE=database`，Java API 地址由 `PAPER_BACKEND_URL` 指定（默认 `http://127.0.0.1:8080`）。前端经 `/api/holdings/state` 请求 Java 后端读取数据库；行情仍走实时行情源。买卖会将持仓、现金和交割记录在同一数据库事务中写入，数据库不可用时阻断更新，不回退本地文件。

完整账本表 `paper_account_state` 保存账户与全部状态；`paper_holdings`、`paper_trade_history`、`paper_delivery_entries` 是同事务更新的查询表，不要直接修改这些投影表。初始化迁移仅执行一次：`POST /api/paper/state/migrate`，已迁移后返回409，旧 `/api/holdings/sync` 禁止覆盖数据库。修改接口 `PUT /api/paper/state` 要求版本号和幂等请求ID。原本地文件保留为迁移备份，不再用于生产更新。所有设备必须配置同一个后端，不能各用自己的 localhost 数据库期待自动同步；当前建议只运行一个交易写入进程。

账户统计已加入 `paper_account_snapshots`：盯盘运行时，每分钟异步记录首个完整的总收益、今日收益（金额及百分比）、仓位比例、现金、持仓市值、总资产与持仓/今日平仓明细。缺失行情不伪装成零，不反造过去的统计历史。数据库模式总资产按“数据库现金＋持仓市值”计算，不用今日盈亏倒推现金；今日盈亏包含分批卖出的全部已实现盈亏，保留与日初权益锚的差额便于对账。查询 `http://127.0.0.1:8765/api/holdings/history`。平仓交易本来已在交割表中，新增 `paper_closed_trades` 视图与 `/api/holdings/closed` 查询；其中末笔盈亏不是整笔综合收益，分批卖出仍须查询全部交割记录。

## 启动加载顺序

盯盘冷启动分三段，目的是先让页面可用，再补齐重数据：

1. **持仓首屏**：只加载实仓、今日已实现和用户登记持仓池。
2. **默认策略**：加载策略16核心龙头热池和公共自选池。
3. **全量补齐**：后台补策略一池、策略16B动态池、策略17叠加观察池、策略3/8/15面板、板块轮动和画像缓存。

这些任务不再阻塞首屏：

- 股票名称缓存预热
- 个股画像/板块反查
- 策略3/8/15快照面板
- 策略17叠加观察池
- 板块轮动

行情 seed 与日线缓存预热并行执行；新浪批量失败时仍会按票兜底拉日线。

## 当前默认交易逻辑

| 模块 | 当前口径 |
| --- | --- |
| 默认策略 | **策略16 核心龙头** |
| 选股池 | 因子27 近3个月核心龙头池 + 公共自选池 |
| 买入 | 因子29：9:20–9:25 路径达阈值则按正式开盘买；否则因子26 开盘阈值买入，1m path-dependent |
| 卖出 | 因子29 竞价末段达阈值则按正式开盘卖（T+1）；其余走因子26 多层止盈/止损 |
| 预警 | 因子2 回撤加减仓预警 |
| 因子22 | 默认关闭，仅研究对照 |
| 仓位 | Capital V2，模拟盘纸面交易，不接券商 |

因子26退出规则摘要：

- 硬保护 2.5%，低开已破按开盘。
- 中赚 3-10%：回落一半与 `0.5 x 20日日频sigma` 谁先到走谁。
- 10% 半仓止盈，15% 全清。
- 大赚后回落 2% 清仓。
- 买入日未到 3%，次日按隔夜高点回落 2.5%，不得低于硬保护。
- T+1：买入当日不卖，卖出当日通常不买回。**策略十六例外**：前一日止损已记、次日竞价低开走开盘保护全清后，当天过门触买允许回补（仍占日新开额度）。

## 策略16 与策略16B

### 策略16

策略16是当前默认交易池：

- 因子27核心龙头池，默认近3个月。
- 主板、非 ST、价格上限等条件由策略固定参数过滤。
- 交易内核使用因子26；**因子29** 可在 9:20–9:25 武装后按正式开盘成交。
- 策略模拟器买入成交价记买点（因子29 记正式开盘），现价只盯市。发现时刻的现价不算入场价，避免策略持有但单笔收益和策略累计停在 0。行情快刷改入场前要用该股自己的买入阈值；快照里没有阈值时先查 `backtest/strategy16_core_leader/thr_2026.json`，仍缺失才兜底默认 2.5%。
- 公共自选池全策略共用。
- 隔夜已记止损、次日竞价低开开盘保护卖出后，当天过门可回买。

刷新核心龙头池：

```bash
python strategy/run_core_leader_pool.py
```

### 策略16B

策略16B复刻策略16的买卖内核，但选股条件可以在页面里动态配置，从全A重新过滤：

- 回看月份：1/2/3/6 等。
- 概念数量、每概念数量、目标池大小。
- 价格上限。
- 非 ST、排除创业板、排除科创板、排除北交所。

页面位置在策略16右侧。点击“生成”后，后端会调用：

```text
GET /api/strategy16b/select
```

生成结果会进入策略16B Tab 和动态盯盘池，不覆盖策略16正式池。

## 盯盘页面说明

| Tab | 说明 |
| --- | --- |
| 持仓 | 实仓/今日平仓/纸面交易状态，Capital V2账户摘要 |
| 策略1 | 研究池，按距买点排序 |
| 策略3 | T-1连板梯度情绪 + 首板晋级跟踪 |
| 策略8 | 当日涨停实时定题材 |
| 策略15 | 连板减磨损与震荡处理 |
| 策略16 | 默认核心龙头交易池 |
| 策略16B | 条件可配置的核心龙头动态池 |
| 策略17 | 紫阳真君叠加观察池，非默认交易池 |

重要口径：

- `holdings_watch.json` 是本机快照缓存，不是账本真源。
- 纸面账本、交易和状态文件不要手工乱改。
- Win/Mac 持仓共享须连接同一 Java 后端/MySQL；不再通过 Git 同步持仓。
- 外网行情断开时，本机 WebSocket 仍可能正常，页面以 `quoteStale` / `feedOk` 显示行情健康。
- 微信扫描预警与纸面/策略模拟自动成交只在 **A 股交易日连续竞价**；周末和交易所休市日不推扫描预警、不成交（`market_phase=closed`）。
- 纸面买入分两条：因子26 只认今日核定开盘突破买点；**因子29** 只用 9:20–9:25 路径决定是否买，成交价锁正式开盘。**9:15–9:19 竞价指示价不参与买卖**，9:25 重置正式 OHLC 但保留竞价末段路径；9:30 必须已有新报价。候选触买后再**单独拉该股票行情复核开盘价**，与聚合行情按 tick 一致才过门；Paper 落账前再强制拉一次。接口失败、日期/时刻未核定、开盘失配或成交价低于买点均拒绝。

## 常用命令

### 回测

```bash
# 策略一规则
python backtest/strategy1.py --rules

# 策略16核心龙头池近7日1m回测
PYTHONPATH=. python backtest/strategy1_pool_1m/run.py --pool strategy16 --days 7 --fit-thr

# 策略16指定日期区间复算，按完整买入周期合并分批卖出并核对现金/权益
python backtest/strategy16_core_leader/run_month_review.py --start 2026-10-01 --end 2026-10-13
# 包含今天盘中已完成分钟，各股票截到共同时间估值（end 须为今天）
python backtest/strategy16_core_leader/run_month_review.py --start 2026-10-01 --end 2026-10-14 --intraday
# 全池等权：30万元均分每只股票，独立资金，不受5槽/日增2只限制
python backtest/strategy16_core_leader/run_month_review.py --start 2026-10-01 --end 2026-10-14 --intraday --all-pool
# 同区间追加 --offline 使用已保存分钟数据；产物位于 strategy16_core_leader/review_<起日>_<止日>/
# 固定当前池/当前阈值，未重建历史选股；阈值拟合窗重叠时属于样本内复算，不含竞价路径。

# 策略16个股阈值拟合（{2%,2.5%,3%} 日线开盘突破夏普择优；缺样本兜底2.5%）
PYTHONPATH=. python backtest/strategy16_core_leader/fit_thr.py

# 因子22同日再买对照
PYTHONPATH=. python backtest/strategy16_core_leader/compare_f22.py --days 7

# 低开破硬保护对照
PYTHONPATH=. python backtest/strategy1_pool_1m/compare_hard_gap.py --pool strategy16 --days 7
```

### 因子池

```bash
# 策略16核心龙头池
python strategy/run_core_leader_pool.py

# 策略17紫阳真君池
python strategy/run_ziyang_pool.py
```

### 持仓同步

```bash
cd holdingStocks
# 重新读取数据库持仓
python index.py holdings-pull
```

持仓账本已经切换为数据库。生产模式的 `holdings-push` 与旧 Git pull 不再可用；`holdings-pull` 只刷新数据库读取。盯盘启动检查数据库账本，失败即停止。`--no-ledger-pull` 只跳过启动检查，不会切回本地文件。离线测试须显式设置 `HOLDINGS_STORAGE=local_json`，不得用于多设备实盘模拟同步。策略16/16B 的独立 simulator 文件此次未迁库，不能将它与纸面持仓账户混为一谈。

## 验证命令

推荐使用：

```bash
python -m py_compile holdingStocks/index.py
python -m unittest holdingStocks.test_watch_boot_perf holdingStocks.test_strategy16b_dynamic
python holdingStocks/runtime_integrity.py --strategy16-start-date 2026-10-08
python holdingStocks/run_all_tests.py --skip-pytest-if-missing
```

当前系统默认 `python3` 可能缺 `pandas` / `akshare`，不要用它判断项目是否坏了。

安装依赖：

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 项目结构

```text
myquan/
├── READ.md                         # 根目录说明
├── TODO.MD                         # 任务与锁定项
├── docs/                           # 策略、因子、架构和审计文档
├── strategy/                       # 因子、策略注册表、策略绑定和选股池生成
├── backtest/                       # 回测、对照实验和报告产物
├── holdingStocks/                  # 盯盘、模拟盘账本、HTTP/WS、微信通知
├── holdingStocks/watch-ui/         # Nuxt 前端
├── sectors/                        # 板块/概念数据
└── data_cache/                     # 本地行情缓存
```

关键文档：

- [架构说明](docs/ARCHITECTURE.md)
- [策略专题](docs/STRATEGY.md)
- [策略注册表](strategy/README.md)
- [因子26](docs/FACTOR26.md)
- [因子27](docs/FACTOR27.md)
- [因子28](docs/FACTOR28.md)
- [因子29](docs/FACTOR29.md)
- [盯盘说明](holdingStocks/README.md)
- [时间完整性](docs/TEMPORAL_INTEGRITY.md)
- [交易引擎契约](docs/TRADING_ENGINE_CONTRACT.md)
- [退出编排契约](docs/PRODUCTION_EXIT_ORCHESTRATION_CONTRACT.md)

## AKQuant 接入方式

AKQuant 是 Rust 内核 + Python 策略层的混合量化框架。本项目主要使用 Python 侧能力，同时保留自定义实时盯盘和纸面交易状态。

典型数据流：

```text
akshare DataFrame
  -> normalize / load_bar_from_df
  -> Bar
  -> Strategy.on_bar
  -> Execution / Statistics
  -> BacktestResult
```

本项目策略分层：

```text
因子层 factors
  -> 策略绑定 bindings
  -> 决策层 decision
  -> 执行层 runner / backtest / watch
```

最小 AKQuant 示例：

```python
import akquant as aq
from akquant import Strategy, CurrentClose


class MyStrategy(Strategy):
    def on_bar(self, bar):
        if self.get_position(bar.symbol) == 0 and bar.close > bar.open:
            self.buy(symbol=bar.symbol, quantity=100)


result = aq.run_backtest(
    data=df,
    strategy=MyStrategy,
    symbols="sh600000",
    initial_cash=100_000.0,
    lot_size=100,
    t_plus_one=True,
    fill_policy=CurrentClose(),
)
```

## 策略与因子注册表（摘要）

完整真源：[`strategy/README.md`](strategy/README.md) · 专题：[`docs/STRATEGY.md`](docs/STRATEGY.md)。改策略/因子时同步更新注册表、`docs/` 与本文。

当前默认 **strategy16**；**strategy16B** 复刻同一买卖内核，页面动态选股，不覆盖正式池、不入默认四槽。

---

## 开发约定

- 改策略/因子时，同步更新 `strategy/README.md`、`docs/` 和本文。
- 不要把 `holdingStocks/strategy_sim_state.json`、`holdingStocks/strategy_signal_events.json`、运行快照和旧账本文件当普通代码改；纸面账户由MySQL保存，独立策略simulator仍是运行态文件，未迁入本次账户库。
- 提交前至少跑 `holdingStocks/run_all_tests.py --skip-pytest-if-missing`。
- 涉及前端时，再跑 `holdingStocks/watch-ui` 的构建或本地 dev 验证。
