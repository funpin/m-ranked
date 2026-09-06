package org.mranked.admin.domain;

import java.util.List;
import java.util.UUID;

public record ManagedInstitution(UUID id, long legacyId, String name, String shortName, long rowVersion,
        List<ManagedAccount> accounts, Long nextAccountAfter, java.util.Map<String,OfficialRating> officialRatings) {
    public ManagedInstitution { accounts=List.copyOf(accounts); }
}
