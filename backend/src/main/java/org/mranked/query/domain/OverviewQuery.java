package org.mranked.query.domain;

import java.util.Set;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;

/**
 * Normalized controls for the legacy overview. Legacy HTML treats unsupported
 * sort/direction values as fallbacks, so normalization must happen before both
 * cache-key construction and SQL execution.
 */
public record OverviewQuery(
        Platform platform,
        PeriodKey period,
        String search,
        String sort,
        String direction
) {
    private static final Set<String> ALL_SORTS = Set.of(
            "name", "m_rating", "coverage", "accounts"
    );
    private static final Set<String> PLATFORM_SORTS = Set.of(
            "name", "subscribers", "posts", "views", "reactions",
            "median_reactions", "m_rating"
    );

    public OverviewQuery {
        if (platform == null || period == null) {
            throw new IllegalArgumentException("overview platform and period are required");
        }
        if (search == null || search.length() > 200) {
            throw new IllegalArgumentException("overview search must contain at most 200 characters");
        }
        if (!sortsFor(platform).contains(sort)) {
            throw new IllegalArgumentException("overview sort was not normalized");
        }
        if (!"asc".equals(direction) && !"desc".equals(direction)) {
            throw new IllegalArgumentException("overview direction was not normalized");
        }
    }

    public static OverviewQuery normalized(
            Platform platform,
            PeriodKey period,
            String search,
            String sort,
            String direction
    ) {
        Set<String> supportedSorts = sortsFor(platform);
        String fallbackSort = platform == Platform.ALL ? "m_rating" : "median_reactions";
        String normalizedSort = sort != null && supportedSorts.contains(sort) ? sort : fallbackSort;
        String normalizedDirection = "asc".equals(direction) || "desc".equals(direction)
                ? direction
                : "name".equals(normalizedSort) ? "asc" : "desc";
        return new OverviewQuery(
                platform,
                period,
                search == null ? "" : search.strip(),
                normalizedSort,
                normalizedDirection
        );
    }

    public boolean allPlatforms() {
        return platform == Platform.ALL;
    }

    private static Set<String> sortsFor(Platform platform) {
        if (platform == null) {
            return Set.of();
        }
        return platform == Platform.ALL ? ALL_SORTS : PLATFORM_SORTS;
    }
}
