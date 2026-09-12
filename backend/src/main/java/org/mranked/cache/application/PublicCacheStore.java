package org.mranked.cache.application;

import java.time.Duration;
import java.util.Optional;

/** Redis-compatible L2 boundary. Implementations must fail open. */
public interface PublicCacheStore {
    Optional<String> get(String opaqueKey);

    void put(String opaqueKey, String publicDtoJson, Duration ttl);

    void remove(String opaqueKey);

    record ScopedEntry(String generation, Optional<String> payload) { }

    /** A generation fences fills racing with transactional-outbox invalidation. */
    default ScopedEntry readScoped(String key, Duration ttl) {
        return new ScopedEntry("disabled", Optional.empty());
    }

    default void putScoped(String key, String generation, String payload, Duration ttl) { }
}
