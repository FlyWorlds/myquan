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

## Holdings Mirror

`POST /api/holdings/sync` manually mirrors positive-quantity positions from
`../holdingStocks/holdings.json` into MySQL. Override the source with `HOLDINGS_FILE`.
`GET /api/holdings` reads the database snapshot and its source/sync timestamps.

```bash
curl -X POST http://127.0.0.1:8080/api/holdings/sync
curl http://127.0.0.1:8080/api/holdings
```

This is a one-way mirror, not a new trading authority or an automatic scheduled
sync. The existing remote paper ledger remains authoritative; refresh that ledger
before synchronization when using multiple devices. Zero-quantity watch entries
are excluded. A valid empty snapshot clears the mirror; a missing/invalid file or
an older source timestamp leaves it untouched. A row lock and transaction protect
the whole snapshot. Repeated identical imports create no duplicates. Costs use
DECIMAL, and unknown available quantity remains NULL rather than becoming sellable.
No quotes or profit estimates are fabricated from these cost records.
Keep the server bound to localhost: authentication is required before remote exposure.
Tests use an isolated in-memory H2 database; real MySQL connectivity and migrations
must also be checked by starting the application and calling its health endpoints.

Local verification on 2026-10-14: all three tests passed, packaging succeeded,
both HTTP endpoints returned UP, and migration V1 was applied to the real MySQL database.
This MySQL server reports version 26.7.0. Flyway logs an untested-version warning;
the initial migration was verified successfully. Future MySQL-specific migrations
must also be verified on the actual server rather than only on H2.
