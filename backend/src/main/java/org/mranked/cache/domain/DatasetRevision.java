package org.mranked.cache.domain;

import java.time.Instant;

public record DatasetRevision(long id, Instant committedAt) {
    public DatasetRevision {
        if (id < 0) {
            throw new IllegalArgumentException("dataset revision cannot be negative");
        }
    }
}
