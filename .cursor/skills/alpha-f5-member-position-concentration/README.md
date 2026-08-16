# skill-alpha-f5-member-position-concentration

当前远端仓库名为 `alpha-f5-member-position-concentration`。按 QuantSkills 社区公开收录规则，建议维护者将仓库重命名为 `skill-alpha-f5-member-position-concentration` 后再申请公开、收录、恢复 public 或进入 registry / quantskills / 组织首页索引。

商品期货会员持仓集中度 Alpha（Factor ID: F5）。计算前5大净多/净空席位的持仓保证金集中度，生成横截面 buy/sell/hold 信号。

本仓库仅提供研究与验证工具，不构成投资建议，不承诺收益，也不代表 QuantSkills、Panda data、Codex、Claude Code、Cursor、Hermes 或 OpenClaw 的官方背书。

## 社区合规状态

| 项目 | 状态 |
|------|------|
| 仓库类型 | Skill |
| 建议仓库名 | `skill-alpha-f5-member-position-concentration` |
| 根入口 | `SKILL.md` |
| 中文说明 | `README.md` |
| 英文说明 | `README.en.md` |
| 许可证 | `GPL-3.0-only`，见 `LICENSE` 与 `skill.json` |
| Codex 入口 | `AGENTS.md` |
| Claude Code 入口 | `CLAUDE.md` |
| Cursor 入口 | `.cursor/rules/skill-alpha-f5-member-position-concentration.mdc` |
| Hermes 入口 | `HERMES.md` |
| OpenClaw 入口 | `OPENCLAW.md` |

## 目录结构

```
SKILL.md                                          根 skill 入口
skill.json                                        QuantSkills 元数据
AGENTS.md                                         Codex 入口
CLAUDE.md                                         Claude Code 入口
HERMES.md                                         Hermes 入口
OPENCLAW.md                                       OpenClaw 入口
.cursor/rules/skill-alpha-f5-member-position-concentration.mdc
README.en.md                                      英文说明
LICENSE                                           GPL-3.0-only 许可声明

alpha-f5-member-position-concentration/        开发产物（计算、验证、回测）
  scripts/
    factor.py       因子计算，输出 Parquet 结果
    validate.py     无未来函数检测、字段完整性验证
    backtest.py     IC/ICIR/ARR/MDD/多空收益等回测指标
  references/
    data_guide.md   数据源与字段说明、因子公式、信号规则

alpha-f5-member-position-concentration-production/   生产产物（只读）
  database.parquet  每日收盘后更新的因子结果
  SKILL.md          生产 skill 说明

README.md           本文件
```

## 因子逻辑

- **核心假设**：前5大净多（或净空）席位持仓保证金占全市场超过60%时，主力方向高度一致，价格跟随主力运动。
- **多头集中度**：`bull_ratio = sum(top5 净多 net_margin) / sum(abs(net_margin) 全部席位)`
- **空头集中度**：`bear_ratio = sum(abs(top5 净空 net_margin)) / sum(abs(net_margin) 全部席位)`
- **原始权重**：`raw_weight = bear_ratio - bull_ratio`（正值代表空方更集中，负值代表多方更集中）
- **Level 路径**：`raw_weight` 做 60 日滚动 Z-score → `zscore_level`（`min_periods=20`）
- **Delta 路径**：`raw_weight` 一阶差分后再做 60 日滚动 Z-score → `zscore_delta`（`min_periods=20`）
- **混合**：`factor_value = 0.5 × zscore_level + 0.5 × zscore_delta`（两路同时有值才保留，等权）

## 信号规则

| 信号 | 触发条件 |
|------|----------|
| `buy` | `bull_ratio > 0.6` 且 `factor_value > 0` 且 横截面 `rank ≤ 前90%` |
| `sell` | `bear_ratio > 0.6` 且 `factor_value < 0` 且 横截面 `rank ≥ 后10%` |
| `hold` | 其余情况 |

## 数据源

使用 Panda data SDK，不读取本地表格作为正式输入。

| 环境变量 | 说明 |
|----------|------|
| `PANDA_DATA_USERNAME` | 必填 |
| `PANDA_DATA_PASSWORD` | 必填 |
| `PANDA_DATA_START_DATE` | 可选，格式 `YYYY-MM-DD` |
| `PANDA_DATA_END_DATE` | 可选，格式 `YYYY-MM-DD` |
| `PANDA_DATA_UNDERLYING` | 可选，逗号分隔品种代码，如 `A,AG,AU` |

## 运行方式

```bash
cd alpha-f5-member-position-concentration
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
| `factor_id` | 固定 `F5` |
| `factor_name` | 固定 `会员持仓集中度` |
| `factor_value` | Level + Delta Z-score 等权混合值 |
| `score` | 横截面百分位 `[0, 100]` |
| `rank` | 横截面整数排名，1 为最优 |
| `signal` | `buy` / `sell` / `hold` |
| `confidence` | `score / 100` |
| `data_version` | 固定 `real-v2` |
| `update_time` | ISO8601 生成时间 |

## 验收标准

- `factor.py` 输出非空，包含 12 个必需字段，`factor_id=F5`，`data_version=real-v2`
- `validate.py` 验证通过（无未来函数、字段完整、取值合法）
- `backtest.py` 输出研究口径和可交易口径两组指标，含多周期 IC 衰减（1D-20D）、Bootstrap IC 95% CI、成本四档分析
- 不通过验证不得进入生产

## 生产查询

交易 agent 使用 `alpha-f5-member-position-concentration-production` skill 读取 `database.parquet`，不在调用时重新计算因子。

生产查询结果只能作为研究数据读取，不应表述为交易建议、收益预测或确定性信号。

## 依赖

- Python 3.10+
- panda-data
- pandas
- scipy
- pyarrow 或 fastparquet

## 许可证

本仓库使用 `GPL-3.0-only`。见 `LICENSE`。
