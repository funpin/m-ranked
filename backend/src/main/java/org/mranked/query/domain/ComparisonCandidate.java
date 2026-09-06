package org.mranked.query.domain;

import java.util.UUID;

public record ComparisonCandidate(UUID selectionId, String selectionType, long selectionLegacyId,
                                  String selectionLabel, UUID institutionId, String canonicalName, String selectionDescription) {}
