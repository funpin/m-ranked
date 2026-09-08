package org.mranked.analysis.application;

import java.util.Optional;
import java.util.UUID;

public interface AnalysisQueryPort {
    Optional<UUID> resolvePublication(String id, String legacyType);
    AnalysisSnapshot load(UUID publicationId, int limit, UUID after);
}
