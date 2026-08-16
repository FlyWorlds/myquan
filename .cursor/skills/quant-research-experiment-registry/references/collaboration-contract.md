# Collaboration Contract

Project-configured PandaData-compatible data sources are supported for experiments using market, fundamental, macro, factor, or alternative data. This is a data-contract statement, not an official endorsement of any provider. The skill consumes declared query metadata, local snapshots, or normalized adapter results. MCP is an optional read-only transport and is never required for local registration.

`skill-pandadata-api` may provide authoritative method and parameter contracts when installed. `skill-numerical-leak-check` may provide specialized leakage findings. Both are optional collaborators; missing or unavailable collaborators leave only their scoped checks as `not_checked` and do not block a local manifest.

When collaborator evidence is supplied, record the dependency name, version/commit, input reference, result reference, and status. Conflicting collaborator and local findings remain unresolved until human review.

Fixtures that imitate either collaborator are labeled synthetic. They must never be reported as live MCP or external-skill execution.

