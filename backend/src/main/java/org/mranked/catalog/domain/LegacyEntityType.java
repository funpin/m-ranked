package org.mranked.catalog.domain;

public enum LegacyEntityType {
    INSTITUTIONS("institutions"),
    CHANNELS("channels"),
    PLATFORM_ACCOUNTS("platform_accounts"),
    POSTS("posts"),
    PLATFORM_POSTS("platform_posts");

    private final String databaseValue;

    LegacyEntityType(String databaseValue) {
        this.databaseValue = databaseValue;
    }

    public String databaseValue() {
        return databaseValue;
    }

    public static LegacyEntityType fromApiValue(String value) {
        return switch (value) {
            case "posts" -> POSTS;
            case "platform_posts" -> PLATFORM_POSTS;
            default -> throw new IllegalArgumentException("unsupported legacy entity type");
        };
    }

    public static LegacyEntityType accountFromApiValue(String value) {
        return switch (value) {
            case "channels" -> CHANNELS;
            case "platform_accounts" -> PLATFORM_ACCOUNTS;
            default -> throw new IllegalArgumentException("unsupported account legacy entity type");
        };
    }
}
