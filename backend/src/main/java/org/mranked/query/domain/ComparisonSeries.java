package org.mranked.query.domain;

import java.util.List;
import java.util.UUID;
import org.mranked.catalog.domain.InstitutionIdentity;

public record ComparisonSeries(
        UUID selectionId,
        ComparisonSelectionType selectionType,
        long selectionLegacyId,
        String selectionLabel,
        InstitutionIdentity institution,
        int primaryCohortSize,
        int engagementCohortSize,
        List<ComparisonPoint> points,
        List<ComparisonPoint> engagementPoints
) {
    public ComparisonSeries {
        if (selectionId == null || selectionType == null || selectionLegacyId <= 0
                || selectionLabel == null || selectionLabel.isBlank()) {
            throw new IllegalArgumentException("comparison series selection identity is invalid");
        }
        if (primaryCohortSize < 0 || engagementCohortSize < 0) {
            throw new IllegalArgumentException("comparison series cohort sizes must be non-negative");
        }
        points = List.copyOf(points);
        engagementPoints = List.copyOf(engagementPoints);
    }
}
