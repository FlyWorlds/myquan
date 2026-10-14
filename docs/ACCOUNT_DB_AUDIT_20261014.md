# Account database review, 2026-10-14

## Scope

First priority batch: consistent database reads, account/delivery/cycle returns,
backup and isolated restore, and read-only strategy16 evidence checks. No historical
cash, delivery, simulator price or event timestamp was rewritten. T1 recovery,
minute collection and full-suite cleanup remain subsequent batches.

## Fixed logic

- Account valuation now reads holdings, cash, trades and deliveries from one committed
  revision. Display reads do not initialize capital or write daily anchors.
- Nested transaction scopes cannot reload an expired cache over pending mutations.
  The outer scope refreshes once; CAS conflicts still reject writes and restore memory.
- All session sell fills count, including partial sales while a position remains open.
  Open daily PnL is calculated on remaining shares, not a row that may already include
  realized PnL. Missing quotes, cost/quantity conflicts and missing daily values remain unknown.
- Committed price adjustments affect delivery, account and paper cycle read models,
  never cash a second time. Original fills and timestamps remain preserved. Ambiguous
  adjustment targets are reported and cannot silently produce a return percentage.
- Database-mode automatic opening reprice is disabled: later OHLC cannot transform
  an already committed intraday PATH exit into an opening fill.
- Account history accepts only the exact current revision; publication carries the
  revision actually used for valuation, not a later shared-cache token.
- Whole-cycle PnL uses all corrected sell legs plus remaining unrealized PnL divided
  by original purchase capital. Quantity-chain mismatch prevents a plausible false value.

## Historical evidence requiring reconciliation

- One committed 002636 adjustment reprices 300 shares from 70.72 to 67.10, a -1086
  cash/PnL difference. It was present before this work. The original final-fill price
  is retained; effective returns honor the recorded adjustment without reapplying cash.
  Whether that legacy automatic correction was legitimate needs original path evidence.
- Six delivery quantity-chain discontinuities were found: 600869, 000070, 600522,
  and three 600072 entries. These can indicate missing manual initial positions,
  resets or repeated exits; discontinuity alone does not prove a duplicate. Do not
  delete records or invent balancing cash before establishing the cause.
- Six strategy16 books lack a matching retained entry event (603301, 603920,
  002453, 002169, 600346, 603659). Missing evidence is not proof of a wrong price;
  the audit distinguishes missing events from actual price mismatches.
- The existing opening equity anchor remains inconsistent with the cash ledger.
  New read logic exposes the discrepancy rather than changing cash to hide it.
  Real runtime validation at revision 1370 recorded cash 179535, marked value
  112644, equity 292179, total PnL -7821, daily PnL -4113 and position 38.6%.
  The opening-anchor difference is -9795 and remains an unresolved historical item.
- `paper_closed_trades` and Java `/api/paper/closed` remain original-fill forensic
  queries. The UI delivery API `/api/trades` and comprehensive paper-cycle return
  use the effective adjusted read model; a final-fill percentage is not cycle PnL.

## Verification

```bash
python backend/backup_database.py --verify-restore
python holdingStocks/audit_database_account.py
python holdingStocks/run_regression_tests.py
cd backend && mvn -o package
```

Backup uses one InnoDB transaction and restrictive file permissions. Restore runs
only in a newly created `myquan_restore_check_*` database, redirects source-qualified
views, verifies restored trade/delivery projections and positive holdings against
the complete account state, then removes only that scratch database. It never
restores over production. Avoid concurrent schema migrations during a backup.
The verified backup manifest is under `backend/logs/backups/`; backups and detailed
account reports are excluded from Git. Scheduling automatic backups remains open.

241 default regression tests, 21 backend tests/package, and 30 focused pytest tests
passed. Real MySQL restore verification passed (revision 1263: two open holdings,
76 trades, 44 deliveries). The historical audit intentionally does not report a
clean account while evidence gaps and opening-equity differences remain. Full-suite
legacy failures were not reclassified as fixed by these focused tests.
