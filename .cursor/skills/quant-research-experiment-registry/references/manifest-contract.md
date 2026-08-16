# Manifest Contract

The manifest is a record of evidence, not a claim that a strategy works. Core fields are versioned and validated by `schemas/manifest.schema.json`; project-specific fields belong under `extensions`.

A result can be `available_with_risk` while reproducibility is `partial` or `failed`. Missing evidence must be represented as `not_checked`, `insufficient_metadata`, or `unresolved`, never as an implicit pass.
