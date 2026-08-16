# Portable Loader

Use this loader with Hermes or OpenClaw when the runtime does not natively
discover `SKILL.md` folders. If native skill discovery is available, install
the full folder unchanged and load `SKILL.md` directly.

```text
You have access to a local skill named ag-futures-seasonality at:
<AG_FUTURES_SEASONALITY_SKILL_ROOT>

When the user asks about seasonal patterns, strong or weak months, crop-cycle
timing, or seasonality research for Chinese agricultural futures:
1. Read <AG_FUTURES_SEASONALITY_SKILL_ROOT>/SKILL.md.
2. Read <AG_FUTURES_SEASONALITY_SKILL_ROOT>/references/crop-calendar.md for
   crop-cycle interpretation and references/source_boundary.md for evidence
   limits.
3. Confirm the variety, continuous-contract construction, and data window.
4. Use scripts/seasonality.py for deterministic calculations.
5. Report average return, win rate, sample years, and statistical significance
   for every seasonal claim, including the multiple-testing caveat.
6. Separate facts from inference and do not provide buy/sell signals,
   guaranteed outcomes, or investment advice.
```

Runtime placement:

- Codex: install under a Codex skill path and invoke
  `$ag-futures-seasonality`.
- Claude Code: install under a Claude skill path and invoke
  `$ag-futures-seasonality`.
- Cursor: copy to `.cursor/skills/ag-futures-seasonality` and enable
  `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount the folder as a local skill root or paste the loader
  above with the real path.
