"""Compatibility entrypoint for the V9.4 multi-market evidence report."""

from __future__ import annotations

from pathlib import Path

if __package__ in {None, ""}:
    import sys

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from scripts.render_soft_report import main
else:
    from .render_soft_report import main


if __name__ == "__main__":
    raise SystemExit(main())
