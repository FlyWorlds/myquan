"""Versioned backtest-only delivery projection; committed account fills stay immutable."""
from __future__ import annotations

DOCUMENT_KEY = 'strategy1_delivery_backtest'


def apply_projection(entries, projection):
    if not projection:
        return entries, None
    start, end = projection['start'], projection['end']
    replacements = projection['entries']
    if (start > end or not replacements or
            any(e.get('source') != 'strategy1_backtest' or
                not start <= str(e.get('session', '')) <= end or
                e.get('side') not in {'buy', 'sell'} for e in replacements)):
        raise ValueError('Invalid strategy1 backtest delivery projection')
    kept = [e for e in entries if not start <= str(e.get('session') or e.get('time') or '')[:10] <= end]
    return kept + [dict(e) for e in replacements], {
        'source': 'strategy1_backtest', 'start': start, 'end': end,
        'label': projection['label'], 'limitations': projection.get('limitations', []),
    }
