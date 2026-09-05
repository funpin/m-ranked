package org.mranked.query.domain;

import java.util.LinkedHashSet;
import java.util.List;

public record ComparisonSelection(
        ComparisonSelectionType type,
        List<Long> legacyIds
) {
    public static final int MAX_INSTITUTIONS = 50;

    public ComparisonSelection {
        if (type == null) {
            throw new InvalidComparisonSelectionException("Comparison selection type is required");
        }
        if (legacyIds == null) {
            throw new InvalidComparisonSelectionException("Comparison selection is required");
        }
        if (legacyIds.size() > MAX_INSTITUTIONS) {
            throw new InvalidComparisonSelectionException(
                    "At most " + MAX_INSTITUTIONS + " " + type.entityValue()
                            + " IDs may be selected"
            );
        }
        LinkedHashSet<Long> unique = new LinkedHashSet<>();
        for (Long legacyId : legacyIds) {
            if (legacyId == null || legacyId <= 0) {
                throw new InvalidComparisonSelectionException(
                        type.entityValue() + " IDs must be positive integers"
                );
            }
            unique.add(legacyId);
        }
        legacyIds = List.copyOf(unique);
    }

    public static ComparisonSelection defaults(ComparisonSelectionType type) {
        return new ComparisonSelection(type, List.of());
    }

    public boolean explicit() {
        return !legacyIds.isEmpty();
    }
}
