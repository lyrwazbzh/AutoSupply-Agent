package com.motorparts.config;

import lombok.RequiredArgsConstructor;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.MigrationInfoService;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

/**
 * Makes Flyway state explicit in the readiness group. Migration failures already
 * stop application startup; pending migrations also keep a running instance out
 * of service until its schema matches the packaged application.
 */
@Component("flywayHealthIndicator")
@RequiredArgsConstructor
public class FlywayHealthIndicator implements HealthIndicator {

    private final Flyway flyway;

    @Override
    public Health health() {
        try {
            MigrationInfoService info = flyway.info();
            MigrationInfo[] pending = info.pending();
            MigrationInfo current = info.current();
            if (pending.length > 0) {
                return Health.down()
                        .withDetail("pendingMigrations", pending.length)
                        .withDetail("currentVersion", current == null ? "none" : current.getVersion())
                        .build();
            }
            return Health.up()
                    .withDetail("currentVersion", current == null ? "none" : current.getVersion())
                    .build();
        } catch (RuntimeException exception) {
            return Health.down(exception).build();
        }
    }
}
