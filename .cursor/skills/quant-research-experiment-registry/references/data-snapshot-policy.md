# Data Snapshot Policy

Record both a normalized query fingerprint and a content fingerprint. Small datasets may be hashed in full. Large datasets use deterministic time-stratified samples across declared train/validation/test intervals, with boundary rows retained. Sample copies are never saved without explicit user confirmation.

Observation time is not availability time. If a provider or MCP result does not expose publication, visibility, or revision metadata, the related check is `not_checked` or `insufficient_metadata`.
