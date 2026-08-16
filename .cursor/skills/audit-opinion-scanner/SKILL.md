---
name: skill-audit-opinion-scanner
description: 多维财务分析系统。涵盖审计意见扫描、25项财务科目缓存、15项比率计算、行业分类对标、5维快速评分、8段深度分析、综合风险检测。从排雷到估值到 AI 解读，一条流水线完成。
tags: [quant, audit, financial, fundamental, a-stock, csi300, analysis]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-audit-opinion-scanner
  repository_url: https://github.com/quantskills/skill-audit-opinion-scanner
  project_type: skill
  collection: fundamental-analysis
  license: GPL-3.0-only
---

# 多维财务分析系统

## 工具定位

- 工具类型：财务分析（多脚本流水线）
- 解决问题：从审计意见、财务报表、行业对标三个维度对 A 股做全面财务健康评估
- 使用对象：量化策略（排雷过滤）、投研分析（单股深度）、AI Agent（数据喂料）

## 维护者

- duanyong <hiduan@qq.com>
- 上游组织：QuantSkills (https://github.com/quantskills)

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化财务分析研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **数据准确性**：财务数据来源于 panda_data，可能存在错误、遗漏或延迟。请务必对照官方财报（年报、证监会公告）进行验证。
- **不保证收益**：财务分析评分和风险评级为量化启发式指标，非预测。高分不保证未来表现，红灯不保证必然亏损。使用者应自行承担全部投资风险。
- **审计意见滞后性**：审计意见反映历史财务状况，可能无法捕捉新兴风险。非标准意见是滞后指标，非先行指标。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不得视为 QuantSkills 官方背书的产品级工具。

## 适用场景

- 每季度财报发布后，快速扫描全市场（默认沪深300）审计意见，找出财务暴雷股票
- 量化选股策略的排雷过滤器——将"非标准审计意见"股票标记为高风险，不进股票池
- **事前排雷**——用当前季度财务数据，ML 预测下一期被出具"非标"意见的概率，不等审计报告公布就提前减仓
- 对单只股票做 8 段全面财务体检，作为进入股票池前的尽职调查
- 按行业筛选财务健康评分，发现行业内相对优质/劣质的公司
- 将审计意见 + 财务指标 + 行业对标三路数据喂给 AI，获取综合风险判断

## 用户如何使用本 Skill（场景示例）

以下展示用户通过 Claude Code（或其他 Agent）与本 skill 交互的真实对话场景。所有场景均假设已构建本地缓存。

### 场景 1：快速排雷 — "最近有哪些股票审计出问题了？"

> 用户：帮我扫描一下 2024q4 沪深300的审计意见，看看有没有问题股。
>
> Agent：运行 `python scripts/scan.py --quarter 2024q4`，发现 147 只股票年报审计均为标准无保留意见，沪深300本季度无审计暴雷。如果要找问题股，中证1000 有 4 只——要我扫一遍吗？
>
> 用户：扫。
>
> Agent：（运行 `--index 000852.SH`）发现 **000506.SZ 招金黄金（无法表示意见，严重风险）**、600267.SH 海正药业（保留意见，高风险）、000567.SZ 海德股份（保留意见）、603887.SH 城地香江（保留意见）。

### 场景 2：选股前尽调 — "帮我看看这只股票财务健康吗？"

> 用户：电科网安 002268.SZ 能进股票池吗？
>
> Agent：（运行 `python scripts/analyze_stock.py 002268.SZ`）电科网安 2023q4 被出具「带强调事项段的无保留意见」——不算最严重的，但要小心。
>
> 核心数据：
> - ROE 6.48% vs 计算机行业中位 8.12%（📉 行业 P20）
> - 营收 30.73 亿 vs 行业中位 18.33 亿（📈 行业 P75，大公司）
> - **现金流/净利润 = 0.85，远低于行业 2.5**（⚠️ 利润现金含量不足）
> - 资产负债率 38%，无商誉风险
>
> 结论：**规模和净利率没问题，但 ROE 偏低 + 现金流/净利润严重低于行业，说明赚的是"纸面利润"而非真金白银**。建议不入池或减配。

### 场景 3：行业筛选 — "医药生物里哪些公司财务最健康？"

> 用户：帮我在医药生物行业里找财务最健康的公司。
>
> Agent：（运行 `python scripts/analyze_quick.py --industry 医药生物`）医药生物 17 只 CSI300 成分股评分如下：
>
> 🟢 4 只（综合 ≥ 65），🟡 9 只（40-65），🔴 4 只（< 40）
>
> 最强的是 XX（评分 82，ROE 18%，现金流/净利润 3.2）*
> 最弱的是 600267.SH 海正药业（评分 27，ROE 4%，2023q4 保留意见）*
>
> 要我逐个做深度分析吗？

### 场景 4：审计+财务结合 — "这只有保留意见的股票到底有多差？"

> 用户：海正药业被出具保留意见，财务上到底什么情况？
>
> Agent：（运行 `python scripts/analyze_stock.py 600267.SH`）
>
> **审计意见**：2023q4 保留意见 + 强调事项段（中审众环会计师事务所）
> 
> **财务实况**（2026q1）：
> - ROE 4.05% vs 医药生物行业中位 6.2%（行业 P25，偏弱）
> - 商誉/净资产 15%（行业 5%，⚠️ 减值风险）
> - **经营现金流/净利润 = 0.85**（利润现金含量不足）
> - 资产负债率 55%（行业中位 38%，⚠️ 杠杆偏高）
> - 最近 4 个季度净利润持续下滑
> 
> **8 段报告中触发 4 项风险警报**：利润无现金支撑、商誉偏高、高杠杆、营收下滑。
>
> 审计意见和财务数据互相印证：保留意见不是空穴来风。**建议规避**。

### 场景 5：批量投资组合体检 — "我的持仓有没有财务雷？"

> 用户：我的持仓里有 600519、000001、002268、601318...帮我逐个做财务体检。
>
> Agent：好的，逐一分析。（并行运行 4 次 `analyze_stock.py`）
>
> - 🟢 **600519.SH 贵州茅台**：综合评分高，ROE 10%、毛利率 90%、资产负债率 12%，无风险信号
> - 🟡 **000001.SZ 平安银行**：ROE 2.7% 偏低但银行正常，91% 负债率是行业属性非风险
> - 🟡 **002268.SZ 电科网安**：审计有强调事项段，现金流质量存疑
> - 🟢 **601318.SH 中国平安**：综合健康，ROE 7%，现金流充足
>
> 持仓整体健康，但电科网安需要特别关注。

### 场景 6：数据不足时直接读取缓存

> 用户：我只要数据，不要报告。给我所有股票的 ROE 和资产负债率。
>
> Agent：（直接读 parquet）300 只 CSI300 最新季度数据已提取。ROE 均值 6.8%（行业中位 7.2%），资产负债率均值 52%。CSV 已导出到 `/tmp/fina_summary.csv`。

## 依赖与鉴权

本 skill 的数据来源是 **panda_data**（金融市场数据 API）。

| 脚本 | 是否需要 panda_data 鉴权 | 说明 |
|------|------------------------|------|
| `scan.py` | ✅ 需要 | 实时拉取审计意见，每次运行调 API |
| `build_cache.py` (build 模式) | ✅ 需要 | 首次构建本地缓存时调 API，之后不需要 |
| `build_cache.py` (`--info`, `--stock`, `--export-csv`) | ❌ 不需要 | 纯本地读取缓存 |
| `analyze_quick.py` | ❌ 不需要 | 纯本地读取缓存 |
| `analyze_stock.py` | ❌ 不需要 | 纯本地读取缓存 |

**panda_data 鉴权要求**：

- 环境变量 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD` 必须已设
- 未配置时，`scan.py` 和 `build_cache.py`（build 模式）会直接报错退出
- 其他所有脚本依赖 `data/fina_cache.parquet` 和 `data/fina_industry.parquet` 本地缓存
- **如果缓存已构建好，无需 panda_data 也可使用第 3/4 步的全部分析功能**

```bash
# 配置鉴权（写入 ~/.zshrc 持久化）
export PANDA_DATA_USERNAME="your_username"
export PANDA_DATA_PASSWORD="your_password"

# 验证鉴权是否生效
python scripts/scan.py --quarter 2025q4
```

## 分析流水线（6 步）

```
第1步              第2步                    第3步              第4步            第5步            第6步
审计意见扫描   →   构建本地数据缓存    →   批量快速评分    →   单股深度报告    →   ML 审计风险预测   →   AI 综合解读
scan.py             build_cache.py          analyze_quick.py    analyze_stock.py    predict.py          当前对话
panda_data API      本地 parquet            1300只 × 5维       1只 × 8段           XGBoost 事前预测     自然语言
实时拉取            离线读取，秒级           排名 + 红绿灯       全面财务体检        概率 + 风险因子       风险判断 + 建议
```

**⭐ 第 5 步是新增的 ML 事前预测，与第 1 步形成互补**：
- 第 1 步：**事后排雷**——审计报告已出，规则映射风险等级
- 第 5 步：**事前预测**——审计报告未出，根据最新季度财务数据预测下期非标概率

---

## 第 1 步：审计意见扫描

**做什么**：每季度财报发布后，拉取全市场（默认沪深300）审计意见，按监管标准映射到风险等级，输出股票排雷清单。

**⚠️ 需要鉴权**：panda_data `get_audit_opinion`

```bash
# 单季度（需要 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD）
python scripts/scan.py --quarter 2024q4

# 多季度
python scripts/scan.py --start-quarter 2023q4 --end-quarter 2024q4

# 指定指数
python scripts/scan.py --quarter 2024q4 --index 000852.SH     # 中证1000
python scripts/scan.py --quarter 2024q4 --index 000905.SH     # 中证500
```

**产出数据列**：按季度命名的 CSV 文件，含以下列：

| 列 | 说明 |
|---|---|
| `symbol` | 股票代码 |
| `name` | 股票名称 |
| `quarter` | 报告季度 |
| `date` | 公告日期 |
| `agency` | 会计师事务所 |
| `audit_type` | 审计报告类型 |
| `opinion` | 审计意见原始值 |
| `risk_level` | 风险等级（0=低, 1=中, 2=高, 3=严重, -1=待确认） |
| `risk_label` | 风险等级中文标签 |

**风险映射规则**：

| 审计意见 | 风险等级 |
|----------|----------|
| `unqualified_opinion` | 0 低风险 |
| `unqualified_opinion_with_emphasis-of-matter_paragraph` | 1 中风险 |
| `unqualified_opinion_with_material_uncertainty` | 1 中风险 |
| `modified_unqualified` | 1 中风险 |
| `qualified_opinion` | 2 高风险 |
| `qualified_opinion_with_basis_for_qualification_paragraph` | 2 高风险 |
| `adverse_opinion` | 3 严重风险 |
| `disclaimer_of_opinion` | 3 严重风险 |
| `no_audit_performed` | -1 待确认 |

---

## 第 2 步：构建本地财务数据库

**做什么**：从 panda_data 拉取 25 个精选财务科目（覆盖利润表、资产负债表、现金流量表），按季度缓存到本地 parquet，自动计算 15 个派生比率，附加 31 个申万行业分类。之后所有分析脚本都是纯本地读取，秒级响应，不再调 API。

**⚠️ 需要鉴权**：panda_data `get_fina_reports` + `get_industry_constituents`（仅首次构建。构建完成后，缓存内所有操作均无鉴权）

```bash
# 首次构建：CSI300，最近 8 个季度（300 只股票，约 5 秒，需要鉴权）
python scripts/build_cache.py --universe 000300.SH --quarters 8

# CSI1000（1000 只，约 2 分钟，需要鉴权）
python scripts/build_cache.py --universe 000852.SH --quarters 8 --batch-size 50

# 增量更新（需要鉴权）
python scripts/build_cache.py --incremental

# ── 以下命令均无需鉴权，纯本地读取 ──

# 查看缓存状态
python scripts/build_cache.py --info

# 单股快览（绝对值 + 比率 + 行业对比）
python scripts/build_cache.py --stock 600519.SH

# 导出全量数据到 CSV
python scripts/build_cache.py --export-csv all_financial_data.csv
```

**缓存文件**（`data/` 目录）：

| 文件 | 内容 | 规模 |
|------|------|------|
| `fina_cache.parquet` | 25 科目 + 15 比率 × 8 季度 | 300 只 × 约 2100 行, ~0.5 MB |
| `fina_industry.parquet` | 申万 L1/L2/L3 行业分类 | 5514 只, ~0.2 MB |

**25 个精选科目**：

| 类别 | 科目 | 说明 |
|------|------|------|
| 利润表 | `is_revenue` | 营业收入 |
| | `is_oper_cost` | 营业成本 |
| | `is_gross_profit` | 毛利 |
| | `is_sell_exp`, `is_admin_exp`, `is_rd_exp`, `is_fin_exp` | 四费 |
| | `is_operate_profit` | 营业利润 |
| | `is_total_profit` | 利润总额 |
| | `is_n_income_attr_p` | 归母净利润 |
| | `is_n_income` | 净利润 |
| 资产负债表 | `bs_total_assets`, `bs_total_liab` | 总资产/总负债 |
| | `bs_total_hldr_eqy_exc_min_int` | 归母权益 |
| | `bs_total_cur_assets`, `bs_total_cur_liab` | 流动/负债 |
| | `bs_money_cap`, `bs_inventory` | 货币资金/存货 |
| | `bs_acct_payable`, `bs_goodwill`, `bs_lt_borr` | 应付/商誉/长期借款 |
| 现金流量表 | `cfs_net_cash_operating` | 经营现金流 |
| | `cfs_net_cash_investing` | 投资现金流 |
| | `cfs_net_cash_financing` | 筹资现金流 |
| | `cfs_end_cash_equiv` | 期末现金余额 |

**15 个派生比率**：ROE、ROA、毛利率、净利率、营业利润率、资产负债率、权益乘数、流动比率、资产周转率、存货周转率、现金流/净利润、现金流/营收、商誉/净资产、研发/营收。

---

## 第 3 步：批量快速评分

**做什么**：对缓存中所有股票（最新季度）做 5 维评分，输出排名 CSV。适合快速筛选。

**🔓 零鉴权**：纯本地读取 `data/fina_cache.parquet`

```bash
# 全量评分 → CSV
python scripts/analyze_quick.py --all

# Top 20 最强
python scripts/analyze_quick.py --top 20

# Worst 20 最弱
python scripts/analyze_quick.py --worst 20

# 按行业筛选
python scripts/analyze_quick.py --industry 医药生物
```

**产出数据列**：按季度命名的 CSV 文件，含以下列：

| 列 | 说明 |
|------|------|
| `symbol`, `l1_name`, `quarter` | 标识 |
| `composite`, `light` | 综合评分（0-100）+ 🟢🟡🔴 |
| `rank` | 排名 |
| `profitability_score`, `profitability_val`, `profitability_z` | 盈利能力（ROE + 行业 z-score） |
| `growth_score`, `growth_val`, `growth_z` | 成长性（净利润 YoY + 行业 z-score） |
| `scale_score`, `scale_val`, `scale_z` | 规模体量（营收 + 行业 z-score） |
| `efficiency_score`, `efficiency_val`, `efficiency_z` | 盈利效率（净利率 + 行业 z-score） |
| `stability_score`, `stability_val`, `stability_z` | 现金流质量（CFO/NP + 行业 z-score） |

**5 维评分逻辑**：每个维度计算 vs 同行业的 z-score（MAD 标准化），通过 sigmoid 映射到 0-100 分，加权合成综合分。

---

## 第 4 步：单股深度报告

**做什么**：对单只股票输出一份完整的 8 段财务体检报告。这是整个系统的核心产出。

**数据来源**：本地 `data/fina_cache.parquet` + `data/fina_industry.parquet`（无鉴权）

```bash
python scripts/analyze_stock.py 600519.SH

# 导出为单行宽 CSV（适合批量分析）
python scripts/analyze_stock.py 600519.SH --csv
```

**报告结构（8 段）**：

| 段 | 标题 | 内容 |
|------|------|------|
| **一** | 核心财务指标 · 逐季对比 | 11 项科目（营收→净利润）× 全部季度 + 趋势箭头，每个指标标注首尾变化幅度 |
| **二** | 盈利能力 · 逐层拆解 | 毛利率 → 营业利润率 → 净利率，每期标注费用率（四费合计/营收）和利润留存率 |
| **三** | DuPont ROE 分解 | ROE = 净利率 × 总资产周转率 × 权益乘数，每期分解 + 文字解读（高杠杆/低周转/低利润） |
| **四** | 资产负债表 · 健康度 | 资产负债率、流动比率（含行业中位对比）、商誉/净资产、长期借款/净资产 + 风险提示 |
| **五** | 现金流 · 质量与趋势 | 经营/投资/筹资三段式逐期表 + 自由现金流（FCF）+ CFO/NP 含金量评级 |
| **六** | 增长轨迹 | 5 项指标（营收/利润/资产/权益/现金流）逐期趋势 + 同季度去年对比（YoY 增速） |
| **七** | 行业百分位排名 | 12 项指标 vs 同行业所有股票的百分位 + 🟢🟡🔴 评级 |
| **八** | 综合风险检测 | 12 项自动检查（ROE为负 / 利润无现金支撑 / 流动性危机 / 商誉炸弹 / 连续亏损 / 营收萎缩…），分 danger/warning 两级 |

**多期数据的价值**：同季度去年对比（YoY）消除季节性，Q4 利润通常高于 Q1（白酒尤甚），真正有意义的下跌是 YoY 下降，而非环比。

---

## 第 5 步：ML 审计风险预测（⭐ 新增 — 事前排雷）

**做什么**：基于 XGBoost 训练模型，用当前最新季度的 45 维财务特征（25 科目 + 15 比率 + 5 YoY 变化 + 行业），预测下一期年报（Q4）被出具"非标准审计意见"的概率。

**核心理念**：不等审计报告公开披露，提前 1-2 个季度预估哪些股票有财务暴雷风险。

**🔓 零鉴权**：纯本地读取 `data/fina_cache.parquet` + `data/audit_predictor.json` 模型文件

```bash
# 首次训练模型（需要已构建多季度缓存 + 审计标签）
python scripts/predict.py --train

# 训练 + 回测评估（按季度留一法交叉验证）
python scripts/predict.py --train --backtest

# 对最新季度全市场预测 → CSV
python scripts/predict.py --predict

# 单只股票预测 + 风险驱动因子解释
python scripts/predict.py --stock 600267.SH
```

**产出数据列**（`output/audit_predictions_{quarter}.csv`）：

| 列 | 说明 |
|---|---|
| `symbol` | 股票代码 |
| `quarter` | 预测所依据的财务数据季度 |
| `prob_nonstandard` | 被出具非标审计意见的概率 [0, 1] |
| `risk_tier` | 风险等级：🟢安全（<0.1）/ 🟡关注（0.1-0.3）/ 🟠警示（0.3-0.5）/ 🔴高危（>0.5） |

**模型详情**：

| 项目 | 值 |
|------|------|
| 算法 | XGBoost（`max_depth=4`, `scale_pos_weight=auto`） |
| 特征维度 | 45（25 科目 + 15 比率 + 5 YoY + 行业编码） |
| 训练窗口 | CSI1000，2020q4–2025q4（5 年 × 6 个 Q4 年报） |
| 正样本 | 53 个非标审计意见（1.1%），自动类别不平衡加权 |
| 回测 AUC | **0.788**（逐年上升：0.71→0.77→0.80→0.87） |
| Top 风险因子 | 利润总额、归母净利润、财务费用、营收增速、净利率 |

**⚠️ 约束与局限性**：

- 模型预测的是基于历史模式的**统计概率**，不是确定性的审计结论
- 训练样本有限（53 个非标），AUC 0.788 是有效但非高精度水平——建议结合第 1 步规则 + 第 4 步深度报告综合判断
- 金融企业（银行/保险）的财务结构特殊，利润和现金流模式与非金融企业不同，模型对此类样本的预测可靠性未知
- 预测仅在最新季度数据上有意义；越接近年报披露日，财务数据越"新鲜"，预测越准确

---

## 第 6 步：AI 综合解读

**做什么**：结合审计意见 + 财务指标 + 行业对标 + 多期趋势，让 AI 给出综合判断。

**方式**：在本对话中直接提股票代码，或贴入第 4 步输出的关键数据。AI 会整合：
- 审计意见有无异常（来自第 1 步）
- 核心指标行业分位（来自第 3/4 步）
- 多期趋势是否有恶化（来自第 4 步 DuPont + 增长率）
- 风险检测结果（来自第 4 步第 8 段）
- 给出综合结论和建议

---

## 快速参考

```bash
# ── 环境（在 skill 根目录下执行） ──
source ~/.zshrc                                    # panda_data 凭证
pip install -r requirements.txt

# ── 初始化（首次） ──
python scripts/build_cache.py --universe 000300.SH --quarters 8
pytest tests/ -v                                   # 44 tests

# ── 日常使用 ──
python scripts/scan.py --quarter 2025q4            # 1. 审计扫描
python scripts/build_cache.py --incremental         # 2. 增量更新缓存
python scripts/analyze_quick.py --all               # 3. 批量评分
python scripts/analyze_stock.py 600267.SH           # 4. 单股深报

# ── 缓存查询（无鉴权） ──
python scripts/build_cache.py --info                # 缓存状态
python scripts/build_cache.py --stock 600519.SH     # 单股快览
python scripts/build_cache.py --export-csv all.csv  # 全量导出

# ── 评分查询（无鉴权） ──
python scripts/analyze_quick.py --top 20            # 最强 20
python scripts/analyze_quick.py --worst 20          # 最弱 20
python scripts/analyze_quick.py --industry 医药生物


---

## 其他 Agent 如何使用本 Skill

本 skill 的核心价值不是代码，是 **数据产出物**。任何 Agent（Build Agent、Alpha Agent、测试 Agent、主 Agent）通过以下三种方式消费：

### 方式一：读数据文件（最简单）

审计扫描和财务评分的结果通过 `scan.py` 和 `analyze_quick.py` 产出，其他 Agent 按约定路径读取。约定：**所有路径以本 skill 根目录为基准**。

```python
from pathlib import Path
import pandas as pd

# 如果是本 skill 内部脚本：用 __file__ 自定位
skill_root = Path(__file__).resolve().parent.parent  # scripts/ → skill根目录

# 如果是外部 agent：假设 skill 已安装，通过相对路径 + 当前工作目录定位
# 或者通过环境变量 / 配置文件传入
skill_root = Path("path/to/skill-audit-opinion-scanner")
```

### 方式二：直接读 Parquet

```python
import pandas as pd
from pathlib import Path

skill_root = Path(__file__).resolve().parent.parent  # 自定位

# 全量财务数据缓存
df = pd.read_parquet(skill_root / "data" / "fina_cache.parquet")
latest = df[df["quarter"] == df["quarter"].max()]
stock = latest[latest["symbol"] == "000001.SZ"].iloc[0]

# 行业分类缓存
indu = pd.read_parquet(skill_root / "data" / "fina_industry.parquet")
row = indu[indu["stock_symbol"] == "000001.SZ"]
print(row[["stock_symbol", "l1_name", "l2_name"]].values)
```

### 方式三：调脚本出纯数据

```bash
# 全量导出到标准 CSV（可被任何语言消费）
python scripts/build_cache.py --export-csv /tmp/all_financial_data.csv

# 单股数据导出（一个股票 = 一行 CSV，含 250+ 列）
python scripts/analyze_stock.py 600519.SH --csv --output /tmp/600519.csv
```

### 集成示例：量化策略排雷

```python
from pathlib import Path
import pandas as pd

# 约定：外部 agent 通过环境变量或配置获取 skill 路径
# 内部脚本用 Path(__file__).resolve().parent.parent 自定位
SKILL_ROOT = Path(__file__).resolve().parent.parent  # 本 skill 内部

def load_audit_blacklist(skill_root: Path, quarter: str) -> list[str]:
    path = skill_root / "output" / f"audit_risk_{quarter}.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return df[df["risk_level"] >= 2]["symbol"].tolist()

def load_financial_health(skill_root: Path, quarter: str) -> pd.DataFrame:
    path = skill_root / "output" / f"health_scores_{quarter}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)

def load_cache(skill_root: Path) -> pd.DataFrame:
    return pd.read_parquet(skill_root / "data" / "fina_cache.parquet")

# 使用
blacklist = load_audit_blacklist(SKILL_ROOT, "2025q4")
scores = load_financial_health(SKILL_ROOT, "2026q1")
candidates = scores[scores["composite"] >= 60] if not scores.empty else pd.DataFrame()
candidates = candidates[~candidates["symbol"].isin(blacklist)]
```

### 数据文件约定

| 文件 | 路径 | 格式 | 更新频率 | 内容 |
|------|------|------|----------|------|
| 审计风险清单 | `output/audit_risk_{quarter}.csv` | CSV, UTF-8 BOM | 每季度 | symbol, opinion, risk_level, risk_label |
| 财务健康评分 | `output/health_scores_{quarter}.csv` | CSV, UTF-8 BOM | 每季度 | 5维评分, 综合分, 排名, 红绿灯 |
| 财务原始数据 | `data/fina_cache.parquet` | Parquet | 每季度增量 | 25科目 × N季度, 含行业标签 |
| 行业分类 | `data/fina_industry.parquet` | Parquet | 全市场一次性 | 5514只, L1/L2/L3 三级分类 |

**约定**：文件名中 `{quarter}` 格式为 `YYYYqN`（如 `2026q1`）。文件由本 skill 的脚本维护，消费方只读不写。

### 当前覆盖范围

- **股票数**：1300 只（CSI300 + CSI1000），可通过 `--universe 000852.SH` 扩展
- **季度数**：最近 20 个季度（`build_cache.py --quarters 20`，覆盖 2021q3–2026q2）
- **行业**：31 个申万一级行业，全市场 5514 只
- **缓存大小**：约 4.6 MB（两份 parquet），15000+ 行的审计标签
- **ML 模型**：`data/audit_predictor.json`（XGBoost，45 维特征，AUC 0.788）

---

## 依赖

- **panda_data** Python 库（仅第 1/2 步需要鉴权，第 3/4 步纯本地）
- pandas >= 2.0, pytest >= 7.0
- 环境变量：`PANDA_DATA_USERNAME`, `PANDA_DATA_PASSWORD`

## 数据接口

| 接口 | 步骤 | 用途 |
|------|------|------|
| `get_audit_opinion` | 第 1 步 | 拉取审计意见 |
| `get_fina_reports` | 第 2 步 | 拉取 25 个精选科目（从 320+ 字段中筛选） |
| `get_industry_constituents` | 第 2 步 | 拉取全市场申万行业分类 |
| `get_index_weights` | 第 1/2 步 | 获取指数成分股 |
| `get_last_trade_date` | 辅助 | 获取最新交易日 |

字段详见 `references/need_used_api.md`。

## 模块结构

```
├── SKILL.md
├── README.md / README.en.md
├── LICENSE                     (GPL-3.0)
├── INSTALL.md                   (多平台安装指南)
├── requirements.txt
├── data/                        本地数据缓存（parquet + JSON）
│   ├── fina_cache.parquet      1300只 × 20季度 × (25科目 + 15比率)
│   ├── fina_industry.parquet   5514只 × 31个申万L1行业
│   └── audit_predictor.json    XGBoost 训练模型（45维特征）
├── scripts/
│   ├── scan.py                  第1步: 审计意见扫描 + 风险映射
│   ├── build_cache.py           第2步: 财务数据缓存构建 + 单股快览
│   ├── analyze_quick.py         第3步: 1300只批量5维评分
│   ├── analyze_stock.py         第4步: 单股8段深度报告
│   ├── predict.py               第5步: ML审计风险事前预测（新增）
│   ├── data.py                  panda_data API 封装
│   ├── universe.py              股票池解析（指数成分股）
│   ├── rules.py                 审计意见 → 风险等级映射 (10种)
│   ├── report.py                CSV + Markdown 输出
├── references/
│   └── need_used_api.md         5个 panda_data API 完整入参/响应
└── tests/                       120 个单元测试
```

## 假设条件

- 财务数据（`get_fina_reports`）的 `end_quarter` 参数可靠地返回对应季度的数据
- `get_industry_constituents` 返回的行业分类覆盖全 A 股，且申万分类标准稳定
- 审计意见的 `opinion` 字段枚举值由 panda_data 服务端维护，新增类型需更新 `OPINION_RISK_MAP`
- 最新季度（如 2026q2）的数据可能不完整（财报未披露完毕），评分脚本自动选择上一个数据充分的季度
- 行业百分位排名依赖同行业至少有 3 只股票有数据
- 所有金额单位为人民币（元），不做币种转换
- 同比增速（YoY）通过与去年同期（如 2026q1 vs 2025q1）对比计算，消除季节性

## 可被 Alpha 调用

- 是
- 调用方式：Alpha 从 `data/fina_cache.parquet` 读取单只或多只股票的财务数据 + 比率 + 行业标签
- 调用限制：Alpha 不调用本 skill 的脚本，直接 `pd.read_parquet()` 即可
- 依赖数据：本 skill 维护 `data/` 目录下的 parquet 缓存文件

## 是否需要生产结果

- 是否生成 `数据库.parquet`：是（`data/fina_cache.parquet` 与 `data/fina_industry.parquet`）
- 产出 CSV 报告（`output/` 目录）按需生成，非核心交付物

## Changelog

### v3 (current)

- **⭐ 第 5 步：ML 审计风险事前预测**：XGBoost 模型，用最新季度 45 维财务特征预测下期年报非标审计意见概率（AUC 0.788）
- **数据扩展**：缓存从 CSI300（300 只 × 8 季度）扩展到 CSI1000（1300 只 × 20 季度，2021q3–2026q2）
- **新脚本**：`predict.py`（训练/预测/回测/单股解释）+ `test_predict.py`（25 个测试）
- **新依赖**：`xgboost>=2.0`, `scikit-learn>=1.3`
- 测试从 95 个增至 **120 个**，全部通过

### v2

- **统一缓存**：放弃 `get_fina_performance`（季度过滤不可靠），改用 `get_fina_reports` + 25 个精选字段
- **两套 parquet 缓存**：`fina_cache.parquet`（财务科目+比率）+ `fina_industry.parquet`（申万行业分类）
- **三层分析体系**：批量5维评分 → 单股8段深报 → AI 综合解读
- **8 段深度报告**：核心财务指标、盈利能力拆解、DuPont 分解、资产负债表健康度、现金流质量、增长轨迹、行业百分位排名、12项自动风险检测
- **15 个派生比率**：ROE/ROA/毛利率/净利率/杠杆/周转率/现金流质量等，涵盖 DuPont 分解
- **行业标准化评分**：所有指标与同行业做 z-score 标准化（MAD），非跨行业绝对值比较
- **鉴权分层**：仅 scan/build 需要 panda_data 凭证，其余脚本纯本地读取
- **Agent 可消费数据**：CSV/Parquet 固定结构，外部 Agent 无需运行脚本即可消费
- **可移植路径**：所有路径通过 `Path(__file__).resolve().parents[1]` 自定位
- **5 平台部署**：Claude Code / Standalone / Codex / Cursor / Hermes / OpenClaw

### v1 (deprecated)

- 仅审计意见扫描：季度拉取 → 规则映射 → 风险标签
- `get_fina_performance` 作为财务数据源（季度重复 80%+，已废弃）
- 仅支持单季度、单指数扫描
- 无行业分类、无评分系统、无深度报告

## Known Limitations

1. **默认仅 CSI300 财务缓存**：三表缓存（`fina_cache.parquet`）当前仅覆盖 CSI300（300 只），需手动 `--universe 000852.SH` 扩展
2. **get_fina_performance 已废弃**：v1 使用此接口的数据已全部迁移到 `get_fina_reports`，旧 `fina_performance.parquet` 不再生成
3. **最新季度可能不完整**：最新一个季度的财报可能尚未披露完毕（如 2026q2 仅 4 只股票有数据），评分自动回退到上一个完整季度
4. **不分析审计报告全文**：审计意见分析仅基于结构化 `opinion` 字段，不涉及 PDF/全文语义分析
5. **AI 解读依赖当前对话**：无外部 LLM API 集成，综合解读通过本对话上下文完成
6. **实时数据不支持**：所有分析基于缓存数据（时点），不支持盘中实时财务指标更新
7. **行业中位计算采样**：深度报告中，行业百分位对比采样同行业前 30 只股票以控制计算时间
8. **非金融企业部分科目为空**：银行、保险等金融企业的 `is_gross_profit`、`bs_inventory` 等科目天然为空
