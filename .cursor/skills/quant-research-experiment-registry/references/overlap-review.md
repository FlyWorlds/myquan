# Overlap Review

Review scope: public quantskills repositories and public registry material inspected during the preparation review on 2026-08-06. This is not an organization-wide proof of non-overlap.

## Boundary

This skill registers existing experiment assets, direct PandaData query metadata, snapshots, results, decisions, and reproducibility evidence. It does not generate factors, optimize models, run a backtest engine, evaluate investment merit, or implement numerical-leakage or overfitting algorithms.

## Nearest public neighbors

- `skill-quant-research`: research production and validation; this skill only records an existing experiment.
- `skill-quant-research-replication`, `skill-paper-replication`, `skill-report-replication`: reconstruct and validate external research; this skill records the resulting experiment.
- `skill-numerical-leak-check`, `skill-backtest-overfit`: specialized checks; this skill records optional evidence and status.
- `skill-factor-review`: factor-library review and research direction; this skill records facts and artifacts, not recommendations.
- `skill-futures-roll-auditor`: continuous-contract and roll audit; this skill can register its output but does not reimplement that audit.

## Private and quarantined scope

Public APIs and public registry artifacts cannot enumerate all private, quarantined, unregistered, or not-yet-refreshed repositories. The quantskills registry maintainer must perform the final organization-wide semantic overlap review with appropriate read access before accepting this repository. No private source or internal path is reproduced here.

## Author and provenance

Repository provenance is represented by the repository's normal version-control metadata. This repository contains no generated-by, agent, model, or tool attribution. Synthetic fixtures are explicitly labeled and are not live data validation.
