package org.mranked.cache.domain;

import java.time.Instant;

public record DatasetRevision(long id, Instant committedAt) {
    public static final long SOURCE_ID_FLOOR = 1_000_000_000_000L;

    public DatasetRevision {
        if (id < 0) {
            throw new IllegalArgumentException("dataset revision cannot be negative");
        }
    }

    public static DatasetRevision source(Instant committedAt) {
        long epochMillis = committedAt.toEpochMilli();
        if (epochMillis < SOURCE_ID_FLOOR) {
            throw new IllegalArgumentException("source watermark is outside the supported epoch range");
        }
        return new DatasetRevision(epochMillis, committedAt);
    }

    public boolean sourceBacked() {
        return id >= SOURCE_ID_FLOOR;
    }
}
