---
name: pandaai-workflow-generator
description: Generate complete PandaAI workflow JSON files (including LiteGraph nodes, links, and embedded Python strategy/factor code) based on user's natural language descriptions of quantitative ideas. Inject trading costs, universe settings, and timing constraints into templates to prepare them for one-click import into PandaAI. Use when a user describes a trading strategy or factor idea and wants an importable PandaAI workflow file, asks 帮我生成 PandaAI 工作流 / 把这个策略变成可导入的回测 / turn a QBTI strategy_brief.json into a PandaAI workflow, or needs PandaAI CodeControl strategy code assembled with correct node wiring and parameters.
license: GPL-3.0-only
compatibility: Requires Python 3.10+ for scripts/generate_workflow.py. Pure stdlib.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-pandaai-workflow-generator
  repository_url: https://github.com/quantskills/skill-pandaai-workflow-generator
  project_type: skill
  collection: portfolio-risk-validation
  license: GPL-3.0
  category: trader-research
  tags:
  - pandaai
  - workflow-generator
  - code-generation
  - backtesting
  platforms:
  - claude-code
  - cursor
  - openclaw
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires:
  - skill-pandadata-api
  summary_zh: 根据用户的自然语言量化想法，自动生成包含 Python 因子/策略代码及完整连线图的 PandaAI 工作流 JSON 文件，支持一键导入官网进行回测。
  summary_en: Generate ready-to-import PandaAI workflow JSON files containing Python strategy/factor code and complete graph links based on user's natural language trading ideas.
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "描述已有的量化策略或因子设计，包含信号、调仓、成本和时间约束；也可上传 strategy_brief.json",
    "required": true
  },
  "fields": [
    {
      "key": "template",
      "label": "工作流模板",
      "type": "select",
      "default": "auto",
      "options": [
        { "value": "auto", "label": "自动匹配" },
        { "value": "simple_backtest", "label": "基础股票回测" },
        { "value": "complex_stock_selection", "label": "复杂选股" },
        { "value": "multi_factor_analysis", "label": "多因子分析" },
        { "value": "multi_agent_trading", "label": "多智能体交易" }
      ]
    },
    {
      "key": "universe",
      "label": "股票池",
      "type": "select",
      "default": "auto",
      "options": [
        { "value": "auto", "label": "按任务/模板自动决定" },
        { "value": "000300.SH", "label": "沪深300" },
        { "value": "000905.SH", "label": "中证500" },
        { "value": "399006.SZ", "label": "创业板指" },
        { "value": "000852.SH", "label": "中证1000" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}将已有量化设计组装为可导入 PandaAI 的完整工作流 JSON，模板选择 {{template}}，股票池为 {{universe}}。严格核验节点、连线、参数覆盖、SDK 方法与沙箱限制；遇到未确认的数据域先生成只读诊断工作流，ETF/基金策略须明确提示当前沙箱无覆盖并给出可行替代，不在本地执行生成的策略代码。验证 JSON 完整性并附导入与审计说明，输出中文报告。"
}
```

# PandaAI 工作流文件生成器 (PandaAI Workflow Generator)

This skill automates the configuration, code injection, and parameters-matching for PandaAI LiteGraph workflow exports. It translates user trading ideas into customized, importable JSON workflow files.

## Core workflow

0. **User has no concrete idea — route to QBTI first, don't try to elicit one yourself**
   This skill is an assembler, not an ideation tool: step 1 below assumes a trading strategy or factor design already exists. If the user says something like "我不懂量化但想试试" / "帮我做一个适合我的策略" / "我根本不知道自己要什么" — with no concrete strategy in mind — do not attempt to draft one from a generic guess, and do not try to informally interview the user yourself (that duplicates a purpose-built skill and skips its safeguards, e.g. never steering a self-described conservative user toward aggressive parameters). Instead:
   1. Hand off to `skill-qbti` (QBTI), which exists exactly for this: a five-part quiz that deterministically translates investing preferences into a `strategy_brief.json`.
   2. Once the user has a `strategy_brief.json` (from QBTI or otherwise, as long as it matches the schema in `references/qbti_bridge.md`), run `python scripts/from_qbti_brief.py --brief <strategy_brief.json> --out <output.json>` to translate it straight into an importable `complex_stock_selection` workflow — this single command replaces steps 1–4 below for QBTI-sourced strategies. See `references/qbti_bridge.md` for exactly what it does and why every QBTI-sourced strategy lands on `complex_stock_selection` (QBTI's variable-length factor list doesn't fit `multi_factor_analysis`'s fixed node topology).
   3. Skip straight to step 5 (Verify Output Integrity) and step 6 (Present Findings & Disclaimer) — do not re-derive template/code/parameters by hand once the bridge script has run.
   If the user already has a concrete strategy idea, skip this step and start at step 1 as usual — QBTI is only for the "I don't know what I want" entry point, not a mandatory gate.

1. **Identify User Goal & Select Template**
   Analyze the user's trading strategy or factor design, then mapping it to one of the four built-in templates:
   - `simple_backtest`: A basic stock backtest with typical `initialize` and `handle_data` event loop.
   - `complex_stock_selection`: A detailed stock selection workflow (e.g. Dreman style) querying custom factors from `panda_data` and applying cross-sectional filters.
   - `multi_factor_analysis`: Multi-factor scorecard weighting, combining, and running a 5-group analysis.
   - `multi_agent_trading`: Multi-agent orchestration, involving custom prompt managers, technical/volatility analysts, and an execution client.

   **Known unsupported instrument class — warn before writing any code.** Verified 2026-07-08 via two dedicated read-only diagnostic probes (see `references/sandbox_diagnostics.md`): the `StockBacktestControl` (股票回测) backtest sandbox's data warehouse has **zero ETF/fund coverage, confirmed exhaustively, not just for one code**. Evidence: (1) 6 independent query paths against ETF 510300.SH all returned 0 rows while a control stock (300750.SZ) succeeded on every one of them in the same run; (2) a full-universe scan of all 5203 listed symbols (roughly the whole A-share market) found zero matches against 20 common ETF code-prefix segments AND zero matches against name keywords ("ETF"/"指数"/"300") — the keyword scan rules out "wrong code guess," since it doesn't depend on code format at all. This is closed, not tentative. If the user asks for an ETF/fund-based strategy (rotation, allocation, tracking, etc.), **say this upfront** before generating anything: this account's backtest data has no ETF/fund products from any issuer, and go straight to offering the fix — substitute representative individual stocks for each ETF in the design (same signal logic, proven data path via `get_stock_daily`/`data[symbol]`). Do not silently generate an ETF strategy and let the user discover this after a failed backtest, and do not re-run the diagnostic probes again for this account — the question is answered.

2. **Draft Python Code or Formulas**
   - Write clean, robust, error-free Python code that complies with the PandaAI SDK specifications.
   - Before calling any `panda_data.get_*` method, look up its exact signature in the [quantskills/skill-pandadata-api](https://github.com/quantskills/skill-pandadata-api) reference skill (218 documented methods with examples) — do not invent parameters or guess method names. **But that skill documents the public research SDK, not necessarily the backtest sandbox's embedded `panda_data`, which has been confirmed to have a different, smaller method surface** (see step 2a).
   - Save the code locally to a temporary file in the workspace (e.g., `temp_code.py`).
   - If using `multi_factor_analysis`, formulate clean expressions such as `RANK((CLOSE / DELAY(CLOSE, 20)) - 1)`. Formulas are injected via parameter overrides on the `FormulaControl` nodes (field `formulas`), not via `--code-file`.

2a. **Probe before building, when the data domain is unconfirmed**
   - The four bundled templates only demonstrate: `data[symbol]` bar prices, `panda_data.get_factor(type='stock'/'future')`, `panda_data.get_market_data(type='future')`, and `panda_data.get_stock_detail`. If the user's idea needs a symbol type or data domain not covered by these (e.g. ETFs, options, a `get_*` method never seen in a template), **do not guess the right API inside a full trading strategy.** Instead:
     1. Read `references/sandbox_diagnostics.md` for the reusable read-only probe pattern and the running ledger of confirmed/unconfirmed sandbox facts.
     2. Generate a minimal diagnostic-only workflow from that pattern: no `order_*` calls, every `panda_data` call wrapped in `try/except` that prints instead of raising, method existence checked via `hasattr()` (never `dir()` — see `references/sandbox_restrictions.md`), a known-working control symbol probed side-by-side with the target symbol, and a short backtest window (1–2 months) to keep the run fast and the log short.
     3. Have the user run that probe first and report back the log. Only then write the real strategy, using exclusively the calls the probe just confirmed work in this sandbox.
   - This turns "guess an API, ship a full strategy, wait for a failure screenshot, repeat" into one cheap diagnostic round trip before the real strategy is written. Update `references/sandbox_diagnostics.md`'s fact table with whatever the probe confirms, so the next strategy in the same data domain skips the probe entirely.

3. **Resolve Custom Parameters**
   - Determine which nodes require parameter overrides.
   - Node targets support three forms: `Type` (all nodes of that type), `Type#<litegraph_id>` (one specific node), and `#<litegraph_id>` (by id regardless of type). When a template contains several nodes of the same type (e.g. the three `FactorWeightAdjustControl` nodes in `multi_factor_analysis`), you MUST use the `#<litegraph_id>` form to set them individually — read the template JSON to find each node's `litegraph_id`.
   - Map parameters into a nested JSON structure. Supported overrides are typically:
     - `StockBacktestControl`: `start_date`, `end_date`, `start_capital`, `standard_symbol`, `commission_rate`, `slippage`.
     - `FactorAnalysisControl`: `adjustment_cycle`, `group_number`, `stock_pool`, `factor_direction`.
     - `FactorBuildProControl`: `start_date`, `end_date`, `market`, `direction`, `type`.
     - `FactorWeightAdjustControl`: `weight` (per node, e.g. `"FactorWeightAdjustControl#9": {"weight": 5}`).
     - `FormulaControl`: `formulas` (per node, e.g. `"FormulaControl#1": {"formulas": "RANK(...)"}`).
   - If an override target matches zero nodes the script exits with an error listing the template's nodes — fix the target instead of retrying blindly.

4. **Run Assembly Command**
   Call the assembly script to inject your code and parameters:
   ```powershell
   python scripts/generate_workflow.py --template <template_name> --code-file <temp_code.py> --param-json '<parameter_overrides_json>' --out <output_path.json>
   ```
   - `--code-file` may be repeated. When the template has multiple `CodeControl` nodes (e.g. `multi_agent_trading` has three), an untargeted `--code-file` is rejected; use the targeted form for each node instead:
   ```powershell
   python scripts/generate_workflow.py --template multi_agent_trading --code-file "CodeControl#11=risk_agent.py" --code-file "CodeControl#19=data_agent.py" --out <output_path.json>
   ```

5. **Verify Output Integrity**
   - Confirm that the output file exists, is valid JSON, and has a newly generated workflow ID to avoid MongoDB collisions on import.
   - After modifying templates or the assembly script itself, run `python scripts/smoke_test.py` to re-verify all four templates end-to-end.
   - Before instructing the user to import into PandaAI, recommend running the `--out` file through `skill-pandaai-workflow-audit` (`python scripts/audit_workflow.py <output_path.json> --json-out audit.json --markdown-out audit.md`). This assembler emits code and parameters as written, not a correctness or overfitting review — the audit skill's format parser is built against the exact same node/link schema this script emits, so no conversion is needed.

6. **Present Findings & Disclaimer**
   - Instruct the user on how to import the generated file into the PandaAI console.
   - Show the standard disclaimer text from `references/disclaimer_template.md` verbatim before ending the turn.

## SDK Code Specifications

**Before writing any CodeControl code, read `references/sandbox_restrictions.md`.** PandaAI statically rejects code containing blacklisted imports or calls (verified 2026-07-08, exact text of the platform's rejection dialog is copied there) — the import is never executed, the workflow fails validation at import time. Highlights:
- No `dir()`, `eval()`, `exec()`, `compile()`, `open()`, `__import__()`. For introspecting whether a `panda_data` method exists, use `hasattr(panda_data, "method_name")` against a candidate name list instead of `dir(panda_data)`.
- No `import os / sys / subprocess / pickle / socket / threading / requests / sqlite3` (full list in the reference file). Strategy code can only do computation and call platform-injected APIs (`panda_data.*`, `order_shares`, etc.) — no filesystem, network, or process access.
- `pandas`, `numpy`, `datetime`, `re`, `json`, `math`, `bisect` are confirmed safe and used across the four bundled templates.

When writing code for the `simple_backtest` or `complex_stock_selection` templates:
- Keep A-share lot rules in mind: buy orders should round to 100 shares.
- Utilize platform APIs such as `order_shares(account_id, symbol, shares, style=MarketOrderStyle)` or `order_values(account_id, symbol, value, remark)`.
- Use try-except blocks when fetching quotes from data providers (e.g., `panda_data.get_factor` or `panda_data.get_market_data`).
- The backtest sandbox's embedded `panda_data` is NOT the same version/surface as the public SDK documented by `skill-pandadata-api` (verified 2026-07-08: the sandbox lacked `get_fund_daily`/`get_fund_daily_post` even though the public SDK docs cover them). Probe method existence with `hasattr()` before calling — see the mandatory probe-first step 2a above for anything outside the four bundled templates' demonstrated calls.

When writing custom Python factors for `multi_factor_analysis`:
- Inherit from the `Factor` class:
  ```python
  class MyFactor(Factor):
      def calculate(self, factors):
          # Compute signals based on input series (e.g., close, volume)
          return result_series
  ```
- Shift signals where necessary (`factors['close'].shift(1)`) to prevent look-ahead bias and signal leakage.

## Boundary Controls

- Never execute generated strategy code locally. The assembly script performs static injection only.
- Ensure the disclaimer is rendered in full. No official affiliation with PandaAI or PandaData is claimed.
