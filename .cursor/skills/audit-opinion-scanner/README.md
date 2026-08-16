# 审计意见扫描 — 多维财务分析系统

从审计意见、财务报表、行业对标三个维度对 A 股做全面财务健康评估。涵盖审计意见扫描（事后排雷）、25项财务科目缓存、15项比率计算、行业分类对标、5维快速评分、8段深度分析、**⭐ XGBoost 审计风险事前预测**、综合风险检测。从排雷到预测到估值到 AI 解读，一条流水线完成。

## ⚠️ 免责声明

- **仅供研究与教育使用**：本 skill 是量化财务分析研究工具，不构成投资建议、财务建议或交易建议。
- **数据准确性**：财务数据来源于 panda_data，可能存在错误、遗漏或延迟。请务必对照官方财报（年报、证监会公告）进行验证。
- **无收益保证**：财务分析评分和风险评级为量化启发式指标，非预测。高分不保证未来表现，红灯不保证必然亏损。
- **审计意见滞后性**：审计意见反映历史财务状况，可能无法捕捉新兴风险。非标准意见是滞后指标，非先行指标。⭐ 第 5 步 ML 事前预测已部分解决此问题。

## 分析流水线（6 步）

```
第1步              第2步                    第3步              第4步            第5步              第6步
审计意见扫描   →   构建本地数据缓存    →   批量快速评分    →   单股深度报告    →   ⭐ ML 风险预测   →   AI 综合解读
scan.py             build_cache.py          analyze_quick.py    analyze_stock.py    predict.py          当前对话
panda_data API     本地 parquet             1300只 × 5维       1只 × 8段          XGBoost 事前预测     自然语言
实时拉取            离线读取，秒级           排名 + 红绿灯       全面财务体检        概率 + 风险因子       风险判断 + 建议
```

> ⭐ **第 5 步 v3 新增**：不等审计报告发布，用当前季度财务数据 + XGBoost 预测下一期非标概率（AUC 0.788）。
> 与第 1 步形成互补——第 1 步事后排雷，第 5 步事前预测。

## 目录结构

```
├── SKILL.md                                skill 完整规范 (v3.0)
├── README.md                               中文说明（本文件）
├── README.en.md                            英文说明
├── LICENSE                                 GPL-3.0
├── INSTALL.md                              多平台安装指南
├── requirements.txt                        pandas, xgboost, scikit-learn, pytest
├── data/                                   本地缓存（parquet + JSON 模型）
│   ├── fina_cache.parquet                  1300只 × 20季度 × (25科目 + 15比率)
│   ├── fina_industry.parquet               5514只 × 31个申万一级行业
│   └── audit_predictor.json               XGBoost 训练模型（45维特征，AUC 0.788）
├── scripts/
│   ├── scan.py                             第1步：审计意见扫描
│   ├── build_cache.py                      第2步：本地缓存构建 + 单股快览
│   ├── analyze_quick.py                    第3步：1300只批量5维评分
│   ├── analyze_stock.py                    第4步：单股8段深度报告
│   ├── predict.py                          第5步：⭐ ML 审计风险事前预测
│   ├── data.py / universe.py / rules.py / report.py
├── output/                                 生成的数据文件
│   ├── audit_risk_YYYYqN.csv               审计风险清单
│   ├── health_scores_YYYYqN.csv            财务健康评分排名
│   └── audit_predictions_YYYYqN.csv        ML 非标概率预测
├── references/
│   └── need_used_api.md                    5个 panda_data API 文档
└── tests/                                  120 个单元测试
```

## 快速开始

```bash
# 0. 安装依赖
pip install -r requirements.txt

# 1. 构建本地缓存（需要 panda_data 凭证，CSI1000 约 36 秒）
source ~/.zshrc                               # 设置 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD
python scripts/build_cache.py --universe 000852.SH --quarters 20

# 2. 审计意见扫描
python scripts/scan.py --quarter 2025q4

# 3. 1300只批量财务健康评分（纯本地，<1 秒）
python scripts/analyze_quick.py --all

# 4. 单股深度分析
python scripts/analyze_stock.py 600519.SH

# 5. ⭐ ML 审计风险预测（训练 + 预测）
python scripts/predict.py --train --backtest  # 训练模型 + 回测评估
python scripts/predict.py --predict            # 全市场预测
python scripts/predict.py --stock 600267.SH    # 单股预测 + 风险因子解释

# 6. 运行测试
pytest tests/ -v
```

## 核心设计

1. **三步鉴权**：只有第 1 步（审计扫描）、第 2 步（构建缓存）和第 5 步首次训练需要 panda_data 凭证。缓存 + 模型建好后，第 3-5 步全部纯本地读取，无需任何 API 鉴权。

2. **精选字段策略**：从 320+ 个会计科目中精选 25 个最有分析价值的字段（利润表 11 项、资产负债表 10 项、现金流量表 4 项），自动计算 15 个派生比率（ROE、DuPont 分解、现金流质量等）。

3. **行业标准化对比**：每个指标都与同行业股票做 z-score 标准化（MAD 中位绝对差），而非跨行业绝对值比较。医药生物的 ROE 15% 和银行的 ROE 15% 含义完全不同。

4. **事后 + 事前双轨排雷**：第 1 步规则映射（事后，审计报告已出）+ 第 5 步 XGBoost 预测（事前，审计报告未出），互补覆盖。

5. **可被 Agent 直接消费**：所有数据产出为 CSV 或 Parquet 文件，结构固定。其他 Agent 无需运行脚本，直接 `pd.read_csv()` 或 `pd.read_parquet()` 即可消费。

## 数据覆盖

| 维度 | 范围 |
|------|------|
| 股票数 | 1300 只（CSI300 + CSI1000），可扩展到全市场 |
| 季度数 | 最近 20 个季度（2021q3–2026q2） |
| 财务科目 | 25 个精选字段（利润表+资产负债表+现金流） |
| 派生比率 | 15 个（ROE/ROA/毛利率/净利率/杠杆/周转率/现金流质量等） |
| 行业分类 | 31 个申万一级行业，5514 只全 A 股 |
| 审计意见类型 | 10 种（从标准无保留到无法表示意见） |
| ML 模型 | XGBoost（45 维特征，AUC 0.788，53 正样本/3652 训练对） |

## 鉴权分层

| 脚本 | 需要 panda_data？ | 缓存空时 | 缓存有数据时 |
|------|------------------|----------|-------------|
| `scan.py` | ✅ 必须 | 报错退出 | 正常跑 |
| `build_cache.py` build 模式 | ✅ 必须 | 正常拉取 | 增量更新 |
| `build_cache.py` `--info`/`--stock`/`--export-csv` | ❌ 不需要 | 提示构建缓存 | 正常跑 |
| `analyze_quick.py` | ❌ 不需要 | 提示构建缓存 | 正常跑，秒出 |
| `analyze_stock.py` | ❌ 不需要 | 提示构建缓存 | 正常跑，秒出 |
| `predict.py` `--train` | ❌ 不需要（需先有缓存） | 提示先构建缓存 | 正常跑 |
| `predict.py` `--predict`/`--stock` | ❌ 不需要 | 提示先构建缓存 + 训练 | 正常跑，秒出 |

## 已知局限

| 局限 | 详情 |
|------|------|
| 默认覆盖 CSI1000（1300 只） | 通过 `--universe` 扩展到全市场（5000+ 只） |
| ML 训练样本有限 | 53 个非标正样本，AUC 0.788 有效但非高精度 |
| 无 LLM API 集成 | AI 解读通过当前对话上下文完成 |
| 无审计报告 PDF/全文分析 | 仅基于结构化 `opinion` 字段 |
| 不支持实时数据 | 仅做时点分析 |
| 金融企业预测可靠性未知 | 银行/保险财务结构特殊 |
