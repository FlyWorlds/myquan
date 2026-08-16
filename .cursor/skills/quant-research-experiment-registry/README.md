# Quant Research Experiment Registry

A local, read-only-first skill for registering existing quantitative research directories and preserving reproducibility evidence. It records configuration, declared PandaData queries, data fingerprints, result artifacts, dependency findings, and user decisions without replacing research or data-analysis skills.

## Quick start

Run from the repository root:

```bash
python scripts/scan_experiment.py tests/fixtures/minimal_experiment
python scripts/normalize_config.py tests/fixtures/minimal_experiment/config.json
python scripts/extract_results.py tests/fixtures/minimal_experiment
python scripts/validate_manifest.py examples/manifest.example.json
python -m unittest discover -s tests -v
node scripts/validate-qsh-form.mjs SKILL.md
```

The scanner never executes source code. Formal registration requires a confirmed configuration file. Write operations and reproduction commands require separate confirmation in the user's runtime.

## Direct PandaData boundary

When the experiment uses PandaData, the registered experiment should retain the direct SDK method, parameters, fields, date range, returned schema, and snapshot fingerprint. The runtime dependency is the user's configured `panda_data` package and credentials. MCP is not a runtime dependency and is not required for local registration. This skill does not install packages, log in, or store credentials.

## Collaboration

Project-configured PandaData-compatible data sources are supported for experiments using market, fundamental, macro, factor, or alternative data. Optional collaborating skills may provide normalized evidence when separately available and authorized; missing collaborators leave scoped checks as `not_checked` rather than blocking local registration. This wording describes a data contract, not an official endorsement of any provider. This repository does not copy another skill's research algorithms. Fixtures in `tests/fixtures/` are synthetic and are not claimed to be live PandaData or external-skill output.

## Overlap boundary

This skill registers and audits evidence for experiments that already exist. It does not generate factors, optimize parameters, run a backtest engine, evaluate investment merit, or replace specialized leakage/overfitting checks. See [references/overlap-review.md](references/overlap-review.md) for the public-scan boundary and administrator review requirements.

## Status

This is a draft, listed skill. Passing local tests does not upgrade its registry validation level and does not prove any strategy or result is valid for trading.

## License

GPL-3.0. See [LICENSE](LICENSE).
