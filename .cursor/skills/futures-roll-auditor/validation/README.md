# Validation

Run from the repository root:

```bash
python scripts/audit_rolls.py --demo
python scripts/audit_rolls.py --demo --adjustment-method difference
python validation/smoke.py
python -B -m unittest discover -s tests -v
```

The repository-local offline suite covers CLI source exclusivity, all adjustment methods, roll-gap calculation, invalid selected contracts, input validation, and report contracts. Demo findings are expected audit output.

PandaData integration was tested separately with sanitized results. No credentials or raw account responses are stored here. `runnable` is a community self-validation level, not official verification.
