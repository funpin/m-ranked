package org.mranked.cache.infrastructure;

import java.time.Instant;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcDatasetRevisionProvider implements DatasetRevisionProvider {
    static final String CURRENT_REVISION_SQL = """
            WITH core_projection(projection_name) AS (VALUES
                ('publication_latest'),
                ('publication_hourly'),
                ('institution_daily_metrics'),
                ('institution_monthly_metrics'),
                ('institution_period_metrics'),
                ('comparison')
            )
            SELECT revision.id, revision.committed_at
              FROM analytics.dataset_revision AS revision
             CROSS JOIN core_projection AS core
              LEFT JOIN analytics.projection_state AS state
                ON state.projection_name = core.projection_name
               AND state.dataset_revision_id = revision.id
               AND state.status = 'ready'
             GROUP BY revision.id, revision.committed_at
            HAVING count(state.projection_name) = 6
             ORDER BY revision.id DESC
             LIMIT 1
            """;

    private final JdbcClient jdbcClient;

    public JdbcDatasetRevisionProvider(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    public DatasetRevision current() {
        return jdbcClient.sql(CURRENT_REVISION_SQL)
                .query((resultSet, rowNumber) -> new DatasetRevision(
                        resultSet.getLong("id"),
                        resultSet.getObject("committed_at", java.time.OffsetDateTime.class).toInstant()
                ))
                .optional()
                .orElseGet(() -> new DatasetRevision(0, Instant.EPOCH));
    }
}
