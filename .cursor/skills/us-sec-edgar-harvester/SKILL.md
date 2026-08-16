---
name: us-sec-edgar-harvester
description: "Harvest and structure US SEC EDGAR public filings - 8-K, Form 4, 13D/G, 13F, S-1 - into a deduplicated, sourced, time-lined dataset. Use when a user asks to collect SEC filings, track insider Form 4 or 13F activity from EDGAR, or build a filing timeline for a US ticker from public data."
license: GPL-3.0-only
quantSkills:
  organization: https://github.com/quantskills
  organization_url: https://github.com/quantskills
  repository: quantskills/skill-us-sec-edgar-harvester
  repository_url: https://github.com/quantskills/skill-us-sec-edgar-harvester
  project_type: skill
  collection: us-sec-edgar-harvester
  license: GPL-3.0
  category: data-api            # trader-research / factor / data-api / replication / monitor / analyst / tooling
  tags: [sec,edgar,filings,form4,13f]                  # lowercase-hyphenated, 1-10 items
  platforms: [claude-code, codex, openclaw, cursor]        # claude-code / codex / openclaw / cursor / workbuddy
  language: zh-en
  status: draft                     # draft / active / stable / deprecated
  validation_level: listed          # listed / runnable / verified (community three-level scheme)
  maintainer_type: community        # official / community
  creator: abgyjaguo
  maintainer: abgyjaguo
  requires: []                      # dependent sibling skill-* / agent-* repository names
  summary_zh: "抓取并结构化美股 SEC EDGAR 公开文件（8-K/Form 4/13D-G/13F/S-1），去重、标注来源与时间线。"      # 8-120 chars
  summary_en: "Harvest and structure US SEC EDGAR public filings into a deduplicated, sourced, time-lined dataset."      # 8-200 chars
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "说明要采集的美国公司、内部人或机构管理人，以及期望的申报范围",
    "required": true
  },
  "fields": [
    {
      "key": "subject_type",
      "label": "主体类型",
      "type": "select",
      "default": "issuer",
      "options": [
        { "value": "issuer", "label": "上市公司" },
        { "value": "insider", "label": "内部人" },
        { "value": "institution", "label": "机构管理人" }
      ]
    },
    {
      "key": "symbol",
      "label": "美股代码",
      "type": "text",
      "placeholder": "例如 AAPL；内部人或机构可留空"
    },
    {
      "key": "form_types",
      "label": "申报类型",
      "type": "text",
      "default": "8-K,4,SC 13D,SC 13G,13F-HR,S-1",
      "help": "逗号分隔，可包含 /A 修订版"
    },
    {
      "key": "date",
      "label": "截止日期",
      "type": "date",
      "default": ""
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}从 SEC EDGAR 公共端点采集 {{subject_type}} 的申报。{{#symbol}}美股代码为 {{symbol}}。{{/symbol}}申报类型为 {{form_types}}。{{#date}}截止日期为 {{date}}。{{/date}}未指定时采集最近申报；如需起止窗口请在任务材料中写明。解析并保留 CIK、accession、申报日期与事件/报告期日期，按 accession 去重并标注修订替代关系，生成逐行可追溯的数据集和时间线；遵守 SEC 公平访问限速，只整理公开事实，不评分、预测或荐股，输出中文报告。"
}
```

# US SEC EDGAR Harvester

Use this skill to **collect and structure US SEC EDGAR public filings** (8-K, Form 4,
13D/13G, 13F, S-1) for a US-listed issuer or an insider/fund, and turn them into a
**deduplicated, sourced, dated filing timeline plus a structured dataset**. This is a
pure information-collection (讯息收集) skill: it gathers and organizes public facts. It
does not score, rank, forecast, or advise. Keep every row traceable to its EDGAR
accession number and never present output as investment advice.

This skill reads **only public SEC EDGAR endpoints** (full-text search, the submissions
API, and the filing index/document archive). It is deliberately distinct from the
Pandadata-backed `hk-us-insider-radar` / `hk-us-holder-concentration` skills: those draw
from the Pandadata vendor feed, while this one harvests the primary-source SEC public
filings directly. Prefer this skill when the user wants raw, citable EDGAR filings; prefer
the Pandadata skills when the user wants the vendor's normalized cross-market feed.

## Core Workflow

1. **Scope the request.** Identify the subject: a US ticker/company, an insider (a natural
   person filing Form 4), or an institutional manager (13F filer). Note the requested form
   types and the date window. Read `references/source_boundary.md` for what may be fetched.
2. **Resolve identifier → CIK.** Map a ticker to its zero-padded 10-digit CIK via the
   public ticker map (`https://www.sec.gov/files/company_tickers.json`) or EDGAR full-text
   search. Record both the raw and padded CIK. One company may have multiple CIKs
   (subsidiaries, historical entities); keep them separate and labelled.
3. **Enumerate recent filings.** Call the submissions API
   (`https://data.sec.gov/submissions/CIK##########.json`) to list recent filings, or use
   full-text search (`https://efts.sec.gov/LATEST/search-index?q=...&forms=...`) when the
   subject is an insider/fund rather than an issuer. Filter by the requested form types
   (`8-K`, `4`, `SC 13D`, `SC 13G`, `13F-HR`, `S-1`, and their `/A` amendments).
4. **Fetch and parse the structured bits** for each accession (delegate raw HTTP fetches to
   the runtime's web/fetch tool; see `references/methodology.md` for the field maps):
   - **Form 4** — reporting owner (name + CIK), issuer, relationship (director / officer /
     10% owner), and every transaction row: transaction code (P/S/A/M/G/F/...), date,
     shares, price, acquired/disposed flag, and post-transaction beneficial ownership;
     keep non-derivative (Table I) and derivative (Table II) rows separate.
   - **13F-HR** — the information table holdings: issuer name, CUSIP, value, shares/principal,
     put/call, investment discretion; note the reporting period end.
   - **8-K** — the item numbers reported (e.g. 1.01, 2.02, 5.02, 8.01) and the event date.
   - **13D / 13G** — the reporting person, the subject issuer, percent of class, and the
     purpose/aggregate-ownership fields; treat 13D (active) vs 13G (passive) distinctly.
   - **S-1** — registrant, offering type, and the security/amount registered when stated.
5. **Distinguish the dates.** For every filing capture BOTH the **filing/acceptance date**
   (when EDGAR received it) and the **event/period date** (transaction date, 8-K event date,
   or 13F period-of-report). They differ, and mixing them corrupts a timeline.
6. **Dedup and supersede.** Deduplicate by **accession number** (the unique EDGAR ID). When
   an amended filing (`/A`) is present, mark it as superseding the original and keep both,
   flagging the original as `superseded_by`.
7. **Build the timeline + dataset.** Emit a chronological, sourced timeline and a flat
   structured dataset (one row per filing or per transaction, with the accession URL on
   every row). Add a plain-language summary of what was collected and its coverage gaps.
8. **Validate.** Run `scripts/validate_report.py <report.md>` to confirm the report carries
   the required sections and per-row source/date labels before delivery.

## Output Contract

Produce:

- `filings_dataset.csv` (or `.json`) — one row per filing (or per Form 4 transaction) with,
  at minimum: `accession`, `form_type`, `filer`/`reporting_owner`, `cik`, `subject_issuer`,
  `filing_date`, `event_or_period_date`, `is_amendment`, `superseded_by`, `source_url`, and
  form-specific columns (transaction code/shares/price, item numbers, percent-of-class, etc.).
- `filing_timeline.md` — a dated, chronological, per-filing timeline, every entry carrying
  its accession number and the canonical EDGAR document URL.
- A concise factual summary: subject, CIK(s), form types and window covered, filing counts,
  notable amendments, and any coverage gaps or rate-limit truncation. **Facts only — no
  ranking, valuation, or recommendation.**

Every emitted row/entry MUST cite its EDGAR accession number and source URL, and MUST label
which date it uses (filing vs event/period).

## Data Sources

- **EDGAR full-text search** — `https://efts.sec.gov/LATEST/search-index` (JSON).
- **EDGAR submissions API** — `https://data.sec.gov/submissions/CIK##########.json`.
- **Ticker→CIK map** — `https://www.sec.gov/files/company_tickers.json`.
- **Filing index & documents** — `https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/`.

All are public, no-key SEC endpoints. See `references/edgar-sources.md` for exact URL shapes
and `references/methodology.md` for parsing and pitfalls. Actual HTTP calls are delegated to
the runtime's web/fetch capability; this skill supplies the endpoints, field maps, and rules.

## References

- `references/edgar-sources.md` — exact EDGAR endpoints, URL shapes, headers, rate limits.
- `references/methodology.md` — form-by-form field maps, transaction codes, dedup/supersede
  rules, date semantics, and graceful-degradation notes.
- `references/source_boundary.md` — what data this skill may and may not read.

## Boundaries

- **Information collection only.** This skill gathers and structures public facts. It does
  NOT analyze, score, rank, value, forecast, or recommend.
- **Public SEC data only.** Reads public EDGAR endpoints; ships no keys or credentials. Must
  send a descriptive, generic `User-Agent` per SEC fair-access policy — never a secret, never
  a real person's private contact unless the user explicitly supplies their own.
- **Respect fair-access rate limits.** Throttle requests; on 403/429 degrade gracefully
  (back off, reduce scope, report partial coverage) rather than hammering the endpoint.
- Distinct from the Pandadata-backed `hk-us-insider-radar` / `hk-us-holder-concentration`
  (different source: primary SEC public filings vs the Pandadata vendor feed).
- Research and workflow tooling only; not official, certified, or verified; not affiliated
  with the SEC or any covered issuer.
- 不构成任何投资建议 / does not constitute investment advice.
