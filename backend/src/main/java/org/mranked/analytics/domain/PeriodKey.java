package org.mranked.analytics.domain;

public enum PeriodKey {
    THREE_HOURS("3h"),
    ONE_DAY("1d"),
    SEVEN_DAYS("7d"),
    THIRTY_DAYS("30d");

    private final String databaseValue;

    PeriodKey(String databaseValue) {
        this.databaseValue = databaseValue;
    }

    public String databaseValue() {
        return databaseValue;
    }

    public static PeriodKey fromApiValue(String value) {
        for (PeriodKey period : values()) {
            if (period.databaseValue.equals(value)) {
                return period;
            }
        }
        throw new IllegalArgumentException("unsupported period");
    }
}
