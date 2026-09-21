"""Paper state errors — remote / concurrency / network."""

from __future__ import annotations


class PaperStateError(Exception):
    """Base for paper state repository failures."""


class StateConflictError(PaperStateError):
    """Optimistic concurrency: version mismatch."""


class DuplicateExecutionError(PaperStateError):
    """Same execution_id already applied (idempotent retry)."""


class LeaseConflictError(PaperStateError):
    """Another writer holds an active lease (ACTIVE_WRITER_EXISTS)."""


class StaleWriterError(PaperStateError):
    """Mutation rejected: fencing token / lease token is stale."""


class RemoteUnavailableError(PaperStateError):
    """Remote DB unavailable — NEW PAPER MUTATION must pause (no local fallback write)."""
