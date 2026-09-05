package org.mranked.query.domain;

import org.mranked.analytics.domain.Platform;

public enum ComparisonSelectionType {
    CHANNELS("channels", "channel"),
    INSTITUTIONS("institutions", "institution");

    private final String apiValue;
    private final String entityValue;

    ComparisonSelectionType(String apiValue, String entityValue) {
        this.apiValue = apiValue;
        this.entityValue = entityValue;
    }

    public String apiValue() {
        return apiValue;
    }

    public String entityValue() {
        return entityValue;
    }

    public static ComparisonSelectionType forPlatform(Platform platform) {
        return platform == Platform.TELEGRAM ? CHANNELS : INSTITUTIONS;
    }
}
