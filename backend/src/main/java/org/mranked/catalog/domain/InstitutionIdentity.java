package org.mranked.catalog.domain;

import java.util.UUID;

public record InstitutionIdentity(
        UUID id,
        long legacyId,
        String canonicalName,
        String shortName
) {
}
