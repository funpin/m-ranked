package org.mranked.cache.application;

import org.mranked.cache.domain.DatasetRevision;

/**
 * An opaque cache identity. Query values are represented only by a SHA-256 digest,
 * so URLs, search text, and other request data are not copied into Redis keys.
 */
public record PublicCacheKey(
        String redisKey,
        String fingerprint,
        DatasetRevision revision
) {
    public PublicCacheKey {
        if (redisKey == null || redisKey.isBlank()) {
            throw new IllegalArgumentException("redis key is required");
        }
        if (fingerprint == null || !fingerprint.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("cache fingerprint must be SHA-256");
        }
        if (revision == null) {
            throw new IllegalArgumentException("dataset revision is required");
        }
    }
}
