package org.mranked.admin.application;

import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;
import org.springframework.stereotype.Service;

@Service
public class AdminService {
    private static final Set<String> PLATFORMS = Set.of("", "telegram", "vk", "max", "rutube");
    private static final Set<String> RUN_STATUSES = Set.of(
            "", "pending", "running", "succeeded", "partial", "failed", "skipped", "cancelled"
    );

    private final AdminQueryRepository queryRepository;
    private final AdminCommandRepository commandRepository;

    public AdminService(
            AdminQueryRepository queryRepository,
            AdminCommandRepository commandRepository
    ) {
        this.queryRepository = queryRepository;
        this.commandRepository = commandRepository;
    }

    public List<AdminJobSummary> collectionJobs(String platform, String status, int limit) {
        String normalizedPlatform = normalizedFilter(platform, "platform", PLATFORMS);
        String normalizedStatus = normalizedFilter(status, "status", RUN_STATUSES);
        if (limit < 1 || limit > 100) {
            throw new IllegalArgumentException("limit must be between 1 and 100");
        }
        return queryRepository.findCollectionJobs(normalizedPlatform, normalizedStatus, limit);
    }

    public AdminJobDetail collectionJob(UUID jobId, int accountResultLimit) {
        if (jobId == null) {
            throw new IllegalArgumentException("job id is required");
        }
        if (accountResultLimit < 1 || accountResultLimit > 200) {
            throw new IllegalArgumentException("account result limit must be between 1 and 200");
        }
        return queryRepository.findCollectionJob(jobId, accountResultLimit)
                .orElseThrow(() -> new AdminResourceNotFoundException(
                        "Collection job was not found"
                ));
    }

    public PlatformAccountAdminState platformAccount(UUID accountId) {
        if (accountId == null) {
            throw new IllegalArgumentException("account id is required");
        }
        return queryRepository.findPlatformAccount(accountId)
                .orElseThrow(() -> new AdminResourceNotFoundException(
                        "Platform account was not found"
                ));
    }

    public SetPlatformAccountEnabledResult setPlatformAccountEnabled(
            UUID accountId,
            boolean enabled,
            long expectedRowVersion,
            String actor,
            UUID correlationId
    ) {
        if (accountId == null || correlationId == null) {
            throw new IllegalArgumentException("account and correlation identifiers are required");
        }
        if (expectedRowVersion < 0) {
            throw new IllegalArgumentException("expected row version cannot be negative");
        }
        String sanitizedActor = sanitizeActor(actor);
        SetPlatformAccountEnabledResult result = commandRepository.setPlatformAccountEnabled(
                new SetPlatformAccountEnabledCommand(
                        accountId, enabled, expectedRowVersion, sanitizedActor, correlationId
                )
        );
        return switch (result.outcome()) {
            case UPDATED, IDEMPOTENT -> result;
            case NOT_FOUND -> throw new AdminResourceNotFoundException(
                    "Platform account was not found"
            );
            case VERSION_CONFLICT -> throw new AdminOptimisticLockException();
        };
    }

    private static String normalizedFilter(String value, String name, Set<String> allowed) {
        String normalized = value == null ? "" : value.strip().toLowerCase(java.util.Locale.ROOT);
        if (!allowed.contains(normalized)) {
            throw new IllegalArgumentException("unsupported " + name);
        }
        return normalized;
    }

    static String sanitizeActor(String actor) {
        if (actor == null) {
            throw new IllegalArgumentException("authenticated actor is required");
        }
        String normalized = actor.strip();
        if (normalized.isEmpty() || normalized.length() > 200
                || normalized.codePoints().anyMatch(Character::isISOControl)) {
            throw new IllegalArgumentException("authenticated actor is invalid");
        }
        return normalized;
    }
}
