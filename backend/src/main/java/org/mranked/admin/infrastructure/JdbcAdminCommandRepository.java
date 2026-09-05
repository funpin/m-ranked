package org.mranked.admin.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import org.mranked.admin.application.AdminCommandRepository;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.SetPlatformAccountEnabledCommand;
import org.mranked.admin.application.SetPlatformAccountEnabledOutcome;
import org.mranked.admin.application.SetPlatformAccountEnabledResult;
import org.mranked.admin.domain.PlatformAccountAdminState;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.CannotGetJdbcConnectionException;
import org.springframework.transaction.support.TransactionOperations;

public class JdbcAdminCommandRepository implements AdminCommandRepository {
    static final String LOCK_ACCOUNT_SQL = """
            SELECT account.id,
                   account.platform::text AS platform,
                   account.enabled,
                   account.row_version,
                   account.updated_at
              FROM catalog.platform_account AS account
             WHERE account.id = :accountId
             FOR UPDATE
            """;

    static final String UPDATE_ACCOUNT_SQL = """
            UPDATE catalog.platform_account
               SET enabled = :enabled,
                   row_version = row_version + 1,
                   updated_at = transaction_timestamp()
             WHERE id = :accountId
               AND row_version = :expectedRowVersion
            RETURNING id,
                      platform::text AS platform,
                      enabled,
                      row_version,
                      updated_at
            """;

    static final String INSERT_REVISION_SQL = """
            INSERT INTO analytics.dataset_revision (cause, correlation_id)
            VALUES ('configuration', :correlationId)
            RETURNING id
            """;

    static final String REBUILD_PROJECTIONS_SQL = """
            SELECT analytics.rebuild_core_projections(:datasetRevision)
            """;

    static final String INSERT_OUTBOX_SQL = """
            INSERT INTO ops_and_admin.outbox_event (
                dataset_revision_id,
                event_type,
                aggregate_type,
                aggregate_id,
                affected_tags,
                payload
            )
            VALUES (
                :datasetRevision,
                'platform_account.enabled_changed',
                'platform_account',
                CAST(:accountId AS text),
                ARRAY[CAST(:affectedTag AS text)],
                jsonb_build_object(
                    'enabled', CAST(:enabled AS boolean),
                    'rowVersion', CAST(:rowVersion AS bigint)
                )
            )
            """;

    static final String INSERT_STATE_AUDIT_SQL = """
            INSERT INTO ops_and_admin.audit_log (
                subject,
                action,
                target_type,
                target_id,
                correlation_id,
                before_state,
                after_state,
                outcome
            )
            VALUES (
                :actor,
                'platform_account.set_enabled',
                'platform_account',
                :accountId,
                :correlationId,
                jsonb_build_object(
                    'enabled', CAST(:beforeEnabled AS boolean),
                    'rowVersion', CAST(:beforeRowVersion AS bigint)
                ),
                jsonb_build_object(
                    'enabled', CAST(:afterEnabled AS boolean),
                    'rowVersion', CAST(:afterRowVersion AS bigint)
                ),
                :outcome
            )
            """;

    static final String INSERT_MISSING_AUDIT_SQL = """
            INSERT INTO ops_and_admin.audit_log (
                subject,
                action,
                target_type,
                target_id,
                correlation_id,
                before_state,
                after_state,
                outcome
            )
            VALUES (
                :actor,
                'platform_account.set_enabled',
                'platform_account',
                :accountId,
                :correlationId,
                NULL,
                NULL,
                'not_found'
            )
            """;

    private final JdbcClient jdbcClient;
    private final TransactionOperations transactions;

    public JdbcAdminCommandRepository(JdbcClient jdbcClient, TransactionOperations transactions) {
        this.jdbcClient = jdbcClient;
        this.transactions = transactions;
    }

    @Override
    public SetPlatformAccountEnabledResult setPlatformAccountEnabled(
            SetPlatformAccountEnabledCommand command
    ) {
        try {
            return Objects.requireNonNull(transactions.execute(status -> execute(command)));
        } catch (CannotGetJdbcConnectionException exception) {
            throw new AdminDatabaseUnavailableException();
        }
    }

    private SetPlatformAccountEnabledResult execute(SetPlatformAccountEnabledCommand command) {
        Optional<PlatformAccountAdminState> existing = jdbcClient.sql(LOCK_ACCOUNT_SQL)
                .param("accountId", command.accountId())
                .query(JdbcAdminCommandRepository::mapAccount)
                .optional();
        if (existing.isEmpty()) {
            insertMissingAudit(command);
            return new SetPlatformAccountEnabledResult(
                    SetPlatformAccountEnabledOutcome.NOT_FOUND, null, null
            );
        }

        PlatformAccountAdminState before = existing.orElseThrow();
        if (before.enabled() == command.enabled()) {
            insertStateAudit(command, before, before, "idempotent");
            return new SetPlatformAccountEnabledResult(
                    SetPlatformAccountEnabledOutcome.IDEMPOTENT, before, null
            );
        }
        if (before.rowVersion() != command.expectedRowVersion()) {
            insertStateAudit(command, before, before, "version_conflict");
            return new SetPlatformAccountEnabledResult(
                    SetPlatformAccountEnabledOutcome.VERSION_CONFLICT, before, null
            );
        }

        PlatformAccountAdminState updated = jdbcClient.sql(UPDATE_ACCOUNT_SQL)
                .param("accountId", command.accountId())
                .param("enabled", command.enabled())
                .param("expectedRowVersion", command.expectedRowVersion())
                .query(JdbcAdminCommandRepository::mapAccount)
                .optional()
                .orElseThrow(() -> new IllegalStateException(
                        "platform account optimistic update did not return a row"
                ));
        long revision = jdbcClient.sql(INSERT_REVISION_SQL)
                .param("correlationId", command.correlationId())
                .query(Long.class)
                .single();
        jdbcClient.sql(REBUILD_PROJECTIONS_SQL)
                .param("datasetRevision", revision)
                .query((row, rowNumber) -> row.getString(1))
                .single();
        jdbcClient.sql(INSERT_OUTBOX_SQL)
                .param("datasetRevision", revision)
                .param("accountId", command.accountId())
                .param("affectedTag", "platform-account:" + command.accountId())
                .param("enabled", updated.enabled())
                .param("rowVersion", updated.rowVersion())
                .update();
        insertStateAudit(command, before, updated, "succeeded");
        return new SetPlatformAccountEnabledResult(
                SetPlatformAccountEnabledOutcome.UPDATED, updated, revision
        );
    }

    private void insertStateAudit(
            SetPlatformAccountEnabledCommand command,
            PlatformAccountAdminState before,
            PlatformAccountAdminState after,
            String outcome
    ) {
        jdbcClient.sql(INSERT_STATE_AUDIT_SQL)
                .param("actor", command.actor())
                .param("accountId", command.accountId())
                .param("correlationId", command.correlationId())
                .param("beforeEnabled", before.enabled())
                .param("beforeRowVersion", before.rowVersion())
                .param("afterEnabled", after.enabled())
                .param("afterRowVersion", after.rowVersion())
                .param("outcome", outcome)
                .update();
    }

    private void insertMissingAudit(SetPlatformAccountEnabledCommand command) {
        jdbcClient.sql(INSERT_MISSING_AUDIT_SQL)
                .param("actor", command.actor())
                .param("accountId", command.accountId())
                .param("correlationId", command.correlationId())
                .update();
    }

    private static PlatformAccountAdminState mapAccount(ResultSet row, int rowNumber)
            throws SQLException {
        return new PlatformAccountAdminState(
                row.getObject("id", UUID.class),
                row.getString("platform"),
                row.getBoolean("enabled"),
                row.getLong("row_version"),
                row.getObject("updated_at", OffsetDateTime.class).toInstant()
        );
    }
}
