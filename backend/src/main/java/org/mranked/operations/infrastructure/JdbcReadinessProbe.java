package org.mranked.operations.infrastructure;

import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.operations.application.ReadinessProbe;
import org.mranked.operations.domain.ReadinessResult;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

@Component
public class JdbcReadinessProbe implements ReadinessProbe {
    static final String EXPECTED_SCHEMA_CONTRACT = "storage-publisher-final-2026-09-08-r2";
    static final String SCHEMA_CONTRACT_SQL =
            "SELECT contract_id FROM ops_and_admin.schema_contract";
    static final String CONNECTIVITY_SQL = "SELECT 1";
    private final JdbcClient jdbcClient;
    private final DatasetRevisionProvider revisionProvider;

    public JdbcReadinessProbe(JdbcClient jdbcClient, DatasetRevisionProvider revisionProvider) {
        this.jdbcClient = jdbcClient;
        this.revisionProvider = revisionProvider;
    }

    @Override
    public ReadinessResult probe() {
        Integer value = jdbcClient.sql(CONNECTIVITY_SQL).query(Integer.class).single();
        if (value == null || value != 1) {
            return ReadinessResult.down();
        }
        String contract = jdbcClient.sql(SCHEMA_CONTRACT_SQL).query(String.class).single();
        if (!EXPECTED_SCHEMA_CONTRACT.equals(contract)) {
            return ReadinessResult.down();
        }
        DatasetRevision revision = revisionProvider.current();
        return revision.id() > 0
                ? ReadinessResult.up(revision.id())
                : ReadinessResult.down();
    }
}
