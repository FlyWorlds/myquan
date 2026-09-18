"""Read-only Shadow telemetry for the watch HTTP layer.

Does not clear buffers, bump metrics, or change paper decisions.
"""

from __future__ import annotations

import json
from typing import Any


def _json_copy(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def shadow_status_payload() -> dict[str, Any]:
    """Snapshot of in-process Shadow counters. Getters only."""
    from strategy.exit_rules import shadow

    metrics = dict(shadow.get_shadow_metrics())
    buf = shadow.get_shadow_buffer()
    errs = shadow.get_shadow_errors()
    return {
        "enabled": bool(shadow.SHADOW_UNIFIED_EXIT_ENGINE),
        "use_unified": bool(shadow.USE_UNIFIED_EXIT_ENGINE),
        "metrics": metrics,
        "buffer_size": len(buf),
        "error_count": len(errs),
        "last_record": _json_copy(buf[-1] if buf else None),
        "last_error": _json_copy(errs[-1] if errs else None),
    }
