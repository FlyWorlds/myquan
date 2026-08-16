# skill-alpha-f8-family-main-divergence

当前远端仓库名为 `alpha-f8-family-main-divergence`。按 QuantSkills 社区公开收录规则，建议维护者将仓库重命名为 `skill-alpha-f8-family-main-divergence` 后再申请公开、收录、恢复 public 或进入 registry / quantskills / 组织首页索引。

商品期货家人主力分歧 Alpha（Factor ID: F8）。计算家人席位（散户）与主力席位（机构）的净持仓方向分歧，并按主力一致性加权，输出横截面 buy/sell/hold 信号。

本仓库仅提供研究与验证工具，不构成投资建议，不承诺收益，也不代表 QuantSkills、Panda data、Codex、Claude Code、Cursor、Hermes 或 OpenClaw 的官方背书。

## 社区合规状态

| 项目 | 状态 |
|------|------|
| 仓库类型 | Skill |
| 建议仓库名 | `skill-alpha-f8-family-main-divergence` |
| 根入口 | `SKILL.md` |
| 中文说明 | `README.md` |
| 英文说明 | `README.en.md` |
| 许可证 | `GPL-3.0-only`，见 `LICENSE` 与 `skill.json` |
| Codex 入口 | `AGENTS.md` |
| Claude Code 入口 | `CLAUDE.md` |
| Cursor 入口 | `.cursor/rules/skill-alpha-f8-family-main-divergence.mdc` |
| Hermes 入口 | `HERMES.md` |
| OpenClaw 入口 | `OPENCLAW.md` |

## 目录结构

```
SKILL.md                                           根 skill 入口
skill.json                                         QuantSkills 元数据
AGENTS.md                                         Codex 入口
CLAUDE.md                                         Claude Code 入口
HERMES.md                                         Hermes 入口
OPENCLAW.md                                       OpenClaw 入口
.cursor/rules/skill-alpha-f8-family-main-divergence.mdc
README.en.md                                      英文说明
LICENSE                                           GPL-3.0-only 许可声明

alpha-f8-family-main-divergence/               开发产物（计算、验证、回测）
  scripts/
    factor.py       因子计算，输出 Parquet 结果
    validate.py     无未来函数检测、字段完整性验证
    backtest.py     IC/ICIR/ARR/MDD/多空收益等回测指标
  references/
    data_guide.md   数据源与字段说明、因子公式、信号规则
  test.py           离线小样本测试，无需 Panda data

alpha-f8-family-main-divergence-production/    生产产物（只读）
  database.parquet  每日收盘后更新的因子结果
  SKILL.md          生产 skill 说明

README.md           本文件
```

## 因子逻辑

- **家人席位**（散户）：东方财富、徽商期货、平安期货，精确字符串匹配
- **主力席位**（机构）：永安期货、中信期货、国泰君安，精确字符串匹配
- **有效分母**：`denom = total_abs_margin + min(family_bull, family_bear) × 2`（加回家人内部对冲量）
- **持仓比例**：`family_ratio = family_net / denom`，`major_ratio = major_net / denom`
- **主力一致性**：`consistency = max(major_bull, major_bear) / (major_bull + major_bear)`
- **一致性强度**：`consistency_strength = clip(2 × consistency - 1, 0, 1)`
- **原始权重**：`raw_weight = (major_ratio - family_ratio) × consistency_strength`（主力领先家人跟随，按一致性加权）
- **因子值**：横截面百分位映射到 `[-1, 1]`，`factor_value = rank_pct(raw_weight) × 2 - 1`（当日全品种截面，非时序）
- **排序方向**：`factor_value` 越大越好（rank=1 为最高）

## 信号规则

| 信号 | 触发条件 |
|------|----------|
| `buy` | 横截面 `rank ≤ ceil(n × 0.1)`（前10%），主力与家人分歧最强且主力方向一致，跟随主力做多 |
| `sell` | 横截面 `rank > n - ceil(n × 0.1)`（后10%），家人与主力方向相反且主力一致，跟随主力做空 |
| `hold` | 分歧信号不在触发区间 |

剔除条件：`total_abs_margin = 0` 或 `major_total = 0`（无法计算一致性）的品种当日不参与排名。

## 数据源

使用 Panda data SDK，不读取本地表格作为正式输入。

| 接口 | 用途 |
|------|------|
| `get_broker_netmarg` | 席位净持仓保证金 |
| `get_future_dominant` | 每日主力合约映射 |
| `get_future_daily` | 主力合约日线（close / open_interest） |
| `get_future_detail` | 合约基础信息（start_delivery_date） |

| 环境变量 | 说明 |
|----------|------|
| `PANDA_DATA_USERNAME` | 必填 |
| `PANDA_DATA_PASSWORD` | 必填 |
| `PANDA_DATA_START_DATE` | 可选，默认 `2024-01-01` |
| `PANDA_DATA_END_DATE` | 可选，默认 `2026-05-28` |
| `PANDA_DATA_UNDERLYING` | 可选，逗号分隔品种代码，留空或 `all` 表示全部 |

## 运行方式

```bash
cd alpha-f8-family-main-divergence
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

## 输出字段

| 字段 | 说明 |
|------|------|
| `trade_date` | 交易日期 `YYYY-MM-DD` |
| `asset_type` | 固定 `future` |
| `symbol` | 期货品种代码 |
| `factor_id` | 固定 `F8` |
| `factor_name` | 固定 `家人主力分歧` |
| `factor_value` | 横截面百分位映射到 `[-1, 1]` |
| `score` | 横截面百分位评分 `[0, 100]` |
| `rank` | 横截面整数排名，1 为最优 |
| `signal` | `buy` / `sell` / `hold` |
| `confidence` | `score / 100` |
| `data_version` | 固定 `real-v1` |
| `update_time` | ISO8601 生成时间 |

## 验收标准

- `factor.py` 输出非空，含 12 个必需字段，`factor_id=F8`，`data_version=real-v1`
- `validate.py` 输出验证通过（无未来函数、字段完整、家人席位和主力席位均至少出现一家）
- `backtest.py` 输出研究口径与可交易口径两组指标，含 1D-20D IC 衰减、Bootstrap IC 95% CI、成本四档分析
- `test.py` 使用合成数据离线验证回测可导入、Bootstrap CI 和可交易口径输出
- 不通过验证不得进入生产

## 生产查询

交易 agent 使用 `alpha-f8-family-main-divergence-production` skill 读取 `database.parquet`，筛选 `factor_id == "F8"`，不在调用时重新计算因子。

生产查询结果只能作为研究数据读取，不应表述为交易建议、收益预测或确定性信号。

## 依赖

- Python 3.10+
- panda-data
- pandas
- pyarrow 或 fastparquet

## 许可证

本仓库使用 `GPL-3.0-only`。见 `LICENSE`。
