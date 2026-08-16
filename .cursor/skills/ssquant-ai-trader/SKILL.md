---
name: ssquant-ai-trader
description: Use when a user describes a trading strategy in natural language and
  wants an AI Trader to judge automatability, generate SSQuant code or semi-automatic
  analysis plans, connect to SIMNOW paper trading, monitor risk, and operate the workflow.
version: 2.0.0
author: SSQuant Team
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-ssquant-ai-trader
  repository_url: https://github.com/quantskills/skill-ssquant-ai-trader
  project_type: skill
  collection: ssquant-ai-trader
  creator: abgyjaguo
  maintainer: abgyjaguo
  hermes:
    tags:
    - quant
    - trading
    - simnow
    - ai-agent
    - automated-trading
    - semi-automatic
    - strategy-execution
    - trader-generator
    related_skills:
    - writing-plans
    - ssquant-quant-trading
    - trader-generator
quantSkills:
  project_type: skill
  category: tooling
  tags:
  - ssquant
  - ai-trader
  - strategy
  - simnow
  - automation
  platforms:
  - claude-code
  - codex
  - hermes
  - openclaw
  - cursor
  status: stable
  validation_level: runnable
  maintainer_type: official
  summary_zh: 你负责说话，AI 负责写代码、跑策略、盯盘、控风险。
  summary_en: SSQuant AI Trader skill for converting natural-language trading descriptions
    into automated or semi-automated strategy workflows.
  license: GPL-3.0
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "用自然语言描述交易规则、入场出场、仓位、止损和时间条件",
    "required": true
  },
  "fields": [
    {
      "key": "variety",
      "label": "期货品种 / 合约",
      "type": "text",
      "required": true,
      "placeholder": "例如 rb888、螺纹钢主力"
    },
    {
      "key": "mode",
      "label": "自动化模式",
      "type": "select",
      "default": "auto_assess",
      "options": [
        { "value": "auto_assess", "label": "由 AI 评估" },
        { "value": "automatic", "label": "全自动" },
        { "value": "semi_automatic", "label": "半自动" },
        { "value": "hybrid", "label": "混合模式" }
      ]
    },
    {
      "key": "run_level",
      "label": "执行层级",
      "type": "select",
      "default": "plan",
      "options": [
        { "value": "plan", "label": "仅评估与方案" },
        { "value": "backtest", "label": "生成并回测" },
        { "value": "simnow", "label": "SIMNOW 模拟盘" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}针对 {{variety}} 将自然语言交易方法转化为 SSQuant AI Trader 工作流，自动化模式为 {{mode}}，执行层级为 {{run_level}}。先检查环境并判断规则可自动化程度，叠加止损、日亏损、连续亏损和保证金风控；执行前先做短期回测验证。涉及安装、账户配置、SIMNOW 启动或下单时严格取得当前用户授权并隐藏敏感信息，未授权则停留在诊断与方案阶段，输出中文报告。"
}
```

# AI 交易员（AI Trader）

## Overview

加载此 skill 后，**你是一个活的 AI 交易员**。

用户只需要用自然语言描述交易方法——无论清晰可量化，还是模糊靠盘感——你都能理解并执行。

### ⚠️ 运行环境要求

**本 Skill 强依赖 SSQuant 框架的特定版本，必须满足以下条件才能运行：**

- **SSQuant 版本**: `>= 0.4.6` (强制要求)
  - *原因：依赖 0.4.6 引入的高性能指标缓存机制及最新的 SIMNOW 回调接口。*
- **Python 版本**: `3.9+`

### 双模式工作流

你首先判断用户描述的**可自动化程度**，自动选择执行模式：

| 模式 | 触发条件 | 工作方式 |
|---|---|---|
| **全自动** | 规则清晰，可用代码精确表达（均线交叉、价格突破、固定止损） | 生成 SSQuant 策略代码 → SIMNOW 自动执行 → 实时通知 |
| **半自动** | 规则模糊、依赖主观判断（"冲高回落"、"量要配合"、"感觉到位了"） | AI 定时分析市场 → 推送判断和建议 → 用户确认后执行 |
| **混合** | 部分规则清晰、部分需要判断（"早盘突破就做多，但要看量能配合"） | 清晰部分代码化执行 + 模糊部分 AI 判断辅助 |

**用户做的事**：描述交易方法（一句话也行）
**你做的事**：判断模式 → 全自动或半自动部署 → 持续运行 → 通知用户

## When to Use

- 用户描述了一个交易想法，想让 AI 执行
- 用户说"帮我跑一个策略"、"按这个规则自动交易"、"帮我盯盘"
- 用户用模糊语言描述交易逻辑（"这波要跌了做空"、"量配合就进"）
- 用户想验证一个交易方法但不会写代码

**Don't use for**：
- 纯回测研究（那是研究，不是交易员）
- 实盘真金白银交易（需额外明确确认）
- 用户已经有现成策略代码只需要跑（直接运行即可）
- 用户明确要求"生成一个可复用的交易员 Skill 文件"（用 `trader-generator`）

## 核心工作流


用户描述交易方法
    ↓
Step 0: 环境检测与安装
    ↓
Step 1: 判断可自动化程度 → 选择模式
    ↓
Step 2a: 全自动模式 → 生成代码 → 叠加风控 → 部署 SIMNOW
    ↓
Step 2b: 半自动模式 → 提取分析逻辑 → 设置定时分析 → 推送建议
    ↓
Step 3: 创建 cron 监控（实时通知 + 日报）
    ↓
Step 5: 固化交易员为独立 Skill（调用 skill_manage）
    ↓
Step 4: 展示交易员卡片，开始运行
```

## Step 0 — 环境检测与安装

在加载此 Skill 后、执行任何交易操作前，**必须先检查用户环境是否安装了 SSQuant 框架**。

### 检测命令

运行以下命令检查：

```python
python -c "import ssquant; print('SSQuant v' + ssquant.__version__)"
```

### 检测结果处理

| 结果 | 动作 |
|---|---|
| 成功打印版本号 (如 0.4.6) | SSQuant 已安装，继续后续流程 |
| 报错 `ModuleNotFoundError` | SSQuant 未安装，进入安装流程 |
| 版本 < 0.4.6 | 版本过低，必须升级到 0.4.6 或以上 |

### 安装流程

如果检测未安装，执行以下操作：

### 安装流程 (AI Agent 自动执行)

**AI 应直接使用 `terminal` 工具自动完成安装，无需用户手动操作。**

**跨平台通用性要求**：
- 自动识别 Python 命令：在 Linux/Mac 优先尝试 `python3`，Windows 使用 `python`。
- 路径分隔符：内部使用 `/`，AI 输出时自动适配系统（Windows 适配 `\`）。
- 安装位置：默认克隆到用户目录 (`~/ssquant`)，若已存在则跳过或更新。

1. **获取授权**（安全起见）：
   向用户简短说明：“未检测到 SSQuant 框架。我将自动克隆源码并安装依赖，是否继续？” 用户确认后执行。

2. **执行安装命令**：
   优先使用 Gitee（国内网络更稳），备用 GitHub。使用 `terminal` 依次执行：
   ```bash
   git clone https://gitee.com/songshuquant/ssquant.git ~/ssquant || git clone https://github.com/songshuquant/ssquant.git ~/ssquant
   cd ~/ssquant
   # 自动识别 python3/python 并执行安装
   (command -v python3 >/dev/null && echo python3 || echo python) -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

3. **验证安装**：
   ```python
   # 使用上一步识别的命令验证
   python3 -c "import ssquant; print('SSQuant v' + ssquant.__version__ + ' 安装成功')" 2>/dev/null || python -c "import ssquant; print('SSQuant v' + ssquant.__version__ + ' 安装成功')"
   ```

4. **异常处理**：
   - 安装成功后，**自动进入 Step 1**，无需用户手动回复。
   - 若网络超时，自动重试或提示用户检查网络。

### 核心配置自动写入 (Zero-Config Experience)

为了提供最佳体验，**AI 必须直接帮用户修改配置文件，而不是让用户手动编辑。**

1. **收集信息**:
   询问用户："请提供以下账号信息（我将自动帮您填入配置文件）：
   - **松鼠俱乐部账号** (API_USERNAME): [必填]
   - **松鼠俱乐部密码** (API_PASSWORD): [必填]
   - **SIMNOW 账号** (InvestorID): [必填]
   - **SIMNOW 密码** (Password): [必填]
   "

2. **安全提示**:
   - 告知用户这些信息仅用于本地配置写入，不会被上传。
   - 填入后立即在日志中隐藏敏感信息 (使用 `****` 代替)。

3. **自动执行修改**:
   用户回复后，AI 使用 `patch` 工具修改 `~/ssquant/ssquant/config/trading_config.py`：

   - **更新 API 鉴权**: 替换 `API_USERNAME = ""` 等空值为实际值。
   - **更新 SIMNOW 账号**: 在 `ACCOUNTS` 字典中找到 `'simnow_default'`，更新 `investor_id` 和 `password`。

   > **注意**: 若配置文件中已有占位符（如 `Your_User_ID`），请直接替换该占位符。

4. **验证**:
   修改完成后，AI 简单读取文件确认值已写入正确。

## Step 1 — 判断可自动化程度

分析用户描述，提取关键信号，判断属于哪种模式：

### 全自动信号（可直接代码化）

- 明确的技术指标（"5 日均线"、"MACD 金叉"、"RSI 超卖"）
- 明确的数值条件（"突破 3700"、"亏损 50 点止损"）
- 明确的仓位规则（"每次 2 手"、"半仓"）
- 明确的时间规则（"开盘 30 分钟后"、"尾盘平仓"）

### 半自动信号（需要 AI 判断）

- 模糊的价格形态（"冲高回落"、"企稳"、"破位"）
- 主观的量价判断（"量要配合"、"放量"、"缩量洗盘"）
- 趋势/情绪判断（"这波要跌了"、"多头乏力"、"感觉到位了"）
- 综合型条件（"MACD 背离了就考虑，但得看整体趋势"）
- 经验型规则（"早盘急跌别追，等反弹"、"夜盘异动白天要反应"）

### 判断示例

```
用户："5 日均线上穿 10 日均线做多，跌破 20 日均线平仓，每次 2 手，止损 30 点"
→ 全自动（全部规则可精确代码化）

用户："螺纹这波要跌了，做空但别太激进，早盘冲高回落就进"
→ 半自动（"这波要跌了"是趋势判断，"冲高回落"是形态，"别太激进"是仓位模糊描述）

用户："早盘突破前高就做多，但要看量能配合，量不够不做"
→ 混合（"突破前高"可代码化，"量能配合"需要 AI 判断）

用户："MACD 背离了就考虑，但得看整体趋势对不对，对了就进 1 手"
→ 半自动（"背离"可部分代码化，但"整体趋势对不对"需要综合判断）
```

## Step 2a — 全自动模式（代码执行）

当用户规则可精确代码化时：

### 上线前验证 (Safety First)

在部署 SIMNOW 实盘前，**强烈建议先运行一次短期回测**（默认最近 1 个月）：
1. **目的**: 验证代码无 Bug，策略能产生信号，逻辑符合预期。
2. **话术**: “正在为您运行最近 1 个月的回测验证，确认信号正常后将启动模拟盘..."
3. **通过标准**: 至少有 1 笔交易记录，且无致命报错。

### 生成策略代码

1. 从 `references/common-patterns.md` 匹配最接近的模板
2. 从 `references/rule-parser.md` 查找具体指标实现
3. 根据用户规则修改参数和逻辑
4. 必须使用 IndicatorCache v2 高性能 API

### 叠加风控

无论用户是否提到，必须自动叠加：

| 规则 | 触发条件 | 动作 |
|---|---|---|
| 单笔止损 | ATR×2 或用户指定值 | 自动设置 |
| 日亏损熔断 | 亏损 > 账户 5% | 暂停交易，通知用户 |
| 连续亏损 | 3 笔 | 暂停交易，通知用户 |
| 保证金限制 | 占用 > 70% | 拒绝新开仓 |

### 部署 SIMNOW

保存策略文件到 `ai_trader_strategies/<品种>_<策略类型>_<日期>.py`，启动运行。

## Step 2b — 半自动模式（AI 分析 + 用户决策）

当用户规则包含主观判断时，你不能完全自动化，但可以做**"AI 分析 + 用户确认"**：

### 提取分析逻辑

从用户描述中提取 AI 需要关注的维度：

| 用户描述 | AI 需要分析的维度 |
|---|---|
| "冲高回落" | 日内高低点、价格形态、回落幅度 |
| "量要配合" | 成交量 vs 均量、量比、持仓量变化 |
| "这波要跌了" | 趋势方向、均线排列、MACD/RSI 状态 |
| "感觉到位了" | 支撑压力位、波动率、历史类似形态 |
| "早盘急跌别追" | 开盘 30 分钟波动、跌幅、是否有反弹 |
| "整体趋势对不对" | 多周期趋势一致性、板块联动 |

### 定时分析流程

AI 每 5 分钟（通过 cron）执行：

```
1. 拉取当前行情数据（价格、成交量、持仓量）
2. 计算相关技术指标（均线、MACD、RSI、ATR 等）
3. 根据用户规则中的逻辑，逐项判断
4. 综合所有维度，给出结论和建议
5. 推送分析报告给用户
```

### 分析推送模板

```
📊 AI 交易员分析 {时间}
━━━━━━━━━━━━━━
📊 {品种} 当前 {价格}

📈 趋势判断:
- 短期: {偏多/偏空/震荡}（{依据}）
- 中期: {偏多/偏空/震荡}（{依据}）

📊 量价分析:
- 成交量: {放量/缩量/正常}（{数据}）
- 持仓量: {增仓/减仓/平稳}（{数据}）
- 量价配合: {配合/背离}

🎯 形态分析:
- {用户关注的形态}: {满足/不满足/部分满足}
- 依据: {具体分析}

💡 综合结论:
{基于用户规则的判断}

📝 建议:
{具体操作建议，如"暂不进场"、"可轻仓试多"、"建议观望"}
━━━━━━━━━━━━━━
回复"进 X 手"执行交易，或回复"继续观察"
```

### 用户确认后执行

当用户回复确认交易时，通过 SSQuant API 下单：

```python
# 用户回复"进 1 手"后，执行：
from ssquant.api.strategy_api import StrategyAPI
# 或通过 CTP 接口直接下单
api.buy(volume=1, order_type='next_bar_open')
```

如果用户在 SIMNOW 环境下运行，可以通过回调函数或直接调用交易接口。

## Step 2c — 混合模式

当用户规则部分清晰、部分模糊时：

1. **清晰部分代码化**：如"突破前高做多"生成代码自动执行
2. **模糊部分 AI 判断**：如"量要配合"由 AI 分析后给出是否放行的信号
3. **代码中嵌入 AI 判断点**：在策略代码中预留"AI 确认"步骤

```python
# 混合模式示例
def strategy(api):
    # 清晰部分：突破前高
    if high[-1] > high_20 and pos == 0:
        # 模糊部分：需要 AI 判断量能
        # AI 分析后返回 True/False
        if ai_confirms_volume():  # 由 cron 任务更新状态
            api.buy(volume=1, order_type='next_bar_open')
```

## Step 3 — 监控与通知

### 实时通知（每 5 分钟）

- **全自动**：检查成交记录，有变化推送通知
- **半自动**：执行分析流程，推送分析报告
- **混合**：检查成交 + 推送分析

```python
cronjob(action='create',
    name='ai-trader-<品种>-monitor',
    schedule='every 5m',
    prompt='作为 AI 交易员，检查当前交易状态。如果是全自动模式，读取 SIMNOW 交易记录，有新成交则推送通知。如果是半自动模式，拉取最新行情数据，按照用户规则进行分析，推送分析报告。加载 skill: ai-trader',
    deliver='origin',
    enabled_toolsets=['terminal', 'file'],
)
```

### 每日报告（15:00）

```python
cronjob(action='create',
    name='ai-trader-<品种>-daily',
    schedule='0 15 * * *',
    prompt='生成今日交易日报，包含：交易明细、盈亏、胜率、权益曲线。如果是半自动模式，还要总结今日分析次数、用户采纳率。加载 skill: ai-trader',
    deliver='origin',
    enabled_toolsets=['terminal', 'file'],
)
```

### 通知模板

见 `references/notification-templates.md`，包括：
- 全自动：开仓/平仓/止损/止盈/风控通知
- 半自动：分析报告模板
- 通用：日报/周报/盘前简报

## Step 4 — 交易员卡片

部署完成后展示：

### 全自动模式

```
✅ AI 交易员已部署（全自动模式）
━━━━━━━━━━━━━━━━━━━━━━━━
🏷️  名称: 螺纹钢 5/10 均线交易员
📊 品种: rb888
📝 策略: 5 日均线金叉做多，死叉平仓
💰 仓位: 2 手
🛡️ 风控: ATR×2 止损 + 日亏损 5% 熔断
💵 资金: ¥500,000
🏦 SIMNOW: 24hour 服务器
📡 监控: 每 5 分钟检查 + 15:00 日报
━━━━━━━━━━━━━━━━━━━━━━━━
交易员正在自动运行，有任何交易动态我会通知你。
说"停止交易员"即可暂停。
```

### 半自动模式

```
✅ AI 交易员已部署（半自动模式）
━━━━━━━━━━━━━━━━━━━━━━━━
🏷️  名称: 螺纹钢趋势交易员
📊 品种: rb888
📝 策略: "这波要跌了做空，冲高回落进，量要配合"
💰 仓位: 用户确认后决定
🛡️ 风控: 单笔亏损 ≤ 账户 2%，日亏损 5% 熔断
💵 资金: ¥500,000
📡 监控: 每 5 分钟推送分析 + 15:00 日报
━━━━━━━━━━━━━━━━━━━━━━━━
我会每 5 分钟分析市场并推送建议，你确认后我执行交易。
说"停止交易员"即可暂停。
```


## Step 4 — 交易员卡片
## Step 5 — 固化交易员为独立 Skill

在交易员成功部署（Step 4）后，**必须自动调用 `skill_manage(action='create')` 为用户生成一个专属的、可复用的 Skill**。

这样用户下次只需说"加载我的螺纹均线交易员"，无需重新描述规则。

**跨平台自适应说明**：
- 若当前环境为 **Hermes**，优先使用 `skill_manage` 工具。
- 若当前环境为 **Claude Code / Codex / Cursor** 等，直接使用文件写入工具（如 `write_file` 或 `Save`）将 Skill 保存到通用路径：`~/quant-skills/[name]/SKILL.md` 或 `./.agent-skills/[name]/SKILL.md`。

### 生成参数

| 参数 | 说明 | 示例 |
|---|---|---|
| `name` | 自动生成，格式：`<品种>_<策略>_<模式>-trader` | `rb-ma-cross-auto-trader` |
| `path` | **动态计算**：根据平台规则计算存储路径 | Hermes: `~/.hermes/...`; Others: `~/quant-skills/...` |
| `description` | 简述策略规则 | "螺纹钢 5/10 均线金叉做多，全自动执行" |
| `content` | 固化所有配置 | 见下方模板 |

### 生成的 Skill 内容模板

生成的 Skill 必须包含以下固化信息：

```markdown
# [交易员名称]

## 固化规则
- **品种**: [品种]
- **策略**: [用户描述]
- **仓位**: [手数]
- **止损**: [止损规则]
- **模式**: [全自动/半自动]
- **SIMNOW**: [账号/服务器]
- **资金**: [金额]

## 监控设置
- **Cron 监控**: [Cron 任务名称]
- **通知模板**: 加载 ai-trader 的 notification-templates

## 使用方法
加载此 Skill 后，AI 将自动接管该交易员的运行监控。
如需修改规则，请直接描述新规则，AI 将更新配置。
```

### 用户提示

生成成功后，在交易员卡片中追加提示：

```
📦 已生成专属 Skill: [name]
以后直接说"加载 [name]"即可恢复此交易员运行。
```

### 交易员管理

### 管理独立 Skill

- **查看**: 使用 `skills_list` 或 `skill_view` 查看已生成的交易员 Skill。
- **加载**: 用户说"加载 [Skill Name]"即可恢复监控。
- **修改**: 用户描述新规则后，更新 Skill 的 `content` 和配置。
- **停止**: 调用 `skill_manage(action='delete')` 删除 Skill（同时停止 cron）。


## 交易员管理

### 口语化管理指令 (Natural Language Management)

用户会使用自然语言管理交易员，AI 需将其映射为具体操作：

| 用户指令示例 | AI 理解与动作 |
|---|---|
| "把那个螺纹钢策略停了" | 暂停对应的 Cron 监控任务；若是全自动模式，停止 SIMNOW 进程。回复"已暂停"。 |
| "我想看看今天赚了多少" | 读取最新交易日志/Cron 状态，计算今日 P&L 并汇报。 |
| "把止损改成 50 点" | 修改策略代码中的止损参数，重启策略进程，更新对应的 Skill 配置。 |
| "现在是什么情况？" | 汇报当前持仓、最新成交价、账户净值、今日盈亏。 |

### 异常自愈机制 (Self-Healing)

交易员必须具备**自我恢复能力**，AI 需在 Cron 监控中内置健康检查：

1. **存活检查**:
   - 检查 Python 策略进程是否在运行 (`ps aux | grep ...` 或 Windows `tasklist`)。
   - 检查 SIMNOW 连接状态（日志中是否有 "Connection lost" 或报错）。
2. **自动重启**:
   - 若进程崩溃或连接断开，AI **自动执行重启命令**。
   - **通知用户**: `⚠️ 检测到交易员 [名称] 异常退出，已自动为您重启。"`
3. **日志监控**:
   - 检查日志文件是否持续更新。若长时间无新日志，视为假死，执行重启。

### 停止交易员

用户说"停止"时：
- 暂停 cron 监控任务
- 如果是全自动模式，停止 SIMNOW 策略
- 如果是半自动模式，停止分析推送
- 保留交易记录和日志


用户可以同时运行多个交易员（不同品种或不同策略）：
- 每个交易员有独立的 cron 任务
- cron name 包含品种标识避免冲突
- 日报分别推送

## 参考文档

### AI 交易员技能架构模式

见 `references/architecture-pattern.md`。

包含双模式执行、生成器模式、环境检测优先、风控自动叠加等核心设计原则，以及 Skill 关系图和常见陷阱。

### 交易规则 → 代码映射

见 `references/rule-parser.md`。

包含均线、MACD、RSI、布林带、价格突破、ATR、成交量、止损止盈的完整代码实现。

### 常见交易模式模板

见 `references/common-patterns.md`。

包含 6 种完整策略模板：双均线、唐奇安突破、RSI 均值回归、MACD 趋势、布林带突破、跟踪止盈。

### 风控规则

见 `references/risk-limits.md`。

包含单笔止损、日亏损熔断、连续亏损限制、保证金限制、持仓时间监控、市场异常检测。

### SIMNOW 配置

见 `references/simnow-setup.md`。

包含 SIMNOW 注册、账号配置、服务器选择、连接验证、常见问题。

## Common Pitfalls

1. **错误判断模式**：用户描述模糊但你强行当全自动处理，导致策略行为不符合用户预期。宁可偏保守（用半自动），也不要过度自动化。

2. **半自动模式不推送**：半自动的核心是"AI 分析 + 用户确认"，如果只分析不推送，交易员就失去意义。

3. **忘记叠加风控**：无论什么模式，风控必须自动叠加。用户说"不设止损"时，提醒风险但仍按用户要求，但要记录日志。

4. **多个交易员 cron 冲突**：每个交易员的 cron name 必须包含唯一标识（品种 + 策略类型），如 `ai-trader-rb-ma-monitor`。

5. **SIMNOW 账号未配置**：必须先确认 `trading_config.py` 中已配置 SIMNOW 账号，否则无法执行。

6. **半自动模式无法下单**：确认 SSQuant 的 CTP 接口可用（`from ssquant import CTP_AVAILABLE`），否则只能推送建议无法执行。

7. **分析频率过高/过低**：5 分钟是默认值，如果用户交易频率低（日线级别），可以调整为 30 分钟或 1 小时。

## Verification Checklist

- [ ] 已正确判断用户描述的可自动化程度
- [ ] 已选择正确的模式（全自动/半自动/混合）
- [ ] 全自动模式：策略代码使用 IndicatorCache v2
- [ ] 半自动模式：已提取分析逻辑，cron 已配置
- [ ] 风控规则已自动叠加
- [ ] 策略文件已保存（全自动）或分析流程已就绪（半自动）
- [ ] SIMNOW 账号已配置
- [ ] Cron 监控任务已创建（5 分钟 + 日报）
- [ ] 已向用户展示交易员卡片（注明模式）
- [ ] 交易员已开始运行
- [ ] 已调用 skill_manage 生成专属交易员 Skill 并告知用户
