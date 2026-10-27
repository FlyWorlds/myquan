# myquan - 基于 AKQuant 的 A 股量化盯盘与回测项目

本项目基于 [AKQuant](https://github.com/akfamily/akquant) 构建，面向 A 股策略研究、回测、模拟盘盯盘和纸面交易状态管理。

当前主线是 **策略一：因子13A 质量带 + 因子16 龙头排序 Top20 + 因子26 多层止盈 + 因子29 竞价末段 + 因子2 回撤预警 + 因子22 收盘动量**。盯盘端支持分阶段异步加载：先出持仓，再出默认策略一，最后补齐其它策略和观察池。策略十六遗留实仓继续按策略一卖出规则盯到平仓，卖出后清空、不回买。

## 报价驱动（盯盘公共）

行情、数据库读取/写入与核对时机统一遵循 [数据使用边界](docs/DATA_SOURCE_CONTRACT.md)：观察价、估值价、成交价分开；数据库参考读取不是新交易事件；页面与账本先对齐版本和时点再比较。

报价驱动是盯盘公共执行（`watch_config.QUOTE_DRIVEN_ENABLED`），与选股策略解耦。默认策略一池也走 **实时行情事件 + MySQL账户状态**：启动、列表刷新、条件买入和因子26卖出不拉1分钟K线。日线与正式开盘审核后台准备，未就绪不买；持仓及现价先显示，不等待日线。因子29 竞价开盘撮合已挂策略一与策略十六。

实时价格先进入独立接收队列，后台按最多64条/批写入MySQL `market_quote_latest`，确认成功后才通知默认策略池的买卖、估值和页面读取缓存。接收线程不等数据库；写入失败不回退本地成交。相同股票连续不同价格按接收顺序处理，不合并掉瞬时冲高；最新表不是完整逐笔历史。当前东财SSE没有经过核验的源时间戳，仅用于原始展示/连接健康，不参与成交；成交计算只消费已入库、保留新浪源时间戳的快照。持仓优先的首批50只独立轮询，其它批次慢不会拖住首批刷新。

客户端成交前同时校验源报价和原始接收时间均不超过5秒，等待平仓/资金计算后重检；Java对新实时成交在入库时再检查服务端时间，过期拒绝。成交记录分开保存挂单价、实收现价、源时间、原始接收时间、决策时间和报价数据库版本。该5秒是过期拒绝上限，不是延迟保证；实际往返时间可查看快照 `quoteStorage` 和成交流水。新表由V7迁移在下次Java启动时创建，本轮没有重启现有服务。

- 9:25后准备过门空仓条件单，9:30后新鲜现价>=挂单价即按挂单价模拟买入；按收到的触发顺序竞争，遵守每日新增2只、同时最多5只等配置。
- 主板正式开盘较昨收上涨>=9.7%时禁买；20%/30%涨停幅度使用对应19.7%/29.7%边界。这是保守的竞价近涨停过滤，不是全天一字板证明。
- 因子26按观测现价更新峰值和卖出判断，保留T+1、半仓及全清规则。下穿保护跳价按观测现价成交；上行阶梯仍保留原目标价纸面成交假设。
- 挂单、峰值、阶段、现金、成交和交割记录保存数据库；状态改变才写入，不逐报价存整份账户。失败不回退本地成交，旧扫描器不并行买卖。
- 今日最高/最低保留展示及校验，不事后补造成交；分钟线只在独立回测/研究进程使用。策略列表收益改读数据库独立策略账本，买卖与现价按金额计算；旧本地检查点保留并标记历史待核验，不再自动分钟bootstrap。
- 页面首次有效快照渲染完成并通知后端后，延迟15秒启动可选分钟备份；9:15–9:40不发起任务。独立低优先级子进程按持仓→策略池顺序单并发采集，每只成功后30分钟内不重复、失败退避5分钟，单次上限20秒；不扫描全A。数据仅追加到 `data_cache/research_minutes.sqlite3`，记录来源、采集时间和实得范围，不承诺已有整月或完整交易日，不接入实时成交或估值。可用 `MINUTE_BACKUP_ENABLED=0 bash start.sh --service python` 关闭；没有浏览器渲染通知则不启动备份。

详见 [报价驱动边界](docs/QUOTE_DRIVEN_STRATEGY16.md)、[策略数据库收益口径](docs/STRATEGY_DATABASE_ACCOUNTING.md)、[价格与时效复审](docs/SIGNAL_PRICE_TIMELINESS_REVIEW_20261015.md)。本次同时更新Java接口和Python，审核后依次执行 `bash start.sh --service java`、`bash start.sh --service python`；代码不会热替换旧进程，盘中替换有短暂观测空窗。

## 快速启动

### 同花顺模拟盘对照

每个交易日9:25后，项目按现有策略准备过门且空仓的条件单，仍须等待正式开盘价审核和日线准备完成，不保证9:25:00全池就绪。查看 [条件单对照清单](http://127.0.0.1:8765/api/condition-buy/report)，下载 [CSV](http://127.0.0.1:8765/api/condition-buy/report.csv)。接口只读已发布的数据库条件单状态，不拉分钟线、不重算目标价、不下单；旧日期或9:25前不提供可挂单CSV。清单为已准备部分，`complete=false`，代码排序不是触价先后。

只有 `ARMED` 可用于核对新挂单；`BLOCKED`、`CANCELLED`、`FILLED` 不是新买入建议。导出包含正式开盘、阈值、目标价、过门依据、源行情和武装时间，并预留同花顺挂单/触发/成交时间、实际成交价和数量。`entry_pct` 为小数（0.025表示2.5%）。项目按目标价纸面成交不代表同花顺能以同价成交，跳空、委托延迟及未成交分别记录，不能倒改账本使结果一致。服务须提前启动并保持机器唤醒；聊天提醒不能替代行情服务，休市不出清单。新接口需替换Python服务后生效。

统一使用根目录启动器：可以一键启动全部，也可以单独启动/替换某个服务，其余服务保持运行。旧的盯盘组合启动脚本已移除；Python不再自动启动Nuxt，不强制抢占未知进程的端口。

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
bash start.sh --wechat-login           # 在当前终端强制微信扫码登录
```

需要扫码时，点击页面右上角主题切换旁的「微信连接」，生成二维码后用微信扫一扫，也可点击「打开扫码链接」。页面会显示等待扫码、手机确认和连接成功状态；已有通道可点「重新扫码连接」。扫码成功后给机器人发一条消息以刷新预警会话。弹窗中的「测试微信推送」会向已配置的接收人发送一条测试消息，并显示实际发送结果；发送期间不能重复点击。也可在项目终端运行 `bash start.sh --wechat-login` 使用终端扫码；默认启动不等待终端扫码，后台自检结果记录在 `backend/logs/project-launcher/python.log`。

### 单独启动 / 替换服务

一键启动后，需要更新哪个服务就执行哪个命令。选中的服务不存在时启动，已由启动器管理时替换；不连带启动或重启其它服务：

```bash
bash start.sh --service java            # 编译检查后替换Java，Python和前端保持运行
bash start.sh --service python          # 替换Python，Java和前端保持运行
bash start.sh --service frontend        # 沿用前端模式：更新静态构建或替换已有Nuxt
bash start.sh --service frontend --ui-dev     # 单独启动/替换Nuxt开发服务
bash start.sh --service frontend --ui-static  # 更新静态构建，停掉已管理Nuxt，Python不重启
bash start.sh --service python --stop   # 仅停止Python
```

单服务命令本身就会替换旧实例，无需先整体 `--stop`。依赖必须已就绪：Python要求Java与账户可读取，前端要求Python可用；缺少依赖时明确报错，不替用户重启其它服务。构建和依赖检查发生在停止旧实例之前，准备失败保留旧服务；新进程启动失败只清理新实例，所选服务会暂时不可用，修复后重试，不承诺自动回滚。

默认前端是Python托管的静态文件，没有独立前端进程；单独更新前端后刷新浏览器即可。Java/Python替换期间相应接口会短暂不可用，Python行情预热需要重新进行，盘中谨慎执行。替换Python默认沿用原微信通知开关，可显式加 `--no-wechat` 或 `--wechat`。不会清空或重新导入数据库账户，也不结束手工启动的未知服务。服务之间仍依赖原端口，单服务替换不能改掉仍被其它已管理服务使用的端口。

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

### 服务职责

一键启动顺序为 **MySQL → Java后台 → Python盯盘 → 前端页面**。服务在后台运行；单独更新使用上面的 `--service` 命令，默认静态页面不必另外启动Node。

| 服务 | 职责 | 本机地址 |
| --- | --- | --- |
| MySQL | 保存持仓、现金、成交流水、交割记录和账户统计 | `127.0.0.1:3306/myquan` |
| Java / Spring Boot | 连接数据库，提供账户读写、版本校验和事务接口 | `http://127.0.0.1:8080` |
| Python | 拉行情、运行策略/模拟交易，提供页面、API 和 WebSocket | `http://127.0.0.1:8765` |
| 前端日常模式 | 已构建的 Nuxt 页面，由 Python 提供 | `http://127.0.0.1:8765/` |
| 前端开发模式 | Nuxt 热更新服务，仅修改前端时使用 | `http://127.0.0.1:3000/` |

当前实际项目根目录为 `/Users/wangxiangyu/Documents/akquan回测/myquan`。以下命令针对这台 Mac；其它设备替换为自己的项目路径和已安装依赖的 Python。Java 后台需要 JDK 21+、Maven 3.6.3+；前端开发/构建建议 Node 22.12+。日常静态模式不需要启动 Node。

### 手工调试：启动数据库

本机使用已有的 Homebrew MySQL，不需要新建或清空数据库：

```bash
brew services start mysql
brew services list
```

确认 `mysql` 状态为 `started` 即可，已运行时不用重启。连接配置位于 `backend/config/application-local.properties`；数据库名默认 `myquan`，端口默认 `3306`。HexHub 只是数据库管理工具，打开 HexHub 不代表 MySQL 服务已启动。

### 手工调试：Java后台（终端一）

以下直接运行方式仅供调试，不会接管一键启动器管理的服务。需要替换已有服务时使用 `--service`，不要同时启动第二个实例。

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

### 手工调试：Python（终端二）

本机已经安装项目依赖的 Python 为 `/opt/homebrew/bin/python3`：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan
HOLDINGS_STORAGE=database PAPER_BACKEND_URL=http://127.0.0.1:8080 /opt/homebrew/bin/python3 holdingStocks/index.py watch --no-ui-dev --wechat-optional
```

Python默认托管已构建的前端，不启动Nuxt；`--no-ui-dev` 仅保留为显式兼容参数。`--wechat-optional` 使微信自检失败不阻止盯盘启动，但不表示微信通知已成功。需要完全关闭通知时改用 `--no-wechat`。不想自动打开浏览器时再加 `--no-open`。

打开以下地址：

- 前端：[持仓与策略页面](http://127.0.0.1:8765/)
- 板块轮动：[板块页面](http://127.0.0.1:8765/sectors)
- 交割单：[成交页面](http://127.0.0.1:8765/trades)
- 账户数据库接口：`http://127.0.0.1:8765/api/holdings/state`
- WebSocket：`ws://127.0.0.1:8765/ws`

该模式前端与 Python 共用 `8765`，不需要运行 `npm run dev`。行情、日线及策略数据会分阶段补齐；缺行情期间的收益空值不是 0%，不能用来判断交易数据已就绪。

### 手工调试：前端开发（终端三）

仅在修改 Vue/TypeScript 页面、需要热更新时使用。MySQL、Java和Python须先就绪，Python不创建前端进程。另开终端三执行：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan/holdingStocks/watch-ui
npm run dev
```

首次缺前端依赖时先执行 `npm ci`。开发页面打开 `http://127.0.0.1:3000/`，请求通过 Nuxt 配置转发到 Python `8765`。不要同时再启动另一个 Python 盯盘进程。Java 不是 Nuxt 的直接替代服务；只启动 Java，页面不会获得实时行情和策略结果。一键开发模式统一用根目录 `bash start.sh --ui-dev`。

### 修改代码后如何生效

- Python：`bash start.sh --service python`。
- Java：`bash start.sh --service java`。
- 前端开发模式：Vue/TypeScript 修改通常自动热更新。
- 前端日常模式：`bash start.sh --service frontend`，然后刷新浏览器。手工调试也可直接构建：

```bash
cd /Users/wangxiangyu/Documents/akquan回测/myquan/holdingStocks/watch-ui
npm run build
```

构建脚本会将产物复制到 `dist`，供 Python 的 `8765` 页面使用。若提示缺少 `dist`，也先执行该构建命令；不要把未构建页面当作服务启动失败。

### 停止与常见问题

正常停止顺序：先停止 Python，再停止 Java；MySQL 可继续作为本机服务运行。确需关闭数据库时执行 `brew services stop mysql`。

| 问题 | 检查与处理 |
| --- | --- |
| `8080` / `8765` / `3000` 端口占用 | 先确认原进程是否已运行；启动器管理的服务用 `--stop` / `--restart`，分开启动的服务在原终端 `Ctrl+C`，不强制抢占 |
| Java 提示数据库连接失败 | 检查 `brew services list`、MySQL 端口和本地配置文件 |
| Python 提示数据库不可用或未迁移 | 先检查 Java 的 `/api/paper/state`；生产模式不回退本地文件 |
| `No module named ...` | 使用已安装项目依赖的 Python；本机不要混用不同版本的 `python` / `python3` |
| Nuxt / Node 版本错误 | 确认 `node --version`；已有最新静态构建时，默认一键启动不需要开发服务器 |
| 页面有持仓但行情/收益空白 | 等待有效行情与完整扫描补齐，并检查行情源健康状态 |
| 另一台设备没有相同持仓 | 必须访问同一个 Java 后台/数据库；各自的 `localhost` 不是同一个数据库 |

检查本机监听端口：

```bash
lsof -nP -iTCP:8080 -iTCP:8765 -iTCP:3000 -sTCP:LISTEN
```

停止旧进程应优先使用其终端的 `Ctrl+C`。当前仅本机访问，不要直接将无认证的后台暴露到公网。

### 启动加载日志

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
2. **默认策略**：加载策略一定盘池和公共自选池。
3. **全量补齐**：后台补策略16观察池、策略16B动态池、策略17叠加观察池、策略3/8/15面板、板块轮动和画像缓存。

这些任务不再阻塞首屏：

- 股票名称缓存预热（账本补空仓位只读本地名称表 / 紫阳 picks 名，不逐票打外网）
- 个股画像/板块反查
- 策略3/8/15快照面板
- 策略17叠加观察池
- 板块轮动

行情 seed 与日线缓存预热并行执行；新浪批量失败时仍会按票兜底拉日线。

## 当前默认交易逻辑

| 模块 | 当前口径 |
| --- | --- |
| 默认策略 | **策略1 援军战法** |
| 选股池 | 因子13A→因子16 定盘 Top20 + 公共自选池 |
| 买入 | 因子26 开盘阈值；因子29 9:20–9:25 武装后按正式开盘；**报价驱动**用已确认现价触价（实时不拉 1m）；只从策略一池入槽 |
| 卖出 | 因子26 多层止盈/止损，报价驱动按观测现价；因子29 竞价路径达阈值可按开盘卖；策略十六遗留实仓同样走这套卖出，卖出后清空 |
| 因子29 | 已挂策略一；未武装仍走因子26 |
| 预警 | 策略一池买点预警 + 因子2 回撤加减仓预警 |
| 因子22 | 策略一默认开启（研究再买路径）；三槽当日卖出通常禁再买 |
| 仓位 | Capital V2，模拟盘纸面交易，不接券商 |

因子26退出规则摘要：

- 硬保护 2.5%，低开已破按开盘。
- 中赚 3-10%：回落一半与 `0.5 x 20日日频sigma` 谁先到走谁。
- 10% 半仓止盈，15% 全清。
- 大赚后回落 2% 清仓。
- 买入日未到 3%，次日按隔夜高点回落 2.5%，不得低于硬保护。
- T+1：买入当日不卖，卖出当日通常不买回。策略十六遗留票卖出后不再回买。

## 策略16 与策略16B

### 策略16

策略16不再是默认交易池，只保留观察 Tab：

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
| 策略1 | 默认交易池，按距买点排序 |
| 策略16 | 核心龙头观察池，不再默认入槽 |
| 策略16B | 条件可配置的核心龙头动态池（在策略16右侧） |
| 策略3 | T-1连板梯度情绪 + 首板晋级跟踪 |
| 策略8 | 当日涨停实时定题材 |
| 策略15 | 连板减磨损与震荡处理 |
| 策略17 | 紫阳真君叠加观察池，非默认交易池 |

重要口径：

- 盯盘快照写入 MySQL 文档 `watch_snapshot`，由 `GET/PUT /api/documents/watch_snapshot` 读写。它不是账本真源。进程内存只保留当前这一帧，便于页面和 WebSocket 立即显示。预警卡片进过预警线后留在原位，宽屏一行四张；红色表示仍在线内，灰色表示暂时离开，并显示买入预警价。触买只显示「触买」和触发时间，按时间从早到晚排，当天颜色固定。策略表一行一只股票，行高固定，状态列不再把行高撑开。条件单说明固定为中文，例如「条件买单@8.32 · 已成交」，不再闪出英文状态。
- 纸面账本、交易和状态文件不要手工乱改。
- Win/Mac 持仓共享须连接同一 Java 后端/MySQL；不再通过 Git 同步持仓。
- 外网行情断开时，本机 WebSocket 仍可能正常，页面以 `quoteStale` / `feedOk` 显示行情健康。
- 微信扫描预警与纸面/策略模拟自动成交只在 **A 股交易日连续竞价**；周末和交易所休市日不推扫描预警、不成交（`market_phase=closed`）。
- 纸面买入：默认策略一走因子26 开盘突破条件单 + 报价驱动现价触价；**因子29** 已挂策略一：9:20–9:25 路径达阈值则按正式开盘买。**9:15–9:19 竞价指示价不参与买卖**，9:25 重置正式 OHLC；9:30 必须已有新报价。候选触买后再**单独拉该股票行情复核开盘价**，与聚合行情按 tick 一致才过门；Paper 落账前再强制拉一次。接口失败、日期/时刻未核定、开盘失配或成交价低于买点均拒绝。

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

持仓账本已经切换为数据库。生产模式的 `holdings-push` 与旧 Git pull 不再可用；`holdings-pull` 只刷新数据库读取。盯盘启动检查数据库账本，失败即停止。`--no-ledger-pull` 只跳过启动检查，不会切回本地文件。离线测试须显式设置 `HOLDINGS_STORAGE=local_json`，不得用于多设备实盘模拟同步。策略模拟账本、盯盘快照、微信通知配置和股票名称缓存在数据库模式下走 Java 文档接口，不再回写本地 JSON。纸面账户和策略模拟账本仍然分开。Java 更新并重启后执行：

```bash
python holdingStocks/migrate_runtime_documents.py
```

该命令在盯盘进程运行时拒绝执行。导入成功后删除对应的本地 JSON。已在 `backend/logs/` 的备份不删除。

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

当前默认 **strategy1**（选股 + 因子29 + 报价驱动公共执行）；**strategy16** 改为观察池（同样挂因子29）；**strategy16B** 复刻策略16买卖内核，页面动态选股，不覆盖正式池、不入默认四槽。

---

## 开发约定

- 改策略/因子时，同步更新 `strategy/README.md`、`docs/` 和本文。
- 不要把运行时 JSON 当账本手工改。纸面账户在 MySQL 账户表；策略模拟状态在文档 `strategy_simulator_state` / `strategy_simulator_events`，作废事件在 `strategy_sim_voided_events`。接口是 `GET/PUT /api/documents/{key}` 和 `POST /api/strategy-simulator/voided`。
- 提交前至少跑 `holdingStocks/run_all_tests.py --skip-pytest-if-missing`。
- 涉及前端时，再跑 `holdingStocks/watch-ui` 的构建或本地 dev 验证。
