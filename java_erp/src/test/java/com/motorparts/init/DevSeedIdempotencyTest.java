package com.motorparts.init;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest
@ActiveProfiles("dev")
@Testcontainers(disabledWithoutDocker = true)
class DevSeedIdempotencyTest {

    @Container
    private static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0.40")
            .withDatabaseName("dev_seed")
            .withUsername("motorparts")
            .withPassword("motorparts-test");

    @DynamicPropertySource
    static void databaseProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", MYSQL::getJdbcUrl);
        registry.add("spring.datasource.username", MYSQL::getUsername);
        registry.add("spring.datasource.password", MYSQL::getPassword);
        registry.add("motorparts.seed.enabled", () -> true);
        registry.add("motorparts.order-expiry.enabled", () -> false);
    }

    @Autowired
    private DatabaseInitializer initializer;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void runningSeederTwiceDoesNotDuplicateOrOverwriteRows() {
        Map<String, Integer> before = counts();
        initializer.run(new DefaultApplicationArguments(new String[0]));
        Map<String, Integer> after = counts();

        assertEquals(before, after);
    }

    private Map<String, Integer> counts() {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (String table : new String[]{"user", "supplier", "part", "supplier_part", "inventory", "purchase_order", "order_detail", "logistics"}) {
            counts.put(table, jdbcTemplate.queryForObject("SELECT COUNT(*) FROM `" + table + "`", Integer.class));
        }
        return counts;
    }
}
