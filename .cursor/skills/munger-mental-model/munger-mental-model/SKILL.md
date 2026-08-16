---
name: munger-mental-model
description: Munger 5-维模型与一票否决的 A 股上市公司多角度评估系统
license: GPL-3.0-only
tags: [quant, analysis, a-share, munger, mental-model]
---

## 适用场景

本模块实现了 Charlie Munger 多角度思维方法论在 A 股市场的量化应用。通过对单个上市公司的财务、竞争、激励、心理、负面清单这五个独立维度的逐一评分，再通过"一票否决"机制进行 cross-validation，最终产出高置信度的投资评估报告。

- **单票研究**：对指定股票进行深度多维分析，输出 JSON 报告和 5 维雷达图
- **批筛应用**：按行业筛选，快速识别符合多维标准的高置信度候选股
- **数据驱动**：纯粹基于 panda_data SDK，不涉及本地数据或第三方 API


## 5 维模型逻辑与打分规则

### 1. 财务维度 (fin)

**核心逻辑**：评估目标公司相对行业同业的财务优势

**打分指标**：
- ROE vs 中位数：目标 ROE >= 行业中位数得 1 分，否则 0 分
- 毛利率 vs 中位数：目标毛利率 >= 行业中位数得 1 分，否则 0 分
- OCF 正性与中位数：OCF > 0 且 >= 行业中位数得 1 分，否则 0 分

**综合评分**：三项指标平均值 × 100（范围 0-100）

**判定规则**：得分 >= 60（可配置阈值）判为 pass


### 2. 竞争维度 (comp)

**核心逻辑**：评估目标公司在同业内的竞争排名

**打分指标**：
- ROE 百分位数（40%权重）：target ROE 在行业中的百分位排名
- 毛利率百分位数（40%权重）：target 毛利率在行业中的百分位排名
- 产业集中度奖励（20%权重）：当前实现为 0（预留扩展）

**综合评分**：ROE percentile × 0.4 + GM percentile × 0.4 + 集中度奖励，范围 0-100

**低置信标记**：少于 3 家同业公司时标记 `low_confidence` flag，自动判为 fail


### 3. 激励维度 (incentive)

**核心逻辑**：通过多个信号评估股权激励与大股东行为对齐情况

**打分指标**（三信号模型，各占 33.33% 权重，基础得分均为 60 分）：

1. **管理层交易信号**（33.33%）
   - 净买入 (net_change > 0) → 100 分
   - 无交易 → 60 分（中性基线）
   - 净卖出 (net_change < 0) → 20 分

2. **股权质押比例信号**（33.33%）
   - 公式：60 + (1 - ratio/0.50) × 40，范围 [20, 100]
   - 质押比例 = 0% → 100 分（无压力）
   - 质押比例 = 50%（阈值）→ 60 分（基线）
   - 质押比例 > 50% → 20 分以下（高风险）

3. **控股股东交易信号**（33.33%）
   - 净增持 (net_change > 0) → 100 分
   - 无交易 → 60 分（中性基线）
   - 小幅减持 (ratio_up_limit ≤ 2%) → 40 分
   - 大幅减持 (ratio_up_limit > 2%) → 20 分

**综合评分**：mgmt_score × 33.33% + pledge_score × 33.33% + controlling_score × 33.33%

**数据缺口标记**：永远添加 `related_party: data_unavailable`（缺乏关联交易数据）

**判定规则**：得分 >= 60 判为 pass


### 4. 心理维度 (psych)

**核心逻辑**：投资者关注度与机构参与热度

**打分指标**：
- 年度投资者活动次数：min(会议数 / 60, 1.0) × 50 分
- 年度参与机构数：min(机构总数 / 60, 1.0) × 50 分

**综合评分**：会议分 + 机构分，范围 0-100

**计分说明**：基准设为 60（周频活跃，即 52-60 次/年），达到基准即获得 50 分满分

**数据缺口标记**：永远添加 `qa_sentiment: not_available`（无文本情感分析）

**判定规则**：得分 >= 60 判为 pass


### 5. 负面清单维度 (neg)

**核心逻辑**：通过一票否决制机制，任何严重负面信号都会导致整体评估失败

**一票否决触发条件**：以下任何一项成立即触发 veto：
1. 审计意见非标准（非 `unqualified_opinion` 或 `no_audit_performed`）→ veto_flag: `nonstandard_audit:*`
2. 审计机构切换（历史中出现过多个不同的审计机构）→ veto_flag: `agency_switch`
3. 任何 ST/退市状态变化记录 → veto_flag: `status_change:ST_or_delisting`
4. 最高质押比例 > 50%（可配置阈值）→ veto_flag: `high_pledge`
5. 控股股东减持幅度超过 2% → veto_flag: `large_controlling_sell` + 数据标记 `hostile_takeover: weak_proxy`

**评分规则**：
- 触发任何 veto：score=0, passed=False, veto=True
- 无 veto：score=100, passed=True, veto=False


## 输入接口映射

| 维度 | 核心 API | 使用字段 | 映射说明 |
|------|---------|---------|---------|
| 财务 (fin) | `get_fina_performance` | roe_weighted, gross_profit, net_cash_flow_operating | ROE、毛利率、OCF |
| 竞争 (comp) | 行业百分位 + `get_industry_constituents` | ROE/毛利率百分位 | 自行计算行业中位数 |
| 激励 (incentive) | `get_top_holders`, `get_stock_shareholder_change` | hold_ratio, pledge_ratio, net_change | 前十大股东、质押、管理层增减持 |
| 心理 (psych) | `get_investor_activity` | activity_date, num_investors, num_institutes | 投资者路演与机构参与 |
| 负面 (neg) | `get_audit_opinion`, `get_stock_status_change`, `get_stock_pledge`, `get_stock_shareholder_change` | opinion, status, pledge_ratio, ratio_up_limit | 审计、ST、质押、减持 |


## 输出字段表

每条分析记录包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | str | 股票代码（如 000001.SZ） |
| trade_date | str | 分析基准日期 (YYYY-MM-DD) |
| dim_scores | dict[str, float] | 五维得分：{fin, comp, incentive, psych, neg}，各 0-100 |
| dim_passed | dict[str, bool\|None] | 五维是否通过：{fin, comp, incentive, psych, neg}，None 表示数据不足 |
| sub_scores | dict[str, dict] | 各维度的详细子指标分数 |
| veto_flags | list[str] | 触发一票否决的具体原因列表（neg 维度） |
| data_flags | list[str] | 数据缺口标记，包括 `related_party: data_unavailable`, `qa_sentiment: not_available`, `hostile_takeover: weak_proxy`（若适用） |
| radar_scores | list[float] | 5 元组 [fin, comp, incentive, psych, neg]，用于绘制雷达图 |
| high_confidence | bool | 是否高置信（True: 所有维度 pass 且无 veto；False: 任何条件不满足） |
| verdict | str | 最终评估结果：pass / fail / veto / insufficient_data |
| data_version | str | 数据版本标记（固定 "real-v1"） |
| update_time | str | 分析时间戳 (ISO 8601) |


## 交叉验证与一票否决

### Cross-Validation 逻辑

最终 verdict 的判定流程（spec §5 AND 逻辑）：

1. **检查一票否决** → 若 neg.veto = True，verdict = "veto"，high_confidence = False，**立即返回**
2. **检查数据完整性** → 若任何维度 passed = None（数据不足），verdict = "insufficient_data"，high_confidence = False，**立即返回**
3. **检查全维度通过** → 若全部五个维度 passed = True，verdict = "pass"，high_confidence = True
4. **其他情况** → verdict = "fail"，high_confidence = False

### 一票否决的执行

- 负面清单维度一旦检测到上述 5 项条件中的任何一项，**立即阻止任何 pass 或 pass-like 的判定**
- veto 优先级高于其他维度的 pass/fail 判定
- veto 记录在 veto_flags 中，便于后续审查


## 使用方式

### 快速开始

```bash
cd munger-mental-model/scripts

# 单票分析（必须）
python analyze.py --symbol 000001.SZ [--end-date 20260630]

# 行业批筛
python analyze.py --industry L2004001

# 验证（部署前必须运行）
PYTHONPATH=. python validate.py
```

### 命令行参数

#### `analyze.py`

```
--symbol SYM        逗号分隔的股票代码列表，如 000001.SZ,600000.SH
--industry CODE     L2 行业代码（例如 L2004001 表示银行业）
--end-date DATE     分析基准日期，格式 YYYY-MM-DD 或 YYYYMMDD（默认：今日）
```

输出：
- `report_{symbol}.json` - 每支股票的完整分析记录
- `radar_{symbol}.png` - 5 维雷达图（如果成功）
- `high_confidence_list.csv` - 高置信度候选名单（仅当有高置信记录时）

#### `validate.py`

```
PYTHONPATH=. python validate.py
```

无命令行参数。要求环境变量 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD` 已设置。

执行流程：
1. 初始化 panda_data 会话
2. 调用 `analyze_symbol('000001.SZ', None, now)`
3. 运行三项预飞检查：
   - `check_record_fields()` - 字段完整性与范围检查
   - `check_veto_forces_low_confidence()` - 一票否决逻辑离线测试
   - `check_data_gap_markers()` - 数据缺口标记检查
4. 输出成功消息或 AssertionError


## Agent 执行规则

当作为自动化工具集成时，建议遵循以下规则：

1. **前置验证** → 在信任任何分析输出前，务必运行 `validate.py` 通过
2. **失败处理** → 若 validate.py 或 analyze.py 返回错误：
   - 报告完整的命令行 + 错误信息
   - 注明分析基准日期 (trade_date)
   - 检查环境变量与网络连接
3. **幂等性** → 同一只股票在同一日期的分析结果应一致（数据源相同）
4. **数据日期检查** → 确保 trade_date 不晚于当前日期（无未来函数）


## 成功标准

部署前 checklist：

- [ ] `validate.py` 通过所有断言（check_record_fields, check_veto_forces_low_confidence, check_data_gap_markers）
- [ ] 生成的 JSON 记录包含所有 spec §6 字段
- [ ] 所有数值字段在合法范围内（0-100）
- [ ] verdict 枚举值来自 {pass, fail, veto, insufficient_data}
- [ ] 一票否决逻辑生效（veto 时 high_confidence 必为 False）
- [ ] 无未来数据污染（trade_date <= 当前日期）
- [ ] 使用真实数据而非 mock（validate.py 必须连接真实 panda_data）
- [ ] veto_flags 与 data_flags 内容合理且完整


## 边界与已知限制

### 数据缺口（Spec §12）

1. **无行业中位数 API**
   - 解决方案：自行计算可比公司的中位数
   - 实现：在 score_financial/score_competition 中按 peers 计算
   - 影响：当同业公司少于 3 家时，竞争维度自动降低置信度

2. **关联交易数据缺席**
   - 激励维度永远标记 `related_party: data_unavailable`
   - 无法评估大股东与关联方的交易行为

3. **QA 文本情感分析缺席**
   - 心理维度永远标记 `qa_sentiment: not_available`
   - 无法提取投资者活动的文本情感信息

4. **举牌的弱代理**
   - 用"控股股东减持比例 > 2%"作为敌意收购的弱代理
   - 标记为 `hostile_takeover: weak_proxy`
   - 触发一票否决

5. **诉讼数据缺席**
   - 预留标记 `litigation: data_unavailable`（暂不用）
   - 未来若获得诉讼数据可扩展

### 其他限制

- **数据源**：仅 panda_data SDK；不读本地文件，不调用其他第三方 API
- **时间边界**：每个维度仅使用 <= 分析基准日期的数据（无未来函数）
- **配置参数**（默认值可通过环境变量覆盖）：
  - `MUNGER_PASS_THRESHOLD=60` - 各维度 pass 分数阈值
  - `MUNGER_PLEDGE_MAX=0.50` - 质押比例上限
  - `MUNGER_IR_MONTHS=12` - 投资者活动查询范围（月数）


## 依赖

### 必需库

| 库 | 版本 | 用途 |
|----|------|------|
| panda_data | latest | 数据获取 SDK |
| pandas | >= 1.0 | 数据处理 |
| numpy | >= 1.15 | 数学运算 |
| matplotlib | >= 3.0 | 雷达图绘制（可选） |
| pytest | >= 6.0 | 单元测试 |

### Python 版本

- **最低要求**：Python 3.10+
- **类型检查**：所有模块使用 `from __future__ import annotations`
- **语法**：PEP 484 type hints


## 架构与模块

```
munger-mental-model/scripts/
├── analyze.py          # 编排层：cross-validation 与记录构建
├── dimensions.py       # 维度评分函数
├── config.py           # 配置与常量
├── data.py             # 数据获取层（panda_data 封装）
├── validate.py         # 部署前验证门
├── test_*.py           # 单元测试
└── references/         # 参考文档与示例
```

---

**免责声明**：本工具仅供学习、研究、教育之用，不构成投资建议，不承诺收益，不代表任何机构背书。用户自行承担使用本工具产生的所有后果。

**许可证**：GNU General Public License v3.0

**灵感来源**：Charlie Munger 《穷查理宝典》的多角度思维与一票否决机制
