package org.mranked.query.domain;

import java.time.Instant;
import java.util.List;

public record PageResult<T>(
        List<T> items,
        String nextCursor,
        long datasetRevision,
        Instant asOf
) {
    public PageResult {
        items = List.copyOf(items);
    }
}
