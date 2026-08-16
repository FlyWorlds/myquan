# Munger 5-维模型与一票否决的多角度cross-validation分析工具

> 本仓库为 QUANTSKILLS 社区成员项目，未经官方审核，不代表 QUANTSKILLS 官方背书或认证。

本项目是 QuantSkills 的 Munger 心理模型分析工具，用于评估 A 股上市公司的投资价值。通过五个独立维度的评分与一票否决的 cross-validation 机制，产出高置信度的候选池。

## 五个维度

1. **财务** (fin) - ROE、毛利率、OCF 的相对优势
2. **竞争** (comp) - 行业内相对竞争力  
3. **激励** (incentive) - 大股东持股集中度、管理层增减持、质押冻结
4. **心理** (psych) - 投资者活动与机构关注度
5. **反面清单** (neg) - 审计意见、高管变动、ST/退市、质押过高、控股股东减持

## 已知数据限制

根据 COMMUNITY_RULES §2 和 §8 的诚实披露原则，本工具存在以下数据限制：

1. **没有行业中位数 API** - 需自行计算行业内可比公司的中位数
2. **关联交易缺席** - 激励维度标记为 `related_party: data_unavailable`
3. **QA 文本情感分析缺席** - 心理维度标记为 `qa_sentiment: not_available`
4. **诉讼数据缺席** - 标记为 `litigation: data_unavailable`

## 安装和运行

### 前置要求

- Python 3.10+
- panda_data SDK
- 环境变量 PANDA_DATA_USERNAME 和 PANDA_DATA_PASSWORD

### 快速开始

```bash
cd munger-mental-model/scripts

# 单票分析
python analyze.py --symbol 000001.SZ --end-date 20260630

# 行业批筛
python analyze.py --industry L2004001  # 银行业

# 验证（运行前置检查）
PYTHONPATH=. python validate.py

# 运行全套测试
PYTHONPATH=. pytest tests/ -v
```

### 环境配置

```bash
export PANDA_DATA_USERNAME=your_username
export PANDA_DATA_PASSWORD=your_password
export MUNGER_PASS_THRESHOLD=60          # 分数阈值，default
export MUNGER_PLEDGE_MAX=0.50            # 质押比例上限，default
export MUNGER_IR_MONTHS=12               # 投资者活动查询范围，月数，default
```

## 使用边界与免责声明

**本工具仅供研究与教育使用，不构成投资建议。**

- 不承诺任何收益或回报
- 不代表任何官方背书或推荐
- 不应作为投资决策的唯一依据
- 分析结果仅供参考，使用者需自行评估风险

## 产出格式

- **JSON** - per-stock 分析记录 (`report_{symbol}.json`)
- **CSV** - 高置信度名单 (`high_confidence_list.csv`)
- **PNG** - 5 维雷达图 (`radar_{symbol}.png`)

## 许可证

GNU General Public License v3.0 (GPL-3.0-only)

## 参考

详见 `munger-mental-model/SKILL.md`。
