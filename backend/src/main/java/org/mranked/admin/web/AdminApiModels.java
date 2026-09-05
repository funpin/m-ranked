package org.mranked.admin.web;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.mranked.admin.application.SetPlatformAccountEnabledResult;
import org.mranked.admin.domain.AdminAccountResult;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;

final class AdminApiModels {
    private AdminApiModels() {
    }

    record Csrf(String headerName, String parameterName, String token) {
    }

    record JobPage(List<Job> items) {
        JobPage {
            items = List.copyOf(items);
        }
    }

    record Job(
            UUID jobId,
            String kind,
            String platform,
            Instant scheduledAt,
            Instant startedAt,
            Instant completedAt,
            String status,
            int accountCount,
            int errorCount,
            UUID correlationId
    ) {
    }

    record AccountResult(
            long resultId,
            UUID platformAccountId,
            Instant startedAt,
            Instant completedAt,
            String status,
            int discoveredCount,
            int snapshotCount,
            String sanitizedErrorCode
    ) {
    }

    record JobDetail(
            Job job,
            List<AccountResult> accountResults,
            boolean accountResultsTruncated
    ) {
        JobDetail {
            accountResults = List.copyOf(accountResults);
        }
    }

    record SetEnabledRequest(Boolean enabled, Long expectedRowVersion) {
    }

    record PlatformAccountState(
            UUID accountId,
            String platform,
            boolean enabled,
            long rowVersion,
            Instant updatedAt
    ) {
    }

    record SetEnabledResponse(
            PlatformAccountState account,
            boolean changed,
            Long datasetRevision,
            UUID correlationId,
            String outcome
    ) {
    }

    static JobPage jobs(List<AdminJobSummary> source) {
        return new JobPage(source.stream().map(AdminApiModels::job).toList());
    }

    static JobDetail jobDetail(AdminJobDetail source) {
        return new JobDetail(
                job(source.job()),
                source.accountResults().stream().map(AdminApiModels::accountResult).toList(),
                source.accountResultsTruncated()
        );
    }

    static PlatformAccountState platformAccount(PlatformAccountAdminState source) {
        return account(source);
    }

    static SetEnabledResponse enabled(
            SetPlatformAccountEnabledResult source,
            UUID correlationId
    ) {
        return new SetEnabledResponse(
                account(source.account()),
                source.outcome() == org.mranked.admin.application.SetPlatformAccountEnabledOutcome.UPDATED,
                source.datasetRevision(),
                correlationId,
                source.outcome().name().toLowerCase(java.util.Locale.ROOT)
        );
    }

    private static Job job(AdminJobSummary source) {
        return new Job(
                source.jobId(), "collection", source.platform(), source.scheduledAt(),
                source.startedAt(), source.completedAt(), source.status(), source.accountCount(),
                source.errorCount(), source.correlationId()
        );
    }

    private static AccountResult accountResult(AdminAccountResult source) {
        return new AccountResult(
                source.resultId(), source.platformAccountId(), source.startedAt(),
                source.completedAt(), source.status(), source.discoveredCount(),
                source.snapshotCount(), source.sanitizedErrorCode()
        );
    }

    private static PlatformAccountState account(PlatformAccountAdminState source) {
        return new PlatformAccountState(
                source.accountId(), source.platform(), source.enabled(), source.rowVersion(), source.updatedAt()
        );
    }
}
