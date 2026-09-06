package org.mranked.operations.infrastructure;

import java.util.Map;
import javax.sql.DataSource;
import org.mranked.operations.application.HealthSnapshotSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Component
public final class JdbcHealthSnapshotSource implements HealthSnapshotSource {
    private final JdbcClient jdbc;
    private final ObjectMapper json;
    public JdbcHealthSnapshotSource(DataSource dataSource, ObjectMapper json) {
        var template=new org.springframework.jdbc.core.JdbcTemplate(dataSource);
        template.setQueryTimeout(3);template.setMaxRows(1);
        this.jdbc=JdbcClient.create(template);this.json=json;
    }
    public Map<String,Object> snapshot() {
        return json.readValue(jdbc.sql("SELECT ops_and_admin.public_health_snapshot()::text")
                .query(String.class).single(), new TypeReference<>() {});
    }
}
