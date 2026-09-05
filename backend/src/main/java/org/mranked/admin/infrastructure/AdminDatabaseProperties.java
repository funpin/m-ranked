package org.mranked.admin.infrastructure;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("mranked.admin.database")
public record AdminDatabaseProperties(
        boolean enabled,
        String url,
        String username,
        String password
) {
    void validateEnabledConfiguration() {
        if (!enabled) {
            return;
        }
        if (url == null || !url.startsWith("jdbc:postgresql://")) {
            throw new IllegalStateException("admin database URL must be an explicit PostgreSQL JDBC URL");
        }
        if (!"api_write_admin".equals(username)) {
            throw new IllegalStateException("admin database username must be api_write_admin");
        }
        if (password == null || password.isBlank()) {
            throw new IllegalStateException("admin database password must be configured");
        }
    }
}
