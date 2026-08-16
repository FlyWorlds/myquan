# Factor Mining PandaAI

[简体中文](README.md) | **English**

[![type](https://img.shields.io/badge/type-community--skill-blue)](https://github.com/quantskills)
[![license](https://img.shields.io/badge/license-GPLv3-blue)](LICENSE)

Mine factors in two modes: AI-led blind discovery using PandaAI data and
analysis feedback, or evidence-grounded extraction from public papers,
reports, PDFs, DOCX files, or text. Translate candidates into `pandaai-cli`
formulas and optionally create, backtest, and analyze them on PandaAI.

This is an unreviewed QuantSkills community project for research and education
only.

## Quick Start

```bash
python -m pip install pandaai-cli pdfplumber
pandaai-cli login
```

Use interactive login. Never put a phone number, password, token, or config
file contents in prompts, shell history, examples, or this repository.

Example request:

```text
Use $factor-mining-pandaai to extract three reproducible A-share factors from
this paper. Show formulas, directions, parameters, and assumptions before
running any backtest.
```

The skill extracts source logic first, checks PandaAI formula constraints, and
uses the external platform only when the user requests execution.

For blind mining, it proposes a diversified, deduplicated candidate batch and
research budget before using PandaAI feedback to iterate and validate winners.
The Python engine performs three-stage genetic search (base mechanisms, time
series transforms, then cross-sectional transforms) to minimize chat tokens.
Field pools can come from Excel, TXT/CSV/TSV, JSON, direct names, or documented
market-field defaults; every candidate retains field provenance and category.
Generated candidates use PandaAI's documented native fields and operators in
formula mode; the local catalog validates names, lookbacks, nesting, and blocks
forward-looking functions before platform execution.

## Research Boundaries

- Data source: PandaAI A-share daily data; confirm actual fields and coverage on the platform.
- Default universe: PandaAI's default Shanghai/Shenzhen A-share universe.
- Parameters: roughly 60 days, 10 groups, and daily rebalancing by default; set dates and frequency explicitly for serious research.
- Limitations: formula support, platform error `10075`, short samples, data snooping, transaction costs, and tradability treatment can all affect results.
- Risk: backtests are historical diagnostics, not forecasts or investment advice.

## Runtime Support

The core contract is model- and vendor-neutral. Any AI that can read Markdown,
access local files, and execute Python/CLI commands can use it. Named runtime
adapters are optional examples; other AIs can use the portable loader in
`agents/`.

## Attribution And Maintenance

- Original author: [`TerribleCookie`](https://github.com/TerribleCookie)
- Upstream: [`TerribleCookie/skill-factor-mining-pandaai`](https://github.com/TerribleCookie/skill-factor-mining-pandaai)
- QuantSkills migration and maintenance: [`abgyjaguo`](https://github.com/abgyjaguo)
- Migration changes: five-runtime adapters, bilingual documentation, GPLv3 licensing, community metadata, safer login guidance, and explicit research-risk boundaries.

## License

This migrated version is released under GNU General Public License v3.0 only
(`GPL-3.0-only`). Third-party components remain subject to their own licenses.
See [NOTICE](NOTICE) for the upstream MIT notice and [LICENSE](LICENSE) for the
full GPLv3 text.
