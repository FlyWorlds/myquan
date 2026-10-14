# myquan Backend

Java 21 language target, Spring Boot 3.5.16, Maven, JDBC/HikariCP and Flyway.
The local database is MySQL at `127.0.0.1:3306`, database `myquan`.
Python strategy execution and the existing holdings ledger remain independent.

## Local Setup

Requirements: JDK 21-25, Maven 3.6.3+, and a running local MySQL server.

Create the database once with an interactive password prompt:

```bash
mysql --protocol=TCP -h 127.0.0.1 -P 3306 -u root -p \
  -e "CREATE DATABASE IF NOT EXISTS myquan CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

`config/application-local.properties` contains this machine's connection credentials
and is intentionally tracked in Git for local development at the user's request.
Its username and password are fixed local values; do not reuse them on public servers.
Other machines can change the local file or supply `SPRING_DATASOURCE_USERNAME`
and `SPRING_DATASOURCE_PASSWORD` overrides. Host, port and database use
`DB_HOST`, `DB_PORT` and `DB_NAME` environment variables.

Run from the project root:

```bash
bash backend/run.sh
```

The launcher resolves Homebrew's JDK when macOS's default `java` is not configured.
The API binds to `127.0.0.1:8080`; use `SERVER_PORT=8081 bash backend/run.sh`
if that port is occupied. Stop the foreground process with Ctrl+C.

## Verification

```bash
curl http://127.0.0.1:8080/actuator/health
curl http://127.0.0.1:8080/api/system/status
bash backend/run.sh test
bash backend/run.sh package
```

`/api/system/status` performs a database query and reports the database name,
product version, schema version and Shanghai time. Database failures return HTTP 503.
The local configuration is not packaged into the JAR. Run a packaged JAR from
the `backend` directory so its external configuration is found.

Flyway initializes `backend_metadata` and its own migration history in `myquan`.
Migration V2 creates `paper_holdings` and `paper_holdings_sync`. There are no
market-data migrations yet.

## Database-Authoritative Paper State

V3 stores the complete account document (including zero-quantity positions,
cash, daily settlement, slot queues, factor memory and alert state) in
`paper_account_state`. `paper_holdings`, `paper_trade_history` and
`paper_delivery_entries` are queryable projections updated in the same transaction.
Keep business edits behind the API; do not directly edit projection tables.

```bash
curl -X POST http://127.0.0.1:8080/api/paper/state/migrate
curl http://127.0.0.1:8080/api/paper/state
curl http://127.0.0.1:8080/api/holdings
```

Migration is one-time and reads the configured `HOLDINGS_FILE` (default
`../holdingStocks/holdings.json`) plus sibling `trades.jsonl` and `trade_ledger.json`.
Stop old writers and back up the files before migration. Once initialized,
re-migration and the legacy `/api/holdings/sync` return HTTP 409.

`PUT /api/paper/state` requires an explicit `expectedRevision`, `requestId`, `holdings`,
`trades` and `ledger`. It locks the account row and atomically updates all tables.
A stale revision returns 409. Retrying the identical request ID cannot apply it
twice; reuse with another payload or after subsequent writes also returns 409.
`paper_state_writes` records committed requests. Failed writes roll back the whole
transaction. Unknown holding fields survive round trips in the account document.
Committed trade/delivery history cannot be truncated, reordered or rewritten.
Account reset may only archive existing trades, never reactivate or delete them;
corrections must be new adjustment events. Serialization/preparation failures also
restore the Python in-memory state. Reset uses its original revision without an
intermediate refresh. The web view rejects older database polls and hides account
returns until holdings/cash and the quote snapshot are compatible.

Python defaults to `HOLDINGS_STORAGE=database`. `PAPER_BACKEND_URL` selects the
Spring Boot API, default `http://127.0.0.1:8080`. No database failure falls back
to local file writes. Explicit `HOLDINGS_STORAGE=local_json` is for offline fixtures
and tests only. The web UI reads `/api/holdings/state` through the Python HTTP
proxy; quotations still use the existing live feed. Costs use DECIMAL; missing
available quantity stays NULL. Strategy simulator state remains separate.

All devices must point to the SAME backend/database to share holdings. Separate
localhost databases do not synchronize with one another. For now run one trading
writer; database revision checks prevent stale overwrites but are not a full
multi-device trading-engine scheduler. Back up MySQL, not Git runtime files.
Keep the server bound to localhost: authentication is required before remote exposure.
Tests use an isolated in-memory H2 database; real MySQL connectivity and migrations
must also be checked by starting the application and calling its health endpoints.

Local verification on 2026-10-14: backend, Python regression and four frontend
consistency tests passed; see TODO.MD for exact counts and remaining full-suite failures.
Packaging succeeded,
V3 was applied to real MySQL, and the complete local state was imported and reconciled.
This MySQL server reports version 26.7.0. Flyway logs an untested-version warning;
the initial migration was verified successfully. Future MySQL-specific migrations
must also be verified on the actual server rather than only on H2.
