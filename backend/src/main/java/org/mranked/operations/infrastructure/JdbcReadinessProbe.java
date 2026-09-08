package org.mranked.operations.infrastructure;

import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.operations.application.ReadinessProbe;
import org.mranked.operations.domain.ReadinessResult;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

@Component
public class JdbcReadinessProbe implements ReadinessProbe {
    static final String EXPECTED_SCHEMA_CONTRACT = "storage-publisher-final-2026-09-08-r3";
    static final String SCHEMA_CONTRACT_SQL =
            "SELECT contract_id FROM ops_and_admin.schema_contract";
    static final String CONNECTIVITY_SQL = "SELECT 1";
    static final String SOURCE_SCHEMA_SQL = """
            SELECT to_regclass('catalog.visible_platform_account') IS NOT NULL
               AND to_regclass('ingest.visible_publication') IS NOT NULL
               AND to_regclass('analytics.usable_publication_snapshot') IS NOT NULL
            """;
    private final JdbcClient jdbcClient;
    private final DatasetRevisionProvider revisionProvider;
    private final boolean sourceReadEnabled;

    public JdbcReadinessProbe(JdbcClient jdbcClient, DatasetRevisionProvider revisionProvider) {
        this(jdbcClient, revisionProvider, false);
    }

    @Autowired
    public JdbcReadinessProbe(
            JdbcClient jdbcClient,
            DatasetRevisionProvider revisionProvider,
            @Value("${mranked.source-read.enabled:false}") boolean sourceReadEnabled
    ) {
        this.jdbcClient = jdbcClient;
        this.revisionProvider = revisionProvider;
        this.sourceReadEnabled = sourceReadEnabled;
    }

    @Override
    public ReadinessResult probe() {
        Integer value = jdbcClient.sql(CONNECTIVITY_SQL).query(Integer.class).single();
        if (value == null || value != 1) {
            return ReadinessResult.down();
        }
        if (sourceReadEnabled) {
            Boolean sourceSchema = jdbcClient.sql(SOURCE_SCHEMA_SQL).query(Boolean.class).single();
            if (!Boolean.TRUE.equals(sourceSchema)) {
                return ReadinessResult.down();
            }
        } else {
            String contract = jdbcClient.sql(SCHEMA_CONTRACT_SQL).query(String.class).single();
            if (!EXPECTED_SCHEMA_CONTRACT.equals(contract)) {
                return ReadinessResult.down();
            }
        }
        DatasetRevision revision = revisionProvider.current();
        return revision.id() > 0
                ? ReadinessResult.up(revision.id())
                : ReadinessResult.down();
    }
}
