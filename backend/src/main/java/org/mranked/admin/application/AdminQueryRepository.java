package org.mranked.admin.application;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;

public interface AdminQueryRepository {
    List<AdminJobSummary> findCollectionJobs(String platform, String status, int limit);

    Optional<AdminJobDetail> findCollectionJob(UUID jobId, int accountResultLimit);

    Optional<PlatformAccountAdminState> findPlatformAccount(UUID accountId);
}
