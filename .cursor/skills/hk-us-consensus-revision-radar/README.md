# 港美股一致预期修订雷达：轨迹矩阵与状态机

一个基于 **PandaData** 的 QuantSkills Community Project。它的重点不是展示某一时点的一致预期快照，而是把港股与美股的目标价、评级变化组织成**修订雷达**：跨五个回看期的修订轨迹矩阵、规则化一致预期状态机，以及可离线复核的 HTML 研究报告。

> 本项目尚未经过 QuantSkills 官方审查或认可，仅用于研究与教育，不构成投资建议，不提供买卖指令、收益承诺或仓位建议。

English: [README.en.md](README.en.md)

## 核心能力

- **修订雷达定位**：以跨期目标价与评级变化为核心，而非只罗列当前评级、目标价或上行空间。
- **修订轨迹矩阵**：将周度、1/3/6/12 个月的目标价和评级变化放入同一可搜索矩阵，便于识别持续上修、减速、反转和信号冲突。
- **一致预期状态机**：基于可公开的聚合证据解释“持续上修”“上修加速”“目标价与评级共振改善”“高分歧待核验”等状态；状态不改变榜单，也不代表个人分析师行为。
- **可审计 HTML 交付**：将原始接口来源、时间口径、公式、资格漏斗、缺失值、校验和限制一并写入单文件离线报告，支持不联网复核。
- 港股与美股独立采集、计算和排名；支持 `week`、`1month`、`3month`、`6month`、`12month` 五个回看期。
- 输出目标价上修/下修、高分歧、评级变化和价格—一致预期偏离榜单，并展示每个指标的计算口径。
- 提供 **修订轨迹矩阵**：按五个回看期展示目标价与评级的变化方向和数值；可按股票名称或代码搜索。
- 提供个股解读：目标价定位、评级分布、目标价与评级轨迹、规则化一致预期状态，以及相关事件上下文。
- 仅将 PandaData 确认的在市普通股纳入核心排名；ETF、优先股、权证、非在市或身份不完整证券保留在诊断中并说明排除原因。
- 生成单文件离线 HTML：无 CDN、无远程请求、无凭证；报告末尾的数据完整性默认收起，可按需展开。

## 快速开始

要求：Python 3.10+、可用的 PandaData 账号，以及网络可访问 PandaData 服务。

```powershell
python -m pip install -r requirements.txt
python -m scripts.run_report --market both --horizon 1month --min-analysts 5 --min-recommendations 5
```

默认输出到 `output/`：

- `consensus_revision_YYYYMMDD_HHMMSS.html`：本次带时间戳的完整报告。
- `latest.html`：最新一次报告的固定入口。

## 认证与隐私

认证始终是运行时的第一个外部动作。可通过当前进程环境变量提供账号：

```powershell
$env:PANDADATA_USERNAME = "your-account"
$env:PANDADATA_PASSWORD = "your-password"
python -m scripts.run_report --market both
```

未设置环境变量时，桌面环境会使用可见的本地登录窗口；密码仅存在于进程内存，不写入命令行、日志、配置文件或 HTML。对非 TTY 调用，只有在 GUI 桌面主机显式使用 `--desktop-login-window` 时才请求登录窗口：

```powershell
python -m scripts.run_report --market both --desktop-login-window
```

- 仅 11 位中国大陆手机号用户名会自动补 `86` 前缀；其他账号保持原样。
- 输入密码并回车后，终端会立即提示“正在登录 PandaData”；认证成功或失败均有明确提示，失败时需要重新输入账号和密码。
- 使用本地登录窗口时，窗口仅向主进程转交已验证的短期会话 token；不会回传密码，也不会触发第二次登录请求。
- 如果认证失败，窗口会要求重新输入账号和密码；不会复用失败凭证。
- `--no-login-window` 仅适用于不允许可见登录窗口的无人值守环境。

## 常用命令

```powershell
# 指定标的（.HK 自动路由到港股）
python -m scripts.run_report --market both --symbols 0700.HK,9988.HK,AAPL,NVDA

# 调整回看期、目标价覆盖与评级覆盖阈值
python -m scripts.run_report --market both --horizon 3month --min-analysts 8 --min-recommendations 8

# 调整目标价方向阈值与每榜条数
python -m scripts.run_report --market hk --revision-threshold 0.02 --ranking-limit 30

# 调整事件展示/发现窗口
python -m scripts.run_report --market both --event-past-days 30 --event-future-days 30 --event-discovery-days 730

# 不查询事件上下文，仅生成一致预期榜单与个股解读
python -m scripts.run_report --market both --no-events
```

关键参数：

| 参数 | 说明 |
|---|---|
| `--market` | `hk`、`us` 或 `both`，默认 `both`。 |
| `--symbols` | 逗号分隔的股票代码；未设置时使用支持范围内的完整股票池。 |
| `--horizon` | 回看期：`week`、`1month`、`3month`、`6month`、`12month`。 |
| `--min-analysts` | 目标价榜单的最低估计数，默认 5。 |
| `--min-recommendations` | 评级变化榜单的最低推荐数，默认 5。 |
| `--revision-threshold` | 目标价上修/下修的绝对变化阈值，默认 `0.01`。 |
| `--ranking-limit` | 每个榜单最多展示条数，默认 20。 |
| `--start-date` / `--end-date` | 可选价格查询窗口，格式 `YYYYMMDD`。 |
| `--output-dir` | 输出目录，默认 `output/`。 |

## 如何阅读报告

### 榜单与指标

- **修订**：当前目标价均值 ÷ 回看期目标价均值 − 1。
- **价格偏离**：当前目标价均值 ÷ 最新有效收盘价 − 1；仅在币种可比时计算。
- **分歧**：目标价标准差 ÷ |当前目标价均值|。
- **覆盖**：目标价榜使用 `estimates_num`；评级榜使用 `recommendations_num`。
- **评级变化**：历史评级均值 − 当前评级均值；PandaData 评级均值越低表示整体评级更积极。

### 修订轨迹与个股解读

这份报告的主要阅读路径是“**修订轨迹矩阵 → 一致预期状态机 → 个股可审计证据**”，而不是单点一致预期查询。修订轨迹矩阵和个股轨迹按五个回看期展示聚合目标价与评级的变化；状态如“持续上修”“目标价与评级共振改善”或“高分歧待核验”只用于解释聚合证据，不改变排名，也不是个人分析师修订记录。

事件仅作解释上下文，不改变排名。数据完整性区域披露接口来源、缺失数据、价格回退、核心股票池排除和校验信息；默认收起以保持报告聚焦。

## PandaData 数据来源

PandaData 是本项目的**唯一原始数据源**；不使用其他数据源补值。完整字段映射与采集规则见 [references/pandadata-api-map.md](references/pandadata-api-map.md)，计算方法见 [references/methodology.md](references/methodology.md)。

| 用途 | 港股接口 | 美股接口 |
|---|---|---|
| 证券身份、状态、类型、行业 | `get_hk_detail` | `get_us_detail` |
| 目标价聚合一致预期 | `get_stock_ncycl_consensus` | `get_stock_ncycl_estimate` |
| 评级聚合一致预期 | `get_stock_recommendation_consensus` | `get_stock_recommendation_estimate` |
| 最新返回日行情/收盘价 | `get_hk_daily` | `get_us_daily` |
| 分红与拆股事件 | `get_stock_dividend_event` | `get_stock_dividend_activity` |
| 市场/披露事件 | `get_stock_market_event` | `get_stock_market_activity` |
| 公司会议事件 | `get_stock_meeting_event` | `get_stock_meeting_activity` |
| 财务披露事件 | `get_stock_financial_event` | `get_stock_financial_activity` |
| 投资者关系事件 | `get_stock_ir_event` | `get_stock_ir_activity` |
| 最近交易日探测（可选） | `get_last_trade_date` | `get_last_trade_date` |

## 可审计特色

- **区别于快照报告的交付物**：核心是修订雷达、轨迹矩阵和状态机，当前目标价/评级仅作为轨迹的当前锚点。
- **保守股票池**：身份、状态和资产类别由详情接口验证；非核心证券不进入排名，但仍计入诊断。
- **逐标的价格回退**：先查询目标交易日；每个缺失、非数值或非正收盘价标的都独立回查前 14 个自然日，不依赖总体匹配率。
- **缺失值不伪造**：缺失数据保持缺失，不以零、前值或第三方数据替代；受影响指标和榜单会明确排除或标记。
- **独立覆盖门槛**：目标价与评级榜单分别使用覆盖阈值，避免混用样本数。
- **来源与时间口径**：报告列出实际调用接口，区分报告生成时间、各市场抓取完成时间和返回价格日期。
- **离线可复核**：HTML 报告不加载外部资源；数据完整性和计算方法随报告一并交付。

## 限制与风险边界

- PandaData 当前映射接口提供的是**聚合一致预期**，不提供个人分析师、券商级修订、修订时间或修订广度；请勿据此推断个人行为或分析师准确率。
- 当前聚合目标价/评级没有可用的具体业务日期。报告将其标为 PandaData 最新可用快照；抓取时间只是采集证据，返回价格日期单独显示。
- 一致预期可能稀疏、滞后、偏差较大，且可能在市场波动后被修订。跨市场数值不进行外汇归一化。
- 未建模公司行动、流动性、交易成本、税费、滑点、执行可行性或衍生品风险。
- 本项目不构成投资建议；榜单和状态不能单独作为投资决策依据。

## 贡献与许可证

欢迎通过 issue 和 review 提出改进建议。该项目是未审查的 QuantSkills Community Project；PandaData SDK 和数据服务适用其各自条款。本代码采用 [GNU GPL v3.0（GPL-3.0-only）](LICENSE)。
