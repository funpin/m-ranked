package org.mranked.admin.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.mranked.admin.application.AdminQueryRepository;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.domain.AdminAccountResult;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.CannotGetJdbcConnectionException;

public class JdbcAdminQueryRepository implements AdminQueryRepository {
    static final String COLLECTION_JOBS_SQL = """
            SELECT run.id,
                   run.platform::text AS platform,
                   run.scheduled_at,
                   run.started_at,
                   run.completed_at,
                   run.status::text AS status,
                   run.account_count,
                   run.error_count,
                   run.correlation_id
              FROM ingest.collection_run AS run
             WHERE (:platform = '' OR run.platform::text = :platform)
               AND (:status = '' OR run.status::text = :status)
             ORDER BY run.started_at DESC, run.id DESC
             LIMIT :limit
            """;

    static final String COLLECTION_JOB_SQL = """
            SELECT run.id,
                   run.platform::text AS platform,
                   run.scheduled_at,
                   run.started_at,
                   run.completed_at,
                   run.status::text AS status,
                   run.account_count,
                   run.error_count,
                   run.correlation_id
              FROM ingest.collection_run AS run
             WHERE run.id = :jobId
            """;

    static final String ACCOUNT_RESULTS_SQL = """
            SELECT result.id,
                   result.platform_account_id,
                   result.started_at,
                   result.completed_at,
                   result.status::text AS status,
                   result.discovered_count,
                   result.snapshot_count,
                   result.sanitized_error_code
              FROM ingest.collection_account_result AS result
             WHERE result.collection_run_id = :jobId
             ORDER BY result.started_at, result.id
             LIMIT :fetchLimit
            """;

    static final String PLATFORM_ACCOUNT_SQL = """
            SELECT account.id,
                   account.platform::text AS platform,
                   account.enabled,
                   account.row_version,
                   account.updated_at
              FROM catalog.platform_account AS account
             WHERE account.id = :accountId
            """;

    private final JdbcClient jdbcClient;

    public JdbcAdminQueryRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    public List<AdminJobSummary> findCollectionJobs(String platform, String status, int limit) {
        try {
            return jdbcClient.sql(COLLECTION_JOBS_SQL)
                    .param("platform", platform)
                    .param("status", status)
                    .param("limit", limit)
                    .query(JdbcAdminQueryRepository::mapJob)
                    .list();
        } catch (CannotGetJdbcConnectionException exception) {
            throw new AdminDatabaseUnavailableException();
        }
    }

    @Override
    public Optional<AdminJobDetail> findCollectionJob(UUID jobId, int accountResultLimit) {
        try {
            return findCollectionJobConnected(jobId, accountResultLimit);
        } catch (CannotGetJdbcConnectionException exception) {
            throw new AdminDatabaseUnavailableException();
        }
    }

    @Override
    public Optional<PlatformAccountAdminState> findPlatformAccount(UUID accountId) {
        try {
            return jdbcClient.sql(PLATFORM_ACCOUNT_SQL)
                    .param("accountId", accountId)
                    .query(JdbcAdminQueryRepository::mapPlatformAccount)
                    .optional();
        } catch (CannotGetJdbcConnectionException exception) {
            throw new AdminDatabaseUnavailableException();
        }
    }

    private Optional<AdminJobDetail> findCollectionJobConnected(
            UUID jobId,
            int accountResultLimit
    ) {
        Optional<AdminJobSummary> job = jdbcClient.sql(COLLECTION_JOB_SQL)
                .param("jobId", jobId)
                .query(JdbcAdminQueryRepository::mapJob)
                .optional();
        if (job.isEmpty()) {
            return Optional.empty();
        }

        List<AdminAccountResult> fetched = jdbcClient.sql(ACCOUNT_RESULTS_SQL)
                .param("jobId", jobId)
                .param("fetchLimit", accountResultLimit + 1)
                .query(JdbcAdminQueryRepository::mapAccountResult)
                .list();
        boolean truncated = fetched.size() > accountResultLimit;
        List<AdminAccountResult> visible = new ArrayList<>(
                fetched.subList(0, Math.min(accountResultLimit, fetched.size()))
        );
        return Optional.of(new AdminJobDetail(job.orElseThrow(), visible, truncated));
    }

    private static AdminJobSummary mapJob(ResultSet row, int rowNumber) throws SQLException {
        return new AdminJobSummary(
                row.getObject("id", UUID.class),
                row.getString("platform"),
                instant(row, "scheduled_at"),
                instant(row, "started_at"),
                nullableInstant(row, "completed_at"),
                row.getString("status"),
                row.getInt("account_count"),
                row.getInt("error_count"),
                row.getObject("correlation_id", UUID.class)
        );
    }

    private static AdminAccountResult mapAccountResult(ResultSet row, int rowNumber) throws SQLException {
        return new AdminAccountResult(
                row.getLong("id"),
                row.getObject("platform_account_id", UUID.class),
                instant(row, "started_at"),
                nullableInstant(row, "completed_at"),
                row.getString("status"),
                row.getInt("discovered_count"),
                row.getInt("snapshot_count"),
                row.getString("sanitized_error_code")
        );
    }

    private static PlatformAccountAdminState mapPlatformAccount(
            ResultSet row,
            int rowNumber
    ) throws SQLException {
        return new PlatformAccountAdminState(
                row.getObject("id", UUID.class),
                row.getString("platform"),
                row.getBoolean("enabled"),
                row.getLong("row_version"),
                instant(row, "updated_at")
        );
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        return row.getObject(column, OffsetDateTime.class).toInstant();
    }

    private static Instant nullableInstant(ResultSet row, String column) throws SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
