# Java ERP

Spring Boot 3.1.10 procurement ERP used by Agent-Harness. It is the production
ERP implementation; the Python Mock is retained only for isolated contract
tests. Existing REST paths and the `{code,message,data}` response envelope are
kept compatible with MCP.

## Toolchain

- Temurin JDK 17 (the build accepts JDK 17 through 21)
- Maven Wrapper 3.9.9
- MySQL 8.0
- Spring Boot 3.1.10 / MyBatis Plus 3.5.3.1
- Flyway schema migrations

Use the checked-in wrapper so local and CI builds use the same Maven version:

```bash
# Linux/macOS/CI
./mvnw -B -ntp verify

# Windows
mvnw.cmd -B verify
```

JaCoCo writes its HTML report to `target/site/jacoco`. MySQL integration tests
use Testcontainers; pure unit tests do not require a running database.

## Configuration

No database password is stored in application configuration. Supply:

| Variable | Purpose |
|---|---|
| `ERP_DB_HOST` | MySQL hostname; `mysql` in Compose |
| `ERP_DB_PORT` | MySQL port, normally `3306` |
| `MYSQL_DATABASE` | database name, normally `motorparts_db` |
| `MYSQL_USER` | application database user |
| `MYSQL_PASSWORD` | application database password |
| `MYSQL_ROOT_PASSWORD` | MySQL container initialization only |

Profiles:

- default: no password, development seed disabled;
- `dev`: local MySQL; seed can be enabled explicitly with
  `MOTORPARTS_SEED_ENABLED=true`;
- `compose`: connects to `mysql:3306`, seed always disabled;
- `test` and production: seed disabled.

Redis is enabled in the default topology only for part/supplier query caches,
login rate limiting and recent/frequent catalog access. The M1 quotation and
fitment tables are not cached. MySQL CAS remains the inventory correctness
boundary. Pending-order expiry is a local MySQL-backed scheduled task; the ERP
does not depend on a message broker.

## Local run

Create an empty MySQL database and application user outside the application,
then export the connection variables. Flyway creates or upgrades all tables.

```bash
export ERP_DB_HOST=127.0.0.1
export ERP_DB_PORT=3306
export MYSQL_DATABASE=motorparts_db
export MYSQL_USER=motorparts
export MYSQL_PASSWORD='from-a-secret-manager'

./mvnw spring-boot:run
```

On Windows, set the same environment variables and run
`mvnw.cmd spring-boot:run`.

Useful internal endpoints:

- readiness: `GET /actuator/health/readiness` (database + Flyway)
- liveness: `GET /actuator/health/liveness`
- metrics: `GET /actuator/prometheus`
- OpenAPI UI: `GET /swagger-ui.html`

## Database ownership

Database structure is changed only by versioned scripts in
`src/main/resources/db/migration`:

- `V1__baseline_schema.sql`: base ERP tables, indexes, constraints and views;
- `V2__harness_write_governance.sql`: operation replay, order idempotency and
  local-message governance;
- `V3__security_rbac.sql`: unified users, roles, permissions and refresh sessions;
- `V4__business_audit.sql`: append-only business audit events;
- `V5__procurement_catalog.sql`: multi-supplier quotations, motorcycle models,
  part fitments, permission grants and compatibility-data backfill.
- `V6__inventory_ledger_and_receiving.sql`: immutable inventory movements,
  atomic whole-order receiving and the related RBAC grants.
- `V7__replenishment_tasks.sql`: replenishment tasks and inspection runs,
  one-active-task enforcement, purchase-order supplier linkage and RBAC grants.
- `V8__purchase_returns.sql`: lightweight purchase returns, return reasons,
  confirmation idempotency and related RBAC grants.

Flyway uses `baseline-on-migrate=true` and `baseline-version=0`. A new database
runs every versioned migration. A non-empty legacy database is baselined at 0 and then upgraded
without deleting rows. Migration failure prevents application startup.

The old runtime DDL initializer and compatibility migration runner have been
removed. The `dev` data loader only inserts deterministic fixtures using natural
keys and `INSERT IGNORE`; it never clears or overwrites existing rows.

For moving a host `motorparts_db` into the Compose `mysql-data` volume, follow
[`deploy/mysql/README.md`](../deploy/mysql/README.md). The workflow records a
consistent dump, SHA-256, row counts, primary-key ranges, order totals and
inventory totals before opening write traffic.

## MCP-facing contract

| Tool group | Main paths |
|---|---|
| suppliers | `/api/suppliers/search`, `/page`, `/get/{id}`, `/create`, `/update-status/{id}` |
| parts | `/api/parts/get/{id}`, `/search`, `/supplier/{id}`, `/page`, `/create` |
| supplier quotations | `/api/parts/{id}/supplier-options` |
| vehicle models / fitments | `/api/vehicle-models/search`, `/api/parts/{id}/fitments`, `/api/parts/search-by-vehicle` |
| orders | `/api/orders/create`, `/update/{id}`, `/{id}/receive`, `/page`, `/get/{id}`, `/search-details`, `/statistics`, `/update-status/{id}`, `/by-idempotency` |
| inventory | `/api/inventory/warning`, `/page`, `/check`, `/inbound`, `/outbound`, `/get/{id}`, `/transactions/page`, `/transactions/{id}` |
| replenishment | `/api/replenishment/page`, `/create`, `/inspect`, `/{id}/create-order`, `/{id}/complete`, `/{id}/cancel` |
| purchase returns | `/api/purchase-returns/page`, `/create`, `/{id}/confirm` |

Writes accept `operationId` and `X-Operation-Id`. A completed operation can be
queried at `/api/operations/{operationId}` and a replay returns the original
response without executing the business service again. Order idempotency is
available through `idempotencyKey` and `/api/orders/by-idempotency`.

Supplier status is `1=active, 2=terminated, 3=pending`; historical value `0` is
normalized to `2`. New orders always start at pending (`1`); status `0` is invalid.
Business errors continue to use HTTP 200 with the error code in the response
body where required by the existing MCP adapter.

M1 catalog writes require `erp:supplier-part:write`, `erp:vehicle:write` or
`erp:fitment:write`; corresponding `:read` permissions protect queries. Setting
a supplier quotation as default also updates the legacy `part.supplier_id` and
`part.purchase_price` fields in the same MySQL transaction. New parts with a
legacy default supplier automatically receive a matching `supplier_part` row.

M2 routes manual inbound/outbound and `POST /api/orders/{id}/receive` through
transactional command services. Inventory quantity, the `inventory_transaction`
ledger, order status/actual arrival date and operation replay result commit or
roll back together in MySQL. Receiving is intentionally whole-order only and is
allowed only from status `3` (purchasing); it records one `PURCHASE_RECEIPT`
movement per part and then changes the order to status `4`. Redis is not used in
this correctness path. The generic status endpoint no longer accepts `3 -> 4`,
so an order cannot be marked stored without creating the matching stock ledger.

M3 adds deterministic replenishment rather than LLM-generated quantities. The
daily scheduled inspection and `POST /api/replenishment/inspect` both calculate
`max(safetyStock * multiplier - currentQuantity, minimumOrderQuantity)`. A
generated-column unique key permits only one `PENDING`/`ORDER_CREATED` task per
part, including under concurrent inspections. `POST /api/replenishment/{id}/create-order`
validates an active quotation, creates a
single-part purchase order and links it in one transaction. Receiving that order
automatically completes the task. Configure the feature with
`ERP_REPLENISHMENT_ENABLED`, `ERP_REPLENISHMENT_CRON`,
`ERP_REPLENISHMENT_ZONE` and `ERP_REPLENISHMENT_TARGET_MULTIPLIER`.

M4 adds lightweight purchase returns for stored purchase orders. Creating a
return records a `PENDING` request against one original order line; confirming
it rechecks the cumulative returned quantity, deducts stock with the MySQL CAS,
writes a `PURCHASE_RETURN` inventory movement and changes the request to
`CONFIRMED` in one transaction. The source order must remain in status `4`, and
confirmed returns can never exceed its originally received quantity. Redis is
not involved. This milestone deliberately excludes quality-inspection,
supplier settlement, refund and complex after-sales workflows.

## Smoke and invariants

With Java ERP running and at least one part present:

```bash
python scripts/smoke_harness.py --base-url http://localhost:8080
```

For an empty CI database, `--bootstrap-fixture` creates one explicit test
supplier and part. It does not enable the development Seeder. Windows users can
run the compatibility entrypoint:

```powershell
powershell -File scripts/smoke_harness.ps1 -BaseUrl http://localhost:8080
```

The smoke covers readiness, supplier/part queries, idempotent order creation,
inventory inbound/outbound replay and operation lookup. Run
`docs/verify_invariants.sql` afterward for database invariants.

## Container deployment

The multi-stage `Dockerfile` builds with Maven 3.9.9 + Temurin 17 and runs on
`eclipse-temurin:17-jre-jammy` as the non-root `erp` user. The service is only on
the internal Compose `data` network and is not exposed through Nginx in phases
0-1.

Default dependency order is:

```text
mysql healthy -> java-erp ready -> mcp healthy -> backend/frontend -> nginx
```

Production backups include both PostgreSQL and MySQL; restore verification is
performed against disposable database containers before a backup is accepted.
