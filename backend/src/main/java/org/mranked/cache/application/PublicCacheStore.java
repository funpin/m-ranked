package org.mranked.cache.application;

import java.time.Duration;
import java.util.Optional;

/** Redis-compatible L2 boundary. Implementations must fail open. */
public interface PublicCacheStore {
    Optional<String> get(String opaqueKey);

    void put(String opaqueKey, String publicDtoJson, Duration ttl);

    void remove(String opaqueKey);
}
