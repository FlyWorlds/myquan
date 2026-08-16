# Portable Runtime Loader

This file is the portable entry point for Hermes, OpenClaw, and other Markdown-capable agent runtimes.

## Load

1. Read `../SKILL.md` in full.
2. Follow the workflow, data boundaries, scoring gates, and reporting requirements defined there.
3. Load only the relevant files under `../references/`.
4. Prefer the existing programs under `../scripts/` to duplicated implementations.

## Safety

- Use PandaData only for quantitative conclusions.
- Read credentials only from the documented environment variables or local credential file.
- Do not expose credentials, tokens, or other sensitive information.
- Do not promise returns, provide personalized investment advice, or generate automatic trading instructions.
- Clearly label missing, unsupported, delayed, or proxy data.
- State that results are for research and education and are not officially certified by QuantSkills.

## Default Task

Analyze an A-share company by separating observed fundamentals, market-consensus proxies, price-implied expectations, and enterprise-investment quality. Report the margin of safety, value-trap gates, catalysts, counter-evidence, falsification conditions, data limitations, and provenance.
