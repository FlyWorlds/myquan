# US Sector Rotation Skill

[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

`us-sector-rotation` generates factual US sector rotation reports from Pandadata. It uses `get_stock_sector_median` as the sector-level source, combines `get_us_daily` and `get_us_detail` for constituent return aggregation, and optionally adds PE/PB valuation snapshots.

Maintainer: abgyjaguo  
Organization: QuantSkills  
Repository: `skill-us-sector-rotation`  
License: GPL-3.0-only

## Use Cases

- Compare US sector performance over 1D, 1W, 1M, 3M, and YTD windows.
- Aggregate constituent returns by the sector fields returned by Pandadata.
- Add PE/PB valuation snapshots when the source fields are available.
- Describe sector ranking changes and rotation speed.

## Limits

- The skill does not replace constituent aggregation with ETFs or indexes.
- The skill does not remap Pandadata sector fields into a custom taxonomy.
- Snapshot valuation data must not be described as historical percentile data unless a rolling local cache exists.
- The report must not provide personalized investment advice or trading instructions.

## Data Interfaces

Core Pandadata methods:

- `get_stock_sector_median`: sector median metrics such as `industry_name`, `imed_pe_ttm`, and `imed_pb_ttm`.
- `get_us_daily`: US daily prices for constituent return backfill.
- `get_us_detail`: US security details and sector fields for constituent mapping.
- `get_stock_mktfin_metric`: optional stock-level market and financial metrics for PE/PB snapshots.

All currency values should be treated as USD unless the source data states otherwise. Do not mix USD, HKD, and CNY values.

## Report Structure

Expected sections:

- `# US Sector Rotation...`
- `## 摘要`
- `## 行业/板块表现`
- `## 估值`
- `## 轮动`
- `## 数据说明`
- A final disclaimer containing `不构成投资建议`.

## Validation

After writing a report, run:

```bash
python scripts/validate_report.py path/to/report.md
```

The validator checks structure and required data notes. It does not verify the truth of Pandadata values. Before real API calls, confirm method names, parameter names, and fields against `skills/pandadata-api/references/api-docs.md`.

## Runtime Compatibility

- Codex uses the root `SKILL.md` and `agents/openai.yaml`.
- Cursor uses the root `SKILL.md` and `agents/cursor-rule.mdc`.
- Claude Code, Hermes, and OpenClaw read the root `SKILL.md`; use `agents/portable-loader.md` when native discovery is unavailable.

## Automation

Automation is disabled by default. If the user explicitly requests it, schedule after `21:30 Asia/Shanghai` and include data date, generation time, source interfaces, T+1 or snapshot status, and missing-data notes in the report.
