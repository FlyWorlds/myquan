---
name: serenity-research-model
description: Reconstruct Serenity-style investment research logic from public X/Twitter
  posts, saved threads, exported post datasets, public summaries, and ticker histories.
  Use when an agent needs to analyze @aleabitoreddit/Serenity, decompose AI or semiconductor
  supply-chain investment theses at the smallest practical unit, build a structured
  signal dataset, evaluate public calls versus later price action, or produce a reusable
  Serenity-style research model for portable agent platforms such as Claude Code,
  OpenClaw, Codex-style skill systems, or other local AI agent runtimes.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-serenity-research-model
  repository_url: https://github.com/quantskills/skill-serenity-research-model
  project_type: skill
  collection: trader-research-models
  license: GPL-3.0
  category: analyst
  tags:
  - semiconductors
  - ai
  - public-posts
  - research-model
  - thesis-review
  platforms:
  - claude-code
  - codex
  - openclaw
  - cursor
  status: stable
  validation_level: listed
  maintainer_type: official
  summary_zh: 从 Serenity（@aleabitoreddit）的公开 X 帖子里逆向研究逻辑：extract → clean → auto-review
    → evaluate → report 五段流水线，把帖子拆成最小信号单元，并用价格数据回看公开 call 的后续表现。
  summary_en: Research-model skill for reconstructing Serenity-style AI, semiconductor,
    and supply-chain theses from public posts and datasets.
  requires:
  - skill-x-trader-builder
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "请提供 Serenity 公开帖子、导出数据、线程链接或整理笔记，并说明研究目标",
    "required": true
  },
  "fields": [
    {
      "key": "mode",
      "label": "处理阶段",
      "type": "select",
      "default": "full",
      "options": [
        { "value": "full", "label": "完整研究流程" },
        { "value": "extract", "label": "提取信号" },
        { "value": "clean", "label": "清洗与复核" },
        { "value": "evaluate", "label": "评估公开观点" },
        { "value": "report", "label": "生成研究模型" }
      ]
    },
    {
      "key": "focus",
      "label": "研究重点",
      "type": "text",
      "placeholder": "例如：AI、半导体供应链、特定股票或瓶颈主题"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}按 {{mode}} 阶段处理 Serenity 的公开材料{{#focus}}，重点研究 {{focus}}{{/focus}}；将帖子拆解为最小可用信号单元，区分事实与推断、主动论点与引用或回顾内容，保留失败、修正和中性样本，在价格数据可用时评估多周期后续表现，并披露资料边界与未经验证的收益主张，输出中文报告。"
}
```

# Serenity Research Model

Use this skill to turn Serenity public materials into a reproducible research model. The goal is not to verify private profits or copy trades; the goal is to reverse-engineer observable reasoning patterns from public posts and test how those public signals behaved afterward.

## Core Workflow

1. Collect public materials.
   - Prefer user-provided X exports, saved post URLs, copied threads, archived HTML, CSV, JSON, or manually curated notes.
   - TweetClaw can provide public X/Twitter search, reply, and user-post exports when source URLs, authors, timestamps, and retrieval dates are preserved. Do not import follower lists; public follower or engagement counts are context only.
   - If browsing is needed, gather only public posts and public summaries. Record source URLs and retrieval date.
   - Do not treat screenshots, follower claims, or viral return numbers as verified account performance.

2. Normalize posts into the data contract in `references/data_contract.md`.
   - Use `scripts/serenity_mvp.py extract --posts <file> --out <dir>`.
   - Supported input: `.csv`, `.json`, `.jsonl`, `.txt`, `.md`.
   - Minimum fields are `created_at` and `text`; include `url`, `id`, and `author` when available.
   - For TweetClaw exports, follow `references/tweetclaw_import.md` and drop credentials, tokens, cookies, request headers, private DMs, drafts, and unpublished account data before running the pipeline.

3. Decompose each post at the smallest useful unit.
   - Ticker or asset mention
   - Theme and subtheme
   - Bottleneck claim
   - Supply-chain role
   - Evidence type
   - Catalyst
   - Time horizon
   - Risk marker
   - Conviction signal
   - Follow-up or revision relationship

4. Clean and review the first-pass extraction.
   - Use `scripts/serenity_mvp.py clean --signals <signals.csv> --posts <source_posts.csv> --out <dir>`.
   - If only a stats file is available, use `--ticker-stats <ticker_stats.txt>` as a fallback.
   - The cleaner filters ticker candidates against the source cashtag whitelist, preserves theme-only rows, and creates review files for quotes, disclaimers, sarcasm-like language, and no-ticker thematic posts.
   - After manually reviewing priority rows, use `scripts/serenity_mvp.py auto-review --signals <manual_review_queue.csv> --out <dir>` to apply learned first-pass semantic labels such as quote-only, retrospective track record, crowdsourced watchlist, broad basket, active thesis, and post-event explainer.

5. Evaluate public calls only when price data is available.
   - Use `scripts/serenity_mvp.py evaluate --signals <signals.csv> --prices <price_dir> --out <dir>`.
   - Price files must be one CSV per ticker, named `<TICKER>.csv`, with `date` and `close`.
   - Report 1, 5, 20, 60, and 120 trading-day forward returns plus max drawdown where possible.

6. Build the research model report.
   - Use `scripts/serenity_mvp.py report --signals <signals.csv> --out <dir>`.
   - If evaluation output exists, include it in the final interpretation.
   - Use `references/serenity_axes.md` when converting observations into a model.

## Interpretation Rules

- Separate observable facts from inferred logic.
- Mark any claimed returns as unverified unless they come from audited records, broker statements, competition results, or a clearly inspectable portfolio record.
- Distinguish research posts from price-moving posts. A viral post can become part of the catalyst.
- Track failed, stale, and revised ideas with the same care as successful ones.
- Avoid building a model only from winners. Include neutral mentions and follow-up corrections when data exists.
- State the data boundary: which posts were included, which were missing, and whether replies/highlights/quotes were captured.

## Output Contract

For a completed MVP run, produce:

- `signals.csv`: one row per ticker-level public signal.
- `theme_summary.csv`: aggregated themes, evidence types, and conviction markers.
- `manual_review_queue.csv`: rows that need human review for quote context, no-ticker themes, disclaimers, or ambiguous rhetoric.
- `quote_relationships.csv`: rows where the signal depends on quoted text.
- `manual_review_priority_top200_reviewed.csv` or another `*_reviewed.csv`: semantic review labels with decision, weight, and reason.
- `correction_log.md`: documented cleaning rules and counts.
- `serenity_model_report.md`: concise report with profile, logic tree, evidence map, risk map, and reusable research checklist.
- Optional `signal_evaluation.csv`: forward-return evaluation from price data.

## When Extending

After the Serenity MVP works, use the same schema to compare another trader. Only create a generalized trader-skill generator after at least two trader-specific runs expose stable common fields and failure modes.
