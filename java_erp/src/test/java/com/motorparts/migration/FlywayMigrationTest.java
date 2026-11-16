package com.motorparts.migration;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationVersion;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Testcontainers(disabledWithoutDocker = true)
class FlywayMigrationTest {

    @Container
    private static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0.40")
            .withDatabaseName("motorparts_test")
            .withUsername("motorparts")
            .withPassword("motorparts-test");

    @Test
    void migratesAnEmptyDatabaseToTheLatestVersion() throws Exception {
        Flyway flyway = flyway(MYSQL.getJdbcUrl());

        assertEquals(9, flyway.migrate().migrationsExecuted);
        assertTableExists(MYSQL.getJdbcUrl(), "purchase_order");
        assertTableExists(MYSQL.getJdbcUrl(), "erp_operation");
        assertTableExists(MYSQL.getJdbcUrl(), "security_role");
        assertTableExists(MYSQL.getJdbcUrl(), "business_audit_event");
        assertTableExists(MYSQL.getJdbcUrl(), "supplier_part");
        assertTableExists(MYSQL.getJdbcUrl(), "vehicle_model");
        assertTableExists(MYSQL.getJdbcUrl(), "part_fitment");
        assertTableExists(MYSQL.getJdbcUrl(), "inventory_transaction");
        assertTableExists(MYSQL.getJdbcUrl(), "replenishment_task");
        assertTableExists(MYSQL.getJdbcUrl(), "replenishment_inspection");
        assertTableExists(MYSQL.getJdbcUrl(), "purchase_return");
        assertTableExists(MYSQL.getJdbcUrl(), "order_expiry_task");
        assertTableNotExists(MYSQL.getJdbcUrl(), "customer");
        assertTableNotExists(MYSQL.getJdbcUrl(), "local_message");
        assertColumnExists(MYSQL.getJdbcUrl(), "purchase_order", "idempotency_key");
        assertColumnExists(MYSQL.getJdbcUrl(), "purchase_order", "supplier_id");
        assertEquals(0, flyway.migrate().migrationsExecuted);
    }

    @Test
    void baselinesAnExistingSchemaWithoutLosingRows() throws Exception {
        String schema = "legacy_case";
        try (Connection connection = DriverManager.getConnection(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement()) {
            statement.execute("CREATE DATABASE `" + schema + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci");
        }
        String legacyUrl = MYSQL.getJdbcUrl().replace("/motorparts_test?", "/" + schema + "?");

        Flyway.configure()
                .dataSource(legacyUrl, MYSQL.getUsername(), MYSQL.getPassword())
                .locations("classpath:db/migration")
                .target(MigrationVersion.fromVersion("1"))
                .load()
                .migrate();
        try (Connection connection = DriverManager.getConnection(
                legacyUrl, MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("INSERT INTO supplier(supplier_code,name) VALUES ('LEGACY-1','保留供应商')");
            statement.executeUpdate("INSERT INTO part(part_code,name,purchase_price,supplier_id) SELECT 'LEGACY-PART-1','保留零件',88.50,id FROM supplier WHERE supplier_code='LEGACY-1'");
            statement.executeUpdate("INSERT INTO `user`(username,password,real_name,role) VALUES ('legacy-user','$2a$10$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW','旧用户','purchase')");
            statement.execute("DROP TABLE flyway_schema_history");
        }

        Flyway migrated = flyway(legacyUrl);
        migrated.migrate();

        try (Connection connection = DriverManager.getConnection(
                legacyUrl, MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery(
                     "SELECT COUNT(*) FROM supplier WHERE supplier_code='LEGACY-1'")) {
            assertTrue(result.next());
            assertEquals(1, result.getInt(1));
        }
        assertColumnExists(legacyUrl, "purchase_order", "payload_hash");
        assertTableExists(legacyUrl, "order_expiry_task");
        assertTableExists(legacyUrl, "supplier_part");
        try (Connection connection = DriverManager.getConnection(
                legacyUrl, MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery(
                     "SELECT sp.purchase_price FROM supplier_part sp JOIN part p ON p.id=sp.part_id WHERE p.part_code='LEGACY-PART-1'")) {
            assertTrue(result.next());
            assertEquals("88.50", result.getBigDecimal(1).toPlainString());
        }
        try (Connection connection = DriverManager.getConnection(
                legacyUrl, MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery(
                     "SELECT password,password_hash FROM `user` WHERE username='legacy-user'")) {
            assertTrue(result.next());
            assertEquals("!", result.getString("password"));
            assertTrue(result.getString("password_hash").startsWith("{bcrypt}$2a$"));
        }
    }

    @Test
    void upgradesWhenHarnessTablesAndColumnsAlreadyExist() throws Exception {
        String schema = "legacy_harness_case";
        try (Connection connection = DriverManager.getConnection(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement()) {
            statement.execute("CREATE DATABASE `" + schema + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci");
        }
        String legacyUrl = MYSQL.getJdbcUrl().replace("/motorparts_test?", "/" + schema + "?");

        Flyway.configure()
                .dataSource(legacyUrl, MYSQL.getUsername(), MYSQL.getPassword())
                .locations("classpath:db/migration")
                .target(MigrationVersion.fromVersion("1"))
                .load()
                .migrate();
        try (Connection connection = DriverManager.getConnection(
                legacyUrl, MYSQL.getUsername(), MYSQL.getPassword());
             Statement statement = connection.createStatement()) {
            statement.execute("ALTER TABLE purchase_order ADD COLUMN idempotency_key varchar(191), ADD COLUMN payload_hash varchar(128), ADD UNIQUE KEY uk_idempotency_key(idempotency_key)");
            statement.execute("CREATE TABLE erp_operation (operation_id varchar(128) PRIMARY KEY, status varchar(32) NOT NULL, applied tinyint NOT NULL DEFAULT 0, result_json mediumtext, updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP)");
            statement.execute("CREATE TABLE order_idempotency (idempotency_key varchar(191) PRIMARY KEY, order_id bigint NOT NULL, payload_hash varchar(128) NOT NULL, status varchar(32) NOT NULL, create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP, update_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP)");
            statement.execute("INSERT INTO purchase_order(id,order_number,status) VALUES (1,'LEGACY-ORDER-1',1)");
            statement.execute("CREATE TABLE local_message (id bigint AUTO_INCREMENT PRIMARY KEY, msg_key varchar(191) NOT NULL UNIQUE, topic varchar(128) NOT NULL, payload text, status varchar(32) NOT NULL, deliver_at datetime NOT NULL, retry_count int NOT NULL DEFAULT 0, create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP, update_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP)");
            statement.execute("INSERT INTO local_message(msg_key,topic,payload,status,deliver_at) VALUES ('pending-order-expiry:1','order.pending.cancel','{\"orderId\":1}','PENDING',CURRENT_TIMESTAMP)");
            statement.execute("DROP TABLE flyway_schema_history");
        }

        Flyway migrated = flyway(legacyUrl);
        assertEquals(9, migrated.migrate().migrationsExecuted);
        assertEquals(0, migrated.migrate().migrationsExecuted);
        assertTableExists(legacyUrl, "order_expiry_task");
        assertTableNotExists(legacyUrl, "local_message");
        assertTableExists(legacyUrl, "purchase_return");
        assertColumnExists(legacyUrl, "purchase_order", "idempotency_key");
    }

    private static Flyway flyway(String url) {
        return Flyway.configure()
                .dataSource(url, MYSQL.getUsername(), MYSQL.getPassword())
                .locations("classpath:db/migration")
                .baselineOnMigrate(true)
                .baselineVersion(MigrationVersion.fromVersion("0"))
                .cleanDisabled(true)
                .load();
    }

    private static void assertTableExists(String url, String table) throws Exception {
        try (Connection connection = DriverManager.getConnection(url, MYSQL.getUsername(), MYSQL.getPassword());
             ResultSet tables = connection.getMetaData().getTables(connection.getCatalog(), null, table, null)) {
            assertTrue(tables.next(), "missing table " + table);
        }
    }

    private static void assertTableNotExists(String url, String table) throws Exception {
        try (Connection connection = DriverManager.getConnection(url, MYSQL.getUsername(), MYSQL.getPassword());
             ResultSet tables = connection.getMetaData().getTables(connection.getCatalog(), null, table, null)) {
            assertTrue(!tables.next(), "unexpected table " + table);
        }
    }

    private static void assertColumnExists(String url, String table, String column) throws Exception {
        try (Connection connection = DriverManager.getConnection(url, MYSQL.getUsername(), MYSQL.getPassword());
             ResultSet columns = connection.getMetaData().getColumns(connection.getCatalog(), null, table, column)) {
            assertTrue(columns.next(), "missing column " + table + "." + column);
        }
    }
}
