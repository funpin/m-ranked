package org.mranked.operations.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class JdbcReadinessProbeTest {
    @Test
    void readinessPinsTheSingleFinalSchemaContract() {
        assertThat(JdbcReadinessProbe.CONNECTIVITY_SQL).isEqualTo("SELECT 1");
        assertThat(JdbcReadinessProbe.SCHEMA_CONTRACT_SQL)
                .isEqualTo("SELECT contract_id FROM ops_and_admin.schema_contract");
        assertThat(JdbcReadinessProbe.EXPECTED_SCHEMA_CONTRACT)
                .isEqualTo("storage-publisher-final-2026-09-08-r2");
    }
}
