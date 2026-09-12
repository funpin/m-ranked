package org.mranked.testing;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.stream.Collectors;

/** Installs the one declarative database contract in a disposable test database. */
public final class FinalSchemaInstaller {
    public static final String CONTRACT = "storage-publisher-final-2026-09-08-r3";

    private FinalSchemaInstaller() {}

    public static void install(String url, String username, String password) throws Exception {
        Path root = Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        String sql = Files.readString(root.resolve("backend/src/main/resources/db/final-schema.sql"))
                .lines()
                .filter(line -> !line.startsWith("\\restrict ") && !line.startsWith("\\unrestrict "))
                .collect(Collectors.joining("\n", "", "\n"));
        try (var connection = DriverManager.getConnection(url, username, password);
             var statement = connection.createStatement()) {
            statement.execute("SET ROLE migration_owner");
            statement.execute(sql);
            try (var row = statement.executeQuery(
                    "SELECT contract_id FROM ops_and_admin.schema_contract")) {
                if (!row.next() || !CONTRACT.equals(row.getString(1)) || row.next()) {
                    throw new IllegalStateException("final schema contract was not installed");
                }
            }
        }
    }
}
