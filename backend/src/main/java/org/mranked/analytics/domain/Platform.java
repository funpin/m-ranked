package org.mranked.analytics.domain;

public enum Platform {
    ALL("all"),
    TELEGRAM("telegram"),
    VK("vk"),
    MAX("max"),
    RUTUBE("rutube");

    private final String databaseValue;

    Platform(String databaseValue) {
        this.databaseValue = databaseValue;
    }

    public String databaseValue() {
        return databaseValue;
    }

    public static Platform fromApiValue(String value) {
        for (Platform platform : values()) {
            if (platform.databaseValue.equals(value)) {
                return platform;
            }
        }
        throw new IllegalArgumentException("unsupported platform");
    }
}
