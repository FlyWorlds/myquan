---
name: ssquant-trader-generator
description: Use when a user wants to turn a natural language trading idea into a
  persistent, deployable AI Trader Skill. Parses rules, judges automatability, generates
  code/analysis plans, deploys to SIMNOW via 'ssquant-ai-trader', and finally calls
  skill_manage to create a permanent, reusable Skill for the specific trader.
version: 1.0.0
author: SSQuant Team
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-ssquant-trader-generator
  repository_url: https://github.com/quantskills/skill-ssquant-trader-generator
  project_type: skill
  collection: ssquant-trader-generator
  creator: abgyjaguo
  maintainer: abgyjaguo
  hermes:
    tags:
    - quant
    - trading
    - skill-generator
    - ai-trader
    - automation
    - persistent-skills
    related_skills:
    - ssquant-ai-trader
    - writing-plans
quantSkills:
  project_type: skill
  category: tooling
  tags:
  - ssquant
  - trader-generator
  - ai-trader
  - natural-language
  - deployment
  platforms:
  - claude-code
  - codex
  - hermes
  - openclaw
  - cursor
  status: stable
  validation_level: runnable
  maintainer_type: official
  summary_zh: 说一次想法，得到一个可以随时加载的 AI 交易员。
  summary_en: Trader-generator skill that turns natural-language trading ideas into
    deployable AI Trader rules, code, and operating plans.
  license: GPL-3.0
  requires:
  - skill-ssquant-ai-trader
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "请描述交易逻辑、开平仓条件、交易周期、风控和希望固化的操作方式",
    "required": true
  },
  "fields": [
    {
      "key": "variety",
      "label": "交易品种",
      "type": "text",
      "placeholder": "如：rb、i、sc"
    },
    {
      "key": "execution_mode",
      "label": "执行模式",
      "type": "select",
      "default": "semi_auto",
      "options": [
        { "value": "semi_auto", "label": "半自动" },
        { "value": "auto", "label": "全自动" }
      ]
    },
    {
      "key": "capital",
      "label": "计划资金",
      "type": "number",
      "placeholder": "填写计划投入金额"
    },
    {
      "key": "risk",
      "label": "风控要求",
      "type": "textarea",
      "placeholder": "止损、止盈、仓位、最大回撤或日内限制"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请将交易品种 {{variety}} 的自然语言交易想法解析为可执行规则，采用 {{execution_mode}} 模式{{#capital}}、计划资金 {{capital}}{{/capital}}{{#risk}}，并落实风控要求：{{risk}}{{/risk}}；判断可自动化程度，委托 ssquant-ai-trader 做环境检查、回测与 SIMNOW 部署，并固化为可复用的专属 Trader Skill，输出中文报告。"
}
```

# 交易员生成器（Trader Generator）

## Overview

这个 Skill 是 **AI Trader 的"制造工厂"**。

它的核心职责不仅仅是运行一次交易员，而是**将用户的自然语言描述转化为一个永久存在的、可复用的专属 Skill**。

### ⚠️ 运行环境要求

**本 Skill 强依赖 SSQuant 框架的特定版本，必须满足以下条件才能运行：**

- **SSQuant 版本**: `>= 0.4.6` (强制要求)
- **Python 版本**: `3.9+`

加载此 Skill 后，AI 具备以下能力：
1.  **深度解析**：理解用户模糊或精确的交易逻辑。
2.  **模式判定**：自动判断全自动/半自动模式。
3.  **即时部署**：调用底层 `ai-trader` 逻辑进行 SIMNOW 部署。
4.  **技能固化**：调用 `skill_manage` 创建该交易员的独立文件，使其成为系统的一部分。

## When to Use

- 用户说："帮我把这个交易想法做成一个自动交易员"。
- 用户描述了一个复杂的策略，并要求"以后我能随时加载它"。
- 用户希望系统里有一个专属 Skill，对应他特定的交易逻辑（如"螺纹钢 5/10 均线交易员"）。

## Workflow

### Step 1 — 意图解析与规则提取

接收用户输入，提取以下核心要素：
- **环境检查**: 首先运行 Step 0 检查 SSQuant 是否安装（见下方 Step 0 定义）。
- **品种** (Symbol): 如 rb, i, sc...
- **核心逻辑** (Logic): 开平仓条件（代码化或主观描述）。
- **风控要求** (Risk): 止损、止盈、资金管理（若未提供则使用默认值）。
- **执行模式** (Mode): 全自动 (Auto) 或 半自动 (Semi-auto)。

### Step 2 — 底层部署 (Delegate to ssquant-ai-trader)

利用 `ssquant-ai-trader` 的能力进行环境搭建。该引擎已内置以下高级特性，生成器无需重复实现：
- **环境自适应**: 自动检测 Python/SSQuant 版本，跨平台自动安装依赖。
- **零配置体验 (Zero-Config)**: 自动引导用户输入并写入 `trading_config.py` (俱乐部账号/SIMNOW 账号)。
- **上线前验证**: 自动运行短期回测 (Safety First) 验证策略逻辑。
- **异常自愈**: 内置进程监控与自动重启机制。

**生成器职责**: 仅负责解析用户意图、生成专属 Skill 文件 (Step 3) 和引导用户授权。具体的部署、监控、代码生成工作全部委托给 `ssquant-ai-trader` 执行。

### Step 3 — 交易员 Skill 生成 (Core Feature)

**这是本 Skill 的核心步骤。**

调用 `skill_manage(action='create')` 生成一个持久化的交易员 Skill。

#### 参数规范

| 字段 | 生成规则 | 示例 |
|---|---|---|
| `name` | `<品种>-<策略关键词>-trader` | `rb-ma-cross-trader`, `i-bottom-fisher-trader` |
| `description` | 简述策略核心规则，便于用户检索 | "螺纹钢 5/10 均线交叉全自动交易员" |
| `category` | `quant-trading` | 归类到量化交易目录 |
| `content` | 固化后的完整配置（见下方模板） | ... |

#### Content 模板结构

生成的 Skill 内容必须包含：

```markdown
---
name: [自动生成]
description: [自动生成]
...
---

# [交易员名称] (已部署实例)

## 固化配置
- **模式**: [全自动/半自动]
- **品种**: [品种代码]
- **规则**: [用户原始描述摘要]
- **资金**: [金额]
- **SIMNOW 账号**: [账号 ID]

## 关联任务
- **监控 Cron**: [Cron 任务名称]
- **策略文件**: [代码路径或分析逻辑路径]

## 操作指令
- **启动**: "启动 [交易员名称]"
- **停止**: "停止 [交易员名称]"
- **查看**: "查看 [交易员名称] 状态"

> 注意：修改此交易员的规则需重新调用 `trader-generator` 进行热更新。
```

### Step 4 — 交付与引导

生成成功后，向用户展示：

```
✅ 交易员生成完毕！

📦 专属 Skill 已创建: [name]
📄 路径: [平台自适应路径]/quant-trading/[name]/SKILL.md
🔗 关联: 已部署 SIMNOW 环境 + 监控任务

以后你只需要说："加载 [name]"，我就会立刻恢复该交易员的工作状态。
```

### 平台自适应存储指南

**AI 必须根据当前运行平台决定 Skill 的存储路径：**

| 平台 | 推荐存储路径 | 保存方式 |
|---|---|---|
| **Hermes** | `~/.hermes/skills/quant-trading/[name]/SKILL.md` | 使用 `skill_manage` 或 `write_file` |
| **Claude Code / Codex** | `./.claude/skills/quant-trading/[name]/SKILL.md` | 使用文件系统写入 (`write_file`) |
| **Cursor / General** | `~/my-ai-skills/quant-trading/[name]/SKILL.md` | 使用文件系统写入 (`write_file`) |

*注意：若不确定路径，优先询问用户或保存至当前工作目录下的 `quant-skills/` 文件夹中。*

## Common Pitfalls

### AI 交易员技能架构模式

见 `ai-trader` 的 `references/architecture-pattern.md`。

包含双模式执行、生成器模式、环境检测优先等核心设计原则。

### 执行引擎委托

所有底层部署（代码生成、SIMNOW 连接、Cron 监控）均委托给 `ai-trader` skill 执行。本 Skill 专注于"解析 → 部署 → 固化"的工厂流程。

## Common Pitfalls

1. **忘记调用 skill_manage**：如果只运行不生成文件，下次用户就无法直接加载了。**必须**在部署成功后生成独立 Skill。
2. **Skill Name 冲突**：如果 `name` 已存在，询问用户是否覆盖或追加版本号（如 `v2`）。
3. **账号未配置阻断**：如果 SIMNOW 账号未配置，无法生成可执行的 Skill，应引导用户先配置，或生成一个"待配置"状态的 Skill。
4. **半自动逻辑丢失**：生成 Skill 时，必须把"AI 分析逻辑"（如量价判断标准）详细写入 content，否则加载后 AI 不知道该怎么分析。

## Step 0 — 环境检测与安装 (与 ai-trader 共享)

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

### AI Agent 自动安装流程

**AI 应直接使用 `terminal` 工具自动完成安装，无需用户手动操作。**

**跨平台通用性要求**：
- 自动识别 Python 命令：在 Linux/Mac 优先尝试 `python3`，Windows 使用 `python`。
- 路径分隔符：内部使用 `/`，AI 输出时自动适配系统。
- 安装位置：默认克隆到用户目录 (`~/ssquant`)，若已存在则跳过或更新。

1. **获取授权**：向用户说明：“未检测到 SSQuant 框架。我将自动克隆并安装，是否继续？”
2. **执行命令**（优先 Gitee，备用 GitHub，pip 使用清华源）：
   ```bash
   git clone https://gitee.com/songshuquant/ssquant.git ~/ssquant || git clone https://github.com/songshuquant/ssquant.git ~/ssquant
   cd ~/ssquant
   # 自动识别 python3/python 并执行安装
   (command -v python3 >/dev/null && echo python3 || echo python) -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
3. **验证安装**：
   ```bash
   python3 -c "import ssquant; print('SSQuant v' + ssquant.__version__ + ' 安装成功')" 2>/dev/null || python -c "import ssquant; print('SSQuant v' + ssquant.__version__ + ' 安装成功')"
   ```
4. **异常处理与流转**：
   - 安装成功后**自动进入 Step 1**，无需用户手动回复。
   - 若网络超时，自动重试或提示用户检查网络。

### 核心配置自动写入 (Zero-Config Experience)

为了提供最佳体验，**AI 必须直接帮用户修改配置文件，而不是让用户手动编辑。**

1. **收集信息**:
   询问用户：“请提供以下账号信息（我将自动帮您填入配置文件）：
   - **松鼠俱乐部账号** (API_USERNAME): [必填]
   - **松鼠俱乐部密码** (API_PASSWORD): [必填]
   - **SIMNOW 账号** (InvestorID): [必填]
   - **SIMNOW 密码** (Password): [必填]
   ”

2. **自动执行修改**:
   用户回复后，AI 使用 `patch` 工具修改 `~/ssquant/ssquant/config/trading_config.py`：
   
   - **更新 API 鉴权**: 替换 `API_USERNAME = ""` 等空值为实际值。
   - **更新 SIMNOW 账号**: 在 `ACCOUNTS` 字典中找到 `'simnow_default'`，更新 `investor_id` 和 `password`。

   > **注意**: 若配置文件中已有占位符（如 `Your_User_ID`），请直接替换该占位符。

3. **验证**:
   修改完成后，AI 简单读取文件确认值已写入正确。
