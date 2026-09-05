package org.mranked.query.domain;

import java.util.Set;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;

/**
 * Normalized legacy activity-rating controls. The public HTML contract accepts
 * unknown sort keys and directions, so normalization happens before a cache key
 * or SQL parameter is built instead of rejecting those requests.
 */
public record ActivityRatingQuery(
        Platform platform,
        PeriodKey period,
        String channelSort,
        String channelDirection,
        String postSort,
        String postDirection
) {
    private static final Set<String> TELEGRAM_CHANNEL_SORTS = Set.of(
            "average", "total", "engagement", "subscribers"
    );
    private static final Set<String> PLATFORM_CHANNEL_SORTS = Set.of(
            "average", "total", "engagement", "views", "subscribers"
    );
    private static final Set<String> TELEGRAM_POST_SORTS = Set.of(
            "reactions", "subscriber_share", "view_share", "views"
    );
    private static final Set<String> PLATFORM_POST_SORTS = Set.of(
            "reactions", "views", "comments", "interactions", "view_share"
    );
    private static final Set<String> VK_POST_SORTS = Set.of(
            "reactions", "views", "comments", "shares", "interactions", "view_share"
    );

    public ActivityRatingQuery {
        if (platform != Platform.TELEGRAM && platform != Platform.VK
                && platform != Platform.RUTUBE) {
            throw new IllegalArgumentException("activity rating supports telegram, vk and rutube");
        }
        if (period == null) {
            throw new IllegalArgumentException("rating period is required");
        }
        Set<String> channelSorts = platform == Platform.TELEGRAM
                ? TELEGRAM_CHANNEL_SORTS : PLATFORM_CHANNEL_SORTS;
        Set<String> postSorts = switch (platform) {
            case TELEGRAM -> TELEGRAM_POST_SORTS;
            case VK -> VK_POST_SORTS;
            case RUTUBE -> PLATFORM_POST_SORTS;
            default -> throw new IllegalArgumentException("unsupported rating platform");
        };
        if (!channelSorts.contains(channelSort) || !postSorts.contains(postSort)) {
            throw new IllegalArgumentException("rating sort was not normalized");
        }
        if (!isDirection(channelDirection) || !isDirection(postDirection)) {
            throw new IllegalArgumentException("rating direction was not normalized");
        }
    }

    public static ActivityRatingQuery normalized(
            Platform platform,
            PeriodKey period,
            String channelSort,
            String channelDirection,
            String postSort,
            String postDirection
    ) {
        boolean telegram = platform == Platform.TELEGRAM;
        Set<String> channelSorts = telegram ? TELEGRAM_CHANNEL_SORTS : PLATFORM_CHANNEL_SORTS;
        Set<String> postSorts = switch (platform) {
            case TELEGRAM -> TELEGRAM_POST_SORTS;
            case VK -> VK_POST_SORTS;
            case RUTUBE -> PLATFORM_POST_SORTS;
            default -> Set.of();
        };
        String normalizedChannelSort = channelSorts.contains(channelSort)
                ? channelSort : "engagement";
        String normalizedPostSort = postSorts.contains(postSort)
                ? postSort : telegram ? "reactions" : "view_share";
        return new ActivityRatingQuery(
                platform,
                period,
                normalizedChannelSort,
                normalizeDirection(channelDirection),
                normalizedPostSort,
                normalizeDirection(postDirection)
        );
    }

    public String entityType() {
        return platform == Platform.TELEGRAM ? "channels" : "institutions";
    }

    public String publicationLegacyType() {
        return platform == Platform.TELEGRAM ? "posts" : "platform_posts";
    }

    private static String normalizeDirection(String value) {
        return isDirection(value) ? value : "desc";
    }

    private static boolean isDirection(String value) {
        return "asc".equals(value) || "desc".equals(value);
    }
}
