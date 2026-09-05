package org.mranked.admin.infrastructure;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.AdminQueryRepository;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;

final class UnavailableAdminQueryRepository implements AdminQueryRepository {
    @Override
    public List<AdminJobSummary> findCollectionJobs(String platform, String status, int limit) {
        throw new AdminDatabaseUnavailableException();
    }

    @Override
    public Optional<AdminJobDetail> findCollectionJob(UUID jobId, int accountResultLimit) {
        throw new AdminDatabaseUnavailableException();
    }

    @Override
    public Optional<PlatformAccountAdminState> findPlatformAccount(UUID accountId) {
        throw new AdminDatabaseUnavailableException();
    }
}
