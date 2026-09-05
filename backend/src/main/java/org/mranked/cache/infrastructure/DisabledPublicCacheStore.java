package org.mranked.cache.infrastructure;

import java.time.Duration;
import java.util.Optional;
import org.mranked.cache.application.PublicCacheStore;

public final class DisabledPublicCacheStore implements PublicCacheStore {
    @Override
    public Optional<String> get(String opaqueKey) {
        return Optional.empty();
    }

    @Override
    public void put(String opaqueKey, String publicDtoJson, Duration ttl) {
        // Redis is explicitly disabled; L1 and PostgreSQL continue to serve requests.
    }

    @Override
    public void remove(String opaqueKey) {
        // Nothing to remove.
    }
}
