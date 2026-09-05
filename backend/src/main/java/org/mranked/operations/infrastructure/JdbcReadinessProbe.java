package org.mranked.operations.infrastructure;

import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.operations.application.ReadinessProbe;
import org.mranked.operations.domain.ReadinessResult;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

@Component
public class JdbcReadinessProbe implements ReadinessProbe {
    static final String LATEST_CORE_READINESS_SQL = """
            WITH latest_revision AS (
                SELECT revision.id
                  FROM analytics.dataset_revision AS revision
                 ORDER BY revision.id DESC
                 LIMIT 1
            ), core_projection(projection_name) AS (VALUES
                ('publication_latest'),
                ('publication_hourly'),
                ('institution_daily_metrics'),
                ('institution_monthly_metrics'),
                ('institution_period_metrics'),
                ('comparison')
            )
            SELECT revision.id AS revision_id,
                   count(state.projection_name) AS ready_count
              FROM latest_revision AS revision
             CROSS JOIN core_projection AS core
              LEFT JOIN analytics.projection_state AS state
                ON state.projection_name = core.projection_name
               AND state.dataset_revision_id = revision.id
               AND state.status = 'ready'
             GROUP BY revision.id
            """;

    private final JdbcClient jdbcClient;
    private final DatasetRevisionProvider revisionProvider;

    public JdbcReadinessProbe(JdbcClient jdbcClient, DatasetRevisionProvider revisionProvider) {
        this.jdbcClient = jdbcClient;
        this.revisionProvider = revisionProvider;
    }

    @Override
    public ReadinessResult probe() {
        Integer value = jdbcClient.sql("SELECT 1").query(Integer.class).single();
        if (value == null || value != 1) {
            return ReadinessResult.down();
        }
        CoreReadiness core = jdbcClient.sql(LATEST_CORE_READINESS_SQL)
                .query((resultSet, rowNumber) -> new CoreReadiness(
                        resultSet.getLong("revision_id"),
                        resultSet.getInt("ready_count")
                ))
                .optional()
                .orElse(null);
        if (core == null || core.readyCount() != 6) {
            return ReadinessResult.down();
        }
        DatasetRevision revision = revisionProvider.current();
        return revision.id() > 0 && revision.id() == core.revisionId()
                ? ReadinessResult.up(revision.id())
                : ReadinessResult.down();
    }

    private record CoreReadiness(long revisionId, int readyCount) {
    }
}
