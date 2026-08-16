# Multi-Platform Install Guide

This package contains 1 QuantSkills skill directory:

- `skill-b12-intraday-position-manager` (this repository): Callable BUILD skill for real-time intraday position management.

---

## Claude Code

Copy this entire repository directory to your Claude Code skills folder:

```bash
# macOS / Linux
cp -R skill-b12-intraday-position-manager ~/.claude/skills/
```

```powershell
# Windows (PowerShell)
New-Item -ItemType Directory -Force "$HOME\.claude\skills"
Copy-Item ".\" "$HOME\.claude\skills\skill-b12-intraday-position-manager" -Recurse -Force
```

After installation, invoke in Claude Code:

```
/skill-b12-intraday-position-manager
```

Requirements: Python 3.8+ (standard library only, zero third-party dependencies).

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
        "name": "skill_b12_intraday_position_manager",
        "description": "Dynamic intraday multi-asset position manager. Supports A-shares/ETFs, index futures, commodity futures, HK stocks. Input: positions list with pnl_pct, sellable_qty, locked_qty, price, available_cash, time. Output: standardized 8-field position adjustment orders.",
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
                  "pnl_pct": {"type": "number"},
                  "sellable_qty": {"type": "integer"},
                  "locked_qty": {"type": "integer"},
                  "price": {"type": "number"},
                  "available_cash": {"type": "number"},
                  "time": {"type": "string"}
                },
                "required": ["code", "pnl_pct", "sellable_qty", "locked_qty", "price", "available_cash", "time"]
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
cd skill-b12-intraday-position-manager/scripts
python3 build.py
```

The build script is callable from any Codex-managed Python runtime. Use:

```python
import sys
sys.path.insert(0, "/path/to/skill-b12-intraday-position-manager/scripts")
from build import run
results = run(positions)
```

---

## Cursor

This skill is compatible with Cursor's custom tools and `.cursorrules`.

### As a Cursor Tool

Add to `.cursor/tools.json` or your project's tool configuration:

```json
{
  "name": "b12-position-manager",
  "description": "Intraday multi-asset position manager",
  "command": "python3",
  "args": ["${WORKSPACE}/skill-b12-intraday-position-manager/scripts/build.py"],
  "env": {}
}
```

### As a Cursor Rule

Add to `.cursorrules`:

```
When the user asks about position management, stop-loss, take-profit, or intraday position sizing for A-shares, index futures, commodity futures, or HK stocks, use the b12-position-manager skill.

The skill expects 7 input fields per position: code, pnl_pct, sellable_qty, locked_qty, price, available_cash, time.

Run: python3 skill-b12-intraday-position-manager/scripts/build.py
```

---

## Hermes

This skill integrates with Hermes as a callable Python module.

### Registering the Skill

In your Hermes skill registry:

```yaml
# hermes_skills.yml
skills:
  b12-intraday-position-manager:
    name: skill-b12-intraday-position-manager
    type: build
    runtime: python3
    entry: skill-b12-intraday-position-manager/scripts/build.py
    description: >
      Dynamic intraday position management across multiple asset classes.
      Supports A-shares, ETFs, index futures, commodity futures, HK stocks.
      Distinguishes T+1/T+0, sellable vs. locked positions, cash vs. margin.
    input_schema:
      type: array
      items:
        code: string
        pnl_pct: float
        sellable_qty: integer
        locked_qty: integer
        price: float
        available_cash: float
        time: string
    constraints:
      - zero third-party dependencies
      - pure Python standard library
      - research and educational use only
```

### Calling from Hermes

```python
# Hermes will resolve the skill path automatically
response = hermes.call_skill("b12-intraday-position-manager", positions)
```

---

## OpenClaw

This skill can be registered as an OpenClaw tool.

### Tool Configuration

```yaml
# openclaw_tools.yaml
- name: position_manager_b12
  description: >
    Intraday multi-asset position manager with five-level priority:
    force-close → full stop-loss → halve → add → hold.
    Covers A-shares, A-ETF, index futures, commodity futures, HK stocks.
  type: local
  runtime: python3
  entrypoint: skill-b12-intraday-position-manager/scripts/build.py
  schema:
    input:
      type: array
      description: List of position snapshots
      items:
        type: object
        required: [code, pnl_pct, sellable_qty, locked_qty, price, available_cash, time]
        properties:
          code: {type: string, description: "Asset code (e.g., 600036, IF2406, 00700)"}
          pnl_pct: {type: number, description: "P&L as decimal (0.01 = +1%)"}
          sellable_qty: {type: integer, description: "Sellable quantity"}
          locked_qty: {type: integer, description: "Locked quantity (T+1 only)"}
          price: {type: number, description: "Current price"}
          available_cash: {type: number, description: "Available cash/margin"}
          time: {type: string, description: "Current time HH:MM"}
  limits:
    max_positions_per_call: 1000
  notes: |
    Research and educational use only. No investment advice.
    Zero third-party dependencies. Python 3.8+ standard library only.
```

---

## Usage Boundaries (All Platforms)

- **Research & educational use only** — not investment advice.
- Caller supplies all position data; this skill does not fetch market data.
- Long-only; no short/hedge/spread/calendar strategies.
- Does not account for price limits, trading halts, liquidity, slippage, or auction sessions.
- See `SKILL.md` for full limitations and `README.md` / `README.en.md` for project overview.
