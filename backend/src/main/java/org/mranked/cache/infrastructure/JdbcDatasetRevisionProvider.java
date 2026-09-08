package org.mranked.cache.infrastructure;

import java.time.Instant;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

@Repository
public class JdbcDatasetRevisionProvider implements DatasetRevisionProvider {
    static final String CURRENT_REVISION_SQL = """
            WITH core_projection(projection_name) AS (VALUES
                ('publication_latest'),
                ('publication_hourly'),
                ('institution_daily_metrics'),
                ('institution_monthly_metrics'),
                ('institution_period_metrics'),
                ('comparison'),
                ('publication_history')
            )
            SELECT revision.id, revision.committed_at
              FROM analytics.dataset_revision AS revision
             CROSS JOIN core_projection AS core
              LEFT JOIN analytics.projection_state AS state
                ON state.projection_name = core.projection_name
               AND state.dataset_revision_id = revision.id
               AND state.status = 'ready'
             GROUP BY revision.id, revision.committed_at
            HAVING count(state.projection_name) = 7
             ORDER BY revision.id DESC
             LIMIT 1
            """;
    static final String SOURCE_WATERMARK_SQL = """
            SELECT completed_at
              FROM ingest.collection_run
             WHERE completed_at IS NOT NULL
               AND status IN ('succeeded', 'partial')
               AND collector_version NOT LIKE 'sqlite-bridge/%'
             ORDER BY completed_at DESC, id DESC
             LIMIT 1
            """;

    private final JdbcClient jdbcClient;
    private final boolean sourceReadEnabled;

    public JdbcDatasetRevisionProvider(JdbcClient jdbcClient) {
        this(jdbcClient, false);
    }

    @Autowired
    public JdbcDatasetRevisionProvider(
            JdbcClient jdbcClient,
            @Value("${mranked.source-read.enabled:false}") boolean sourceReadEnabled
    ) {
        this.jdbcClient = jdbcClient;
        this.sourceReadEnabled = sourceReadEnabled;
    }

    @Override
    public DatasetRevision current() {
        if (sourceReadEnabled) {
            return jdbcClient.sql(SOURCE_WATERMARK_SQL)
                    .query((resultSet, rowNumber) -> DatasetRevision.source(
                            resultSet.getObject("completed_at", java.time.OffsetDateTime.class).toInstant()
                    ))
                    .optional()
                    .orElseGet(() -> new DatasetRevision(0, Instant.EPOCH));
        }
        var published = jdbcClient.sql(CURRENT_REVISION_SQL)
                .query((resultSet, rowNumber) -> new DatasetRevision(
                        resultSet.getLong("id"),
                        resultSet.getObject("committed_at", java.time.OffsetDateTime.class).toInstant()
                ))
                .optional();
        return published.orElseGet(() -> new DatasetRevision(0, Instant.EPOCH));
    }
}
