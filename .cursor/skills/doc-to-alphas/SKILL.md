---
name: doc-to-alphas
description: "Generate novel alpha factor expressions from document text (research papers, financial reports, market commentary). Provides an OHLCV formula contract and a toy-data validator. Use when the user asks to derive stock-selection alpha ideas from unstructured text or produce a batch of diverse, validated factor expressions from a document."
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-doc-to-alphas
  repository_url: https://github.com/quantskills/skill-doc-to-alphas
  project_type: skill
  collection: factor-generation
  creator: abgyjaguo
  creator_url: https://github.com/abgyjaguo
  maintainer: abgyjaguo
  maintainer_url: https://github.com/abgyjaguo
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-doc-to-alphas
  repository_url: https://github.com/quantskills/skill-doc-to-alphas
  project_type: skill
  collection: factor-generation
  category: factor
  tags:
    - alpha-generation
    - factor-discovery
    - ohlcv
    - validation
    - stock-selection
    - doc-to-alphas
  platforms:
    - claude-code
    - codex
    - cursor
    - hermes
    - openclaw
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires: []
  summary_zh: 从文档文本生成 OHLCV alpha 因子表达式，并提供公式契约与玩具数据自动验证。
  summary_en: Generate OHLCV alpha factor expressions from document text, with a formula contract and automatic toy-data validation.
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "描述任务，或直接粘贴研报/财报段落；也可上传 PDF 附件",
    "required": true
  },
  "fields": [],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请从上述文档材料中提炼可计算的 OHLCV alpha 因子表达式，并用玩具数据自动验证可计算性；输出中文报告。"
}
```

# Doc to Alphas

Use this skill to derive novel alpha factor expressions from document text.
You (the agent) generate the expressions using your own LLM following the
contract in `references/alpha_ops.md`, then run the bundled validator to
confirm each expression is computable.

This skill is **fully self-contained** — no API keys, no external services,
no other skills required. It provides:

- A **formula contract** — exactly 6 fields and 27 functions that every
  expression must use.
- A **toy-data validator** — evaluates each expression against synthetic
  OHLCV data (30 dates × 5 symbols) to catch errors instantly.
- **Look-ahead bias detection** — catches expressions that peek into the
  future (truncation test + static scan).
- **Numerical stability checks** — flags NaN/Inf ratios, division-by-zero,
  log-of-negative, and extreme-value instability.
- **Auto-correction loop** — failed alphas get categorized error diagnostics
  and correction hints; the agent retries up to 5 times.

## Creator, Maintainer, And Scope

- Creator: `abgyjaguo` (`https://github.com/abgyjaguo`).
- Maintainer: `abgyjaguo` for the QuantSkills community.
- Repository: `https://github.com/quantskills/skill-doc-to-alphas`.
- License: GNU General Public License v3.0 only (`GPL-3.0-only`).
- Scope: research-oriented alpha factor ideation and toy-data validation from
  document text. The skill is not official investment advice, a certified data
  product, or a guarantee of trading performance.

## Core Workflow

1. **Read the contract** — `references/alpha_ops.md` defines every allowed
   field and function.
2. **Generate alphas** — use your own LLM to produce N alpha expressions
   from the user's document text. Each alpha must have `name`, `expression`,
   `description`, and `rationale`. Output as a JSON array.
3. **Save to file** — write the alpha array to a JSON file.
4. **Validate** — run `scripts/generate_alphas.py --alphas <file>
   --correction-context` to evaluate every expression against toy data.
   The validator checks for syntax errors, unsupported fields, **look-ahead
   bias**, and **numerical instability**.
5. **Auto-correct** — if any alphas fail, the `--correction-context` flag
   outputs a ready-to-use LLM correction prompt with specific error
   diagnostics and hints. Feed this to your LLM, save the corrected alphas,
   and re-validate. **Retry up to 5 times** until all alphas pass.
6. **Report** — show the user which alphas passed and which failed, with
   error details for failures.

## Auto-Correction Loop (Retry up to 5×)

```text
FOR attempt = 1 to 5:
  1. Generate/save alphas → validate
  2. If all pass → DONE
  3. If failures → use --correction-context to get fix prompt
  4. Feed correction prompt to LLM → save corrected alphas
  5. If attempt == 5 and still failing → report failures to user
```

## Calling Pattern

```bash
# After the agent generates alphas and saves them to alphas.json:
python scripts/generate_alphas.py --alphas alphas.json

# With correction context for the retry loop:
python scripts/generate_alphas.py --alphas alphas.json --correction-context

# With custom output path:
python scripts/generate_alphas.py --alphas alphas.json --output results.json
```

No prerequisites beyond Python with `numpy` and `pandas`.

## Agent Prompt Template

When the user asks you to generate alphas, use this prompt:

```
You are a quantitative researcher. Based on the following document, generate
exactly {n} novel alpha factor expressions for stock selection.

DOCUMENT:
{text}

Follow the contract in references/alpha_ops.md exactly:
- ONLY these 6 fields: open, high, low, close, volume, amount
- ONLY the 27 functions listed in the contract
- Do NOT use vwap, adjfactor, or any other field

CRITICAL — LOOK-AHEAD BIAS PREVENTION:
- delay(x, n), delta(x, n), and returns(x, n) MUST use n ≥ 1
- All rolling functions inherently use only past data — this is correct

CRITICAL — NUMERICAL STABILITY:
- Never divide by something that could be zero. Use max(denom, 1e-8) as guard.
- Never take log(x) without ensuring x > 0: use log(max(x, 1e-8)).
- Prefer rank() and zscore() based expressions — they are naturally stable.

Output a JSON array of objects with keys: name, expression, description, rationale.
```

## Output Contract

After validation, you get a JSON object with:

- `total_checked` — number of alphas tested
- `passed` / `failed` — counts
- `toy_data_shape` — `[dates, symbols]` of validation data
- `results` — per-alpha: `name`, `expression`, `ok`, `error` (if failed),
  `eval_time_ms`, `output_shape`/`output_mean` (if passed)

## Reference Files

- `references/alpha_ops.md` — full field/function contract (the single source of truth).
- `scripts/formulas.py` — Python definitions: HELPER_DOCS, ALLOWED_FIELDS, ALLOWED_FUNCTIONS.
- `scripts/validation.py` — toy data generator and ToyAlphaEngine.
- `scripts/generate_alphas.py` — CLI validator: takes a JSON file of alphas, validates them.
- `references/agent-integration.md` — install and smoke-test on Claude Code, Codex, etc.

## Cross-Agent Use

- Codex and Claude Code can load this folder directly as `$doc-to-alphas`
  through `SKILL.md`.
- Cursor should use `agents/cursor-rule.mdc` as the project rule adapter and
  keep the full skill folder under `.cursor/skills/doc-to-alphas`.
- Hermes and OpenClaw should use `agents/portable-loader.md` when they do not
  natively discover `SKILL.md` folders.
- OpenAI-style agent registries can read `agents/openai.yaml` for display name,
  short description, and default invocation prompt.
