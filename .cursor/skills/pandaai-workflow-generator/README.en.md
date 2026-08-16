# PandaAI Workflow Generator (skill-pandaai-workflow-generator)

This is an Agent Skill incubated for the [QuantSkills Open Source Community](https://github.com/quantskills).

When conducting quantitative research or participating in internal ranking competitions, we need to verify factor or strategy ideas quickly on the PandaAI platform. However, manually dragging nodes, connecting lines, pasting code, and modifying parameters in the PandaAI web editor (based on LiteGraph) is highly inefficient and error-prone, occasionally causing import failures or data leakage.

This Skill provides four verified PandaAI workflow templates along with a **dependency-free (Python standard library only)** assembly script. By utilizing LLM-generated Python strategy code and this tool, users can establish an automated **"Idea -> Auto-assembled Workflow -> One-click Import & Backtest"** pipeline.

---

## Directory Structure

```
skill-pandaai-workflow-generator/
├── LICENSE
├── README.md               # Chinese documentation
├── README.en.md            # English documentation (This file)
├── SKILL.md                # Specifications and Agent instructions
├── scripts/
│   ├── generate_workflow.py # Assembly script based on Python standard library
│   ├── from_qbti_brief.py   # Bridges skill-qbti's strategy_brief.json into a PandaAI workflow
│   └── smoke_test.py        # End-to-end smoke test
└── references/
    ├── disclaimer_template.md # Disclaimer template
    ├── sandbox_restrictions.md # Platform code sandbox security restrictions (banned import/call list, verified)
    ├── sandbox_diagnostics.md # Probe-before-building methodology + reusable diagnostic snippet
    ├── qbti_bridge.md         # QBTI bridge: what to do when the user doesn't know what they want
    └── templates/           # Built-in workflow JSON templates
        ├── simple_backtest.json         # Simple backtest template (standard initialize/handle_data structure)
        ├── complex_stock_selection.json  # Complex stock selection & financial factor query template
        ├── multi_factor_analysis.json    # Multi-factor score and 5-group analysis pipeline template
        └── multi_agent_trading.json     # Futures multi-agent collaborative trading template (orchestration)
```

---

## Usage Instructions

### 1. Run the Assembly Script
You can execute `scripts/generate_workflow.py` with standard `python` or `uv run`. The script loads a base template, inserts the strategy or factor code into the `CodeControl` node, and synchronizes custom parameters (e.g., dates, capital) between backend `static_input_data` and frontend LiteGraph `properties`.

```bash
# Example: Using simple_backtest template, injecting strategy code, and overriding backtest dates
python scripts/generate_workflow.py \
  --template simple_backtest \
  --code-file my_strategy.py \
  --param-json '{"StockBacktestControl": {"start_date": "20250101", "end_date": "20251231"}}' \
  --out my_workflow.json
```

### 2. Arguments
* `--template`: Template name. Supported values:
  * `simple_backtest` (Simple backtest)
  * `complex_stock_selection` (Complex stock selection)
  * `multi_factor_analysis` (Multi-factor analysis)
  * `multi_agent_trading` (Multi-agent trading)
* `--code-file`: The Python file containing the factor or strategy code to embed into the `CodeControl` node. Repeatable.
  * When the template has a single `CodeControl` node, pass the path directly. When it has several (e.g. `multi_agent_trading` has three), an untargeted `--code-file` is rejected — use the targeted form for each node:
    ```bash
    --code-file "CodeControl#11=risk_agent.py" --code-file "CodeControl#19=data_agent.py"
    ```
* `--param-json`: A JSON string or file path containing node parameters to override, formatted as `{ "<node target>": { "parameter_key": "parameter_value" } }`.
  * Node targets support `Type` (all nodes of the type), `Type#<litegraph_id>` (one specific node), and `#<litegraph_id>` (by id only).
  * E.g., `{"StockBacktestControl": {"standard_symbol": "上证指数"}}`
  * E.g., setting the three weight nodes and one formula in the multi-factor template individually: `{"FactorWeightAdjustControl#9": {"weight": 5}, "FactorWeightAdjustControl#14": {"weight": 3}, "FactorWeightAdjustControl#15": {"weight": 1}, "FormulaControl#1": {"formulas": "RANK((CLOSE / DELAY(CLOSE, 20)) - 1)"}}`
  * A target matching zero nodes makes the script exit with an error (preventing silently generating a file with default parameters after a typo).
* `--out`: Output path for the generated, importable JSON file.

### 3. One-click Import & Backtest
After generating `my_workflow.json`, log in to the PandaAI platform, click **"Import Workflow"**, and upload the JSON. The editor canvas will render with perfect links, codes, and parameters. Click **"Run"** to start the backtest immediately!

### 4. Don't know what strategy you want? Run QBTI first
If you have no quant background and no concrete strategy idea, this skill alone can't help — it assumes an idea already exists. Use [skill-qbti](https://github.com/quantskills/skill-qbti)'s five-part quiz to translate your risk tolerance, involvement level, and factor taste into a `strategy_brief.json`, then bridge it into an importable workflow with one command:

```bash
python scripts/from_qbti_brief.py --brief strategy_brief.json --out my_workflow.json
```

See [qbti_bridge.md](references/qbti_bridge.md) for the factor-family-to-scoring-formula mapping table and why every QBTI-sourced strategy lands on the `complex_stock_selection` template.

---

## Disclaimer

This skill is an independent community contribution and is unofficial. It is not affiliated with PandaAI or the PandaData organization. Generated workflows, strategies, and factor code are for research and education only and do not constitute investment advice. For details, please refer to [disclaimer_template.md](references/disclaimer_template.md). Investing carries risk.
