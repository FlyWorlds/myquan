# Multi-Platform Install Guide

This package contains 1 QuantSkills skill: `skill-b11-auto-stop-loss-take-profit` (Enhanced, **v2 hybrid**).

> **v2 Required per-position input schema**:
> `code, entry_price, entry_date, current_qty, open_price, today, total_equity`.
> Optional: `available_cash` (kept for backwards compat, **not** used as denominator),
> `multiplier` (futures — overrides built-in table).
>
> **v1 fallback fields `holding_trading_days` / `trade_days` / `config["calendar"]` /
> `config["trade_days"]` are REMOVED in v2.** The trading calendar is now hard-dependent
> on [`panda_data`](https://pypi.org/project/panda-data/) `get_trade_cal`, backed by a
> local snappy-compressed parquet cache at `production/trade.parquet`.

---

## v2 First-Run Prerequisites (all platforms)

1. **Install runtime dependencies** (v2 no longer runs on stdlib alone):

   ```bash
   pip install panda_data pyarrow
   ```

   > `panda_data` is a **hard dependency** — the trading calendar has no fallback.
   > `pyarrow` is a **transitive dependency** shipped by `panda_data`; installing it
   > explicitly is only needed if you want the parquet cache layer without
   > `panda_data` at read time. Without `pyarrow`, `build.py` skips the local
   > `production/trade.parquet` cache and calls `panda_data.get_trade_cal` live on
   > every run (functionally correct, just slower).

2. **Configure credentials** (one-time env vars; `build.py` auto-calls `init_token`):

   ```bash
   export PANDA_USERNAME=<your_username>
   export PANDA_PASSWORD=<your_password>
   ```

   Missing credentials raise `RuntimeError` on first calendar access with a guidance link.

3. **Warm the local calendar cache** (fetches today−3y → today+1y, ~18.5KB, one-time):

   ```bash
   python3 scripts/build_calendar.py
   ```

   The shipped `production/trade.parquet` already contains a snapshot at publish time;
   agents may call `refresh_calendar(force=False)` in-process instead of the CLI script.

---

## Claude Code

Copy this entire repository directory to your Claude Code skills folder:

```bash
# macOS / Linux
cp -R skill-b11-auto-stop-loss-take-profit ~/.claude/skills/
```

```powershell
# Windows (PowerShell)
New-Item -ItemType Directory -Force "$HOME\.claude\skills"
Copy-Item ".\" "$HOME\.claude\skills\skill-b11-auto-stop-loss-take-profit" -Recurse -Force
```

After installation, invoke in Claude Code:

```
/skill-b11-auto-stop-loss-take-profit
```

Requirements: Python 3.8+, `panda_data` (hard dependency), `pyarrow` (transitive
via `panda_data`; optional cache-layer acceleration), and `PANDA_USERNAME` /
`PANDA_PASSWORD` env vars (see "v2 First-Run Prerequisites" above).

---

## Codex (OpenAI)

This skill can be used as a function/tool definition for OpenAI Codex agents.

### As a Codex Tool

Add to your Codex SDK configuration:

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "skill_b11_auto_stop_loss_take_profit",
        "description": "Automated stop-loss, take-profit, forced close, and position cap for A-shares and futures. Priority: guard > next-day take-profit (+5%) > next-day stop-loss (-3%) > holding >=2 trading days force close > single-name notional > 10% of total_equity reduce. Trading-day aware calendar via injected holding_trading_days/trade_days or panda_data. Emits the 8-field position adjustment order.",
        "parameters": {
          "type": "object",
          "properties": {
            "positions": {
              "type": "array",
              "description": "List of position objects",
              "items": {
                "type": "object",
                "properties": {
                  "code": {"type": "string"},
                  "entry_price": {"type": "number"},
                  "entry_date": {"type": "string"},
                  "current_qty": {"type": "integer"},
                  "open_price": {"type": "number"},
                  "today": {"type": "string"},
                  "total_equity": {"type": "number", "description": "Total equity — the position-ratio denominator (option A)."},
                  "available_cash": {"type": "number", "description": "Optional, kept for backwards compat; NOT used as denominator."},
                  "multiplier": {"type": "number", "description": "Futures contract multiplier; A-shares ignore it. Overrides built-in table."}
                },
                "required": ["code", "entry_price", "entry_date", "current_qty", "open_price", "today", "total_equity"]
              }
            }
          },
          "required": ["positions"]
        }
      }
    }
  ]
}
```

### Running Locally

```bash
cd skill-b11-auto-stop-loss-take-profit
python3 scripts/build.py
```

Callable from any Codex-managed Python runtime:

```python
import sys
sys.path.insert(0, "/path/to/skill-b11-auto-stop-loss-take-profit/scripts")
from build import run
results = run(positions)  # list or dict; see references/api_guide.md
```

---

## Cursor

Compatible with Cursor's custom tools and `.cursorrules`.

### As a Cursor Tool

Add to `.cursor/tools.json`:

```json
{
  "name": "b11-stop-loss-take-profit",
  "description": "Auto stop-loss, take-profit, forced close, and single-name cap for A-shares and futures (enhanced, trading-day aware).",
  "command": "python3",
  "args": ["${WORKSPACE}/skill-b11-auto-stop-loss-take-profit/scripts/build.py"],
  "env": {}
}
```

### As a Cursor Rule

Add to `.cursorrules`:

```
When the user asks about stop-loss, take-profit, forced liquidation, or position sizing for A-shares or futures, use the b11-stop-loss-take-profit skill.

Required per-position fields: code, entry_price, entry_date, current_qty, open_price, today, total_equity.
Optional: multiplier (futures override).

Run: python3 skill-b11-auto-stop-loss-take-profit/scripts/build.py
```

---

## Hermes

Integrates with Hermes as a callable Python module.

### Registering the Skill

```yaml
# hermes_skills.yml
skills:
  b11-auto-stop-loss-take-profit:
    name: skill-b11-auto-stop-loss-take-profit
    type: build
    runtime: python3
    entry: skill-b11-auto-stop-loss-take-profit/scripts/build.py
    description: >
      Enhanced stop-loss, take-profit, forced close, and single-name position cap
      for A-shares and futures. Trading-day aware via panda_data.get_trade_cal
      (hard dependency, backed by local production/trade.parquet cache).
      Five-level priority: guard -> next-day TP (+5%) -> next-day SL (-3%) ->
      >= 2 trading-day forced close -> notional > 10% total_equity reduce -> hold.
    input_schema:
      type: array
      items:
        code: string
        entry_price: float
        entry_date: string
        current_qty: integer
        open_price: float
        today: string
        total_equity: float
        available_cash: float?      # optional, not the denominator
        multiplier: float?           # futures override
    constraints:
      - business layer: pure Python stdlib (math / numbers / re / datetime / bisect)
      - calendar layer: panda_data (hard dependency, no fallback)
      - cache layer: pyarrow (transitive via panda_data; optional acceleration)
      - research and educational use only
```

### Calling from Hermes

```python
response = hermes.call_skill("b11-auto-stop-loss-take-profit", positions)
```

---

## OpenClaw

Register as an OpenClaw tool.

### Tool Configuration

```yaml
# openclaw_tools.yaml
- name: stop_loss_take_profit_b11
  description: >
    Enhanced automated stop-loss, take-profit, forced close, and single-name
    position cap for A-shares and futures. Five-level priority engine with
    trading-day-aware holding count.
  type: local
  runtime: python3
  entrypoint: skill-b11-auto-stop-loss-take-profit/scripts/build.py
  schema:
    input:
      type: array
      description: List of position snapshots
      items:
        type: object
        required: [code, entry_price, entry_date, current_qty, open_price, today, total_equity]
        properties:
          code: {type: string, description: "Asset code (e.g., 600036, sh600036, IF2406, rb2410)"}
          entry_price: {type: number, description: "Entry price (>0, finite)"}
          entry_date: {type: string, description: "Entry date YYYY-MM-DD"}
          current_qty: {type: integer, description: "Current position quantity (>=0)"}
          open_price: {type: number, description: "Today's open price (>0, finite)"}
          today: {type: string, description: "Current trading date YYYY-MM-DD"}
          total_equity: {type: number, description: "Total equity — the position-ratio denominator (option A)."}
          available_cash: {type: number, description: "Optional, kept for backwards compat; NOT used as denominator."}
          multiplier: {type: number, description: "Optional futures contract multiplier override."}
  limits:
    max_positions_per_call: 1000
  notes: |
    Research and educational use only. No investment advice.
    v2 hard-depends on panda_data (calendar, no fallback); pyarrow is transitive
    via panda_data and enables the local production/trade.parquet cache. Run
    scripts/build_calendar.py once to warm the cache.
```

---

## Usage Boundaries (All Platforms)

- **Research & educational use only** — not investment advice.
- Caller supplies all position data; this skill fetches only the trading calendar via `panda_data`.
- Long-only; no short/hedge positions.
- Does not model price limits, trading halts, liquidity, or slippage.
- Trading calendar defaults to A-shares (SH exchange); HK / US not supported.
- Unknown futures symbols require an explicit `multiplier`.
- v2 requires `panda_data` and env credentials on first calendar access (hard
  dependency, no fallback). `pyarrow` is optional cache acceleration and comes
  transitively with `panda_data`. Run `scripts/build_calendar.py` once to warm
  `production/trade.parquet`.
- See `SKILL.md` for full limitations and `README.md` / `README.en.md` for overview.
