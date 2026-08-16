---
name: gao-shanwen-research-model
description: Build and apply a Gao Shanwen-style China macro and capital-market research workflow from his books, public articles, and archived materials. Use when analyzing Chinese macro cycles, inflation, capacity cycles, real estate, shadow banking, RMB exchange rates, China equity strategy, asset revaluation theory, or when compiling Gao Shanwen bibliography and reading paths.
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "填写中国宏观、资本市场、书目核验、阅读路径或文章检索问题",
    "required": true
  },
  "fields": [
    {
      "key": "mode",
      "label": "研究类型",
      "type": "select",
      "default": "analysis",
      "options": [
        { "value": "analysis", "label": "宏观与市场分析" },
        { "value": "method", "label": "研究方法" },
        { "value": "bibliography", "label": "书目与阅读路径" },
        { "value": "article_lookup", "label": "公开文章检索" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}按高善文公开著作与文章所体现的研究框架完成 {{mode}} 任务，区分出版物、公开文章与当前外部数据三层证据，围绕现象、因果机制、可观测代理、竞争解释和证伪条件展开，不冒充本人、不作无来源的当代观点归因，输出中文报告。"
}
```

# Gao Shanwen Research Model

## Core Use

Use this skill to analyze China macro and capital-market questions through Gao Shanwen's public research frame: disciplined observation, causal mechanism building, data cross-checking, scenario forecasts, and explicit error conditions.

This skill does not impersonate Gao Shanwen or assert what he would say now. It reconstructs a research workflow from public works and asks Codex to cite the specific book, article, or current data source used.

## First Load

- For book lists, reading paths, or source verification, read `references/bibliography.md`.
- For analysis style, research workflow, or writing an answer in his research tradition, read `references/research-method.md`.
- For article lookup, topic routing, or finding archived public pieces, read `references/article-index.md`.

## Workflow

1. Classify the question:
   - `bibliography`: titles, editions, publication facts, or reading order.
   - `method`: how to study a topic in Gao Shanwen's style.
   - `analysis`: a China macro, policy, market, real-estate, inflation, RMB, shadow-banking, or equity-strategy question.
   - `article_lookup`: find public articles by topic, year, or title.
2. Start from the relevant reference file, then browse live sources when the answer depends on current data, policy, prices, institutional status, or recently changed facts.
3. Separate three evidence layers:
   - Published books and identifiable editions.
   - Public article archive entries and dated reports.
   - Current external data or news used for present-tense claims.
4. Build the answer around mechanisms, not slogans:
   - State the phenomenon.
   - Identify the causal channel.
   - Name observable proxies.
   - Check competing explanations.
   - State what evidence would falsify the view.
5. When writing investment or market analysis, include uncertainty and risk controls. Do not present conclusions as investment advice.

## Style Rules

- Prefer concise Chinese prose with a clear chain of reasoning.
- Avoid grand memorial language unless the user asks for an obituary, tribute, or article.
- Do not quote long copyrighted passages from books or articles. Use short excerpts only when needed, then paraphrase.
- When sources conflict, say so directly and keep the conflict in the answer rather than smoothing it away.
- For present-day macro or market claims, use dated sources and concrete dates.

## Common Outputs

- Verified bibliography with confidence notes.
- Reading path by theme or difficulty.
- Topic map linking questions to books and archived articles.
- Macro research memo with assumptions, evidence, mechanism, scenarios, and falsification tests.
- Chinese article, speech note, or research summary based on cited works.
