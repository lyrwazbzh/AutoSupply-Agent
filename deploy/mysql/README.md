# Host MySQL migration runbook

This runbook preserves the existing `motorparts_db` while moving it into the
Compose-managed `mysql-data` volume. The helper never stops or deletes the old
database. Run it from a trusted maintenance host with MySQL 8 client tools.

```bash
export SOURCE_MYSQL_HOST=127.0.0.1
export SOURCE_MYSQL_PORT=3306
export SOURCE_MYSQL_USER=root
export SOURCE_MYSQL_PASSWORD='read-from-a-secret-manager'
export MYSQL_DATABASE=motorparts_db

bash deploy/mysql/migrate-host.sh preflight
# Stop writes to the old Java ERP here.
bash deploy/mysql/migrate-host.sh export
ALLOW_MYSQL_IMPORT=1 bash deploy/mysql/migrate-host.sh import
bash deploy/mysql/migrate-host.sh verify
python3 java_erp/scripts/smoke_harness.py --base-url http://java-erp.internal:8080
```

The export directory contains the SQL dump, its SHA-256, and source/target
metrics. Keep those files with the change record. Open write traffic only after
the metrics, invariant checks, Flyway readiness, and contract smoke all pass.
If validation fails, stop the new stack and point traffic back to the old
read-only database; do not delete either database during the observation
window.
