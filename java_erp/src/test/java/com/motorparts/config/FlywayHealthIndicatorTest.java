package com.motorparts.config;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.MigrationInfoService;
import org.junit.jupiter.api.Test;
import org.springframework.boot.actuate.health.Status;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class FlywayHealthIndicatorTest {

    @Test
    void readinessIsUpWhenNoMigrationsArePending() {
        Flyway flyway = mock(Flyway.class);
        MigrationInfoService info = mock(MigrationInfoService.class);
        when(flyway.info()).thenReturn(info);
        when(info.pending()).thenReturn(new MigrationInfo[0]);

        assertEquals(Status.UP, new FlywayHealthIndicator(flyway).health().getStatus());
    }

    @Test
    void readinessIsDownWhenMigrationIsPending() {
        Flyway flyway = mock(Flyway.class);
        MigrationInfoService info = mock(MigrationInfoService.class);
        when(flyway.info()).thenReturn(info);
        when(info.pending()).thenReturn(new MigrationInfo[]{mock(MigrationInfo.class)});

        assertEquals(Status.DOWN, new FlywayHealthIndicator(flyway).health().getStatus());
    }
}
