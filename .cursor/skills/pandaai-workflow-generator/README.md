# PandaAI 工作流自动生成器 (skill-pandaai-workflow-generator)

这是一个专为 [QuantSkills 开源社区](https://github.com/quantskills) 孵化的 Agent Skill。

在进行量化研究或打内部排位赛时，我们需要快速在 PandaAI 平台上对各种因子或策略创意进行回测验证。然而，手动在 PandaAI 网页端（基于 LiteGraph 画布）中拖拽节点、连接线条、贴入代码并修改各种参数十分低效，且容易因参数冲突引发不可预知的数据泄露或导入报错。

本 Skill 内置了四种经验证、能够完美跑通的 PandaAI 拓扑模板，并提供了一个**零第三方依赖（纯 Python 标准库）**的自动装配脚本。通过大模型生成 Python 策略代码，并结合本脚本，用户可以实现**“量化思路 -> 自动装配工作流 -> 官网一键导入回测”**的端到端自动化。

---

## 目录结构

```
skill-pandaai-workflow-generator/
├── LICENSE
├── README.md               # 本文件 (中文说明)
├── README.en.md            # 英文说明
├── SKILL.md                # 规范元数据及 Agent 指导词
├── scripts/
│   ├── generate_workflow.py # 纯 Python 3.10+ 标准库的图装配脚本
│   ├── from_qbti_brief.py   # 把 skill-qbti 的 strategy_brief.json 桥接为 PandaAI 工作流
│   └── smoke_test.py        # 端到端冒烟测试 (python scripts/smoke_test.py)
└── references/
    ├── disclaimer_template.md # 免责声明
    ├── sandbox_restrictions.md # 平台代码沙箱安全限制（禁止的 import/调用清单，实测确认）
    ├── sandbox_diagnostics.md # 回测沙箱数据诊断方法论：先探测再写策略，含可复用探针代码骨架
    ├── qbti_bridge.md         # QBTI 桥接说明：不知道自己要什么的用户如何用本 skill
    └── templates/           # 内置基础工作流 JSON 模板
        ├── simple_backtest.json         # 基础策略回测模板 (经典 initialize/handle_data 结构)
        ├── complex_stock_selection.json  # 复杂选股与财务因子拉取回测模板 (德雷曼风格)
        ├── multi_factor_analysis.json    # 多因子合成与 5 分组分析模板 (包含因子加权与合并)
        └── multi_agent_trading.json     # 期货多智能体协同决策交易模板 (包含编排器与交易执行器)
```

---

## 使用说明

### 1. 运行装配脚本
你可以使用 `python` 或 `uv run` 直接运行 `scripts/generate_workflow.py`。该脚本负责加载基础模板，自动将用户的策略/因子代码写入 `CodeControl` 节点，并将定制的回测参数（如起止日期、初始资金等）同步更新到后端的 `static_input_data` 和前端 LiteGraph 的 `properties` 中。

```bash
# 示例：基于极简策略回测模板，将 strategy.py 中的代码填入，并覆盖回测起止日期
python scripts/generate_workflow.py \
  --template simple_backtest \
  --code-file my_strategy.py \
  --param-json '{"StockBacktestControl": {"start_date": "20250101", "end_date": "20251231"}}' \
  --out my_workflow.json
```

### 2. 参数说明
* `--template`：模板名称，可选值为：
  * `simple_backtest` (基础回测)
  * `complex_stock_selection` (复杂选股)
  * `multi_factor_analysis` (多因子分析)
  * `multi_agent_trading` (多智能体交易)
* `--code-file`：需要嵌入 `CodeControl` 节点的 Python 因子或策略代码文件，可重复传入。
  * 模板中只有一个 `CodeControl` 时直接传路径即可；有多个时（如 `multi_agent_trading` 有三个）必须写成定位形式分别注入，否则脚本会报错并列出可选节点：
    ```bash
    --code-file "CodeControl#11=risk_agent.py" --code-file "CodeControl#19=data_agent.py"
    ```
* `--param-json`：需要覆盖/注入的节点属性，为 JSON 字符串或 JSON 文件的路径。格式为 `{ "<节点定位符>": { "parameter_key": "parameter_value" } }`。
  * 节点定位符支持三种写法：`Type`（该类型全部节点）、`Type#<litegraph_id>`（指定某个节点）、`#<litegraph_id>`（仅按 id 定位）。
  * 例如，修改股票回测的基准指数：`{"StockBacktestControl": {"standard_symbol": "上证指数"}}`
  * 例如，分别设置多因子模板中三个权重节点与一条公式：`{"FactorWeightAdjustControl#9": {"weight": 5}, "FactorWeightAdjustControl#14": {"weight": 3}, "FactorWeightAdjustControl#15": {"weight": 1}, "FormulaControl#1": {"formulas": "RANK((CLOSE / DELAY(CLOSE, 20)) - 1)"}}`
  * 定位符匹配不到任何节点时脚本会直接报错退出（防止拼错节点名后静默生成默认参数的文件）。
* `--out`：生成的、可用于导入的 JSON 文件输出路径。

### 3. 一键导入回测
生成 `my_workflow.json` 后，登录 PandaAI 工作流官网，点击 **"导入工作流"**，上传该 JSON 文件。你将看到连线完美、代码与参数已正确填充的画布，直接点击 **"运行"** 即可开始回测！

### 4. 不知道自己要什么策略？先跑 QBTI
如果你不是量化背景、也没有具体的策略想法，本 skill 单独用不上——它假设策略创意已经存在。先用 [skill-qbti](https://github.com/quantskills/skill-qbti) 的五组趣味问答，把你的风险偏好、参与度、因子口味等翻译成 `strategy_brief.json`，再一条命令桥接成可导入的工作流：

```bash
python scripts/from_qbti_brief.py --brief strategy_brief.json --out my_workflow.json
```

详见 [qbti_bridge.md](references/qbti_bridge.md)（含因子家族到打分公式的映射表，以及为什么统一落到 `complex_stock_selection` 模板）。

---

## 免责声明

本技能由社区开发者独立贡献，属于非官方项目，不隶属于 PandaAI 或 PandaData 组织。生成的工作流、策略与因子代码仅供研究与教育参考，**不构成任何投资建议**。详细免责声明请参阅 [disclaimer_template.md](references/disclaimer_template.md)。投资有风险，入市需谨慎。