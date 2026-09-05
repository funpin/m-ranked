package org.mranked.cache.application;

import org.mranked.cache.domain.DatasetRevision;

public record PublicCacheRequest(PublicCacheKey key) {
    public PublicCacheRequest {
        if (key == null) {
            throw new IllegalArgumentException("cache key is required");
        }
    }

    public DatasetRevision revision() {
        return key.revision();
    }
}
