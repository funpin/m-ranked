package org.mranked.admin.domain;

import java.util.UUID;

public record CatalogCommandResult(String outcome, UUID targetId, Long legacyId, Long datasetRevision,
        Long rowVersion, UUID correlationId) { }
