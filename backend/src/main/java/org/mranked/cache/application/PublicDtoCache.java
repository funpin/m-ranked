package org.mranked.cache.application;

import com.github.benmanes.caffeine.cache.Cache;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Function;
import org.mranked.cache.domain.DatasetRevision;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/**
 * Two-level cache for already-mapped public DTOs. A PostgreSQL revision read is
 * deliberately performed by {@link #prepare} on every request, before either cache
 * is consulted. Redis is therefore an availability/performance optimization only.
 */
@Component
public class PublicDtoCache {
    private final DatasetRevisionProvider revisionProvider;
    private final PublicCacheKeyFactory keyFactory;
    private final Cache<String, String> l1;
    private final PublicCacheStore l2;
    private final ObjectMapper objectMapper;
    private final Duration l2Ttl;
    private final AtomicLong highestObservedRevision = new AtomicLong(Long.MIN_VALUE);

    public PublicDtoCache(
            DatasetRevisionProvider revisionProvider,
            PublicCacheKeyFactory keyFactory,
            Cache<String, String> publicDtoL1Cache,
            PublicCacheStore l2,
            ObjectMapper objectMapper,
            @Value("${mranked.cache.redis.ttl:PT10M}") Duration l2Ttl
    ) {
        this.revisionProvider = revisionProvider;
        this.keyFactory = keyFactory;
        this.l1 = publicDtoL1Cache;
        this.l2 = l2;
        this.objectMapper = objectMapper;
        this.l2Ttl = l2Ttl;
    }

    public PublicCacheRequest prepare(String namespace, Map<String, ?> normalizedQuery) {
        DatasetRevision revision = revisionProvider.current();
        long previous = highestObservedRevision.getAndAccumulate(revision.id(), Math::max);
        if (previous != Long.MIN_VALUE && revision.id() > previous) {
            l1.invalidateAll();
        }
        return new PublicCacheRequest(keyFactory.create(namespace, revision, normalizedQuery));
    }

    public <T> T getOrLoad(
            PublicCacheRequest request,
            Class<T> dtoType,
            Function<DatasetRevision, T> loader
    ) {
        if (request.revision().id() == 0) {
            return loader.apply(request.revision());
        }
        String key = request.key().redisKey();
        Optional<T> local = decode(l1.getIfPresent(key), dtoType);
        if (local.isPresent()) {
            return local.get();
        }

        Optional<String> remotePayload = safeGet(key);
        Optional<T> remote = remotePayload.flatMap(payload -> decode(payload, dtoType));
        if (remote.isPresent()) {
            l1.put(key, remotePayload.orElseThrow());
            return remote.get();
        }
        if (remotePayload.isPresent()) {
            safeRemove(key);
        }

        T loaded = loader.apply(request.revision());
        String encoded = encode(loaded);
        l1.put(key, encoded);
        safePut(key, encoded);
        return loaded;
    }

    public void invalidateLocal() {
        l1.invalidateAll();
    }

    public long estimatedLocalSize() {
        return l1.estimatedSize();
    }

    private <T> Optional<T> decode(String encoded, Class<T> dtoType) {
        if (encoded == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(objectMapper.readValue(encoded, dtoType));
        } catch (Exception ignored) {
            return Optional.empty();
        }
    }

    private String encode(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception exception) {
            throw new IllegalStateException("public response could not be encoded", exception);
        }
    }

    private Optional<String> safeGet(String key) {
        try {
            return l2.get(key);
        } catch (RuntimeException ignored) {
            return Optional.empty();
        }
    }

    private void safePut(String key, String value) {
        try {
            l2.put(key, value, l2Ttl);
        } catch (RuntimeException ignored) {
            // L2 is optional; the authoritative revision and database remain available.
        }
    }

    private void safeRemove(String key) {
        try {
            l2.remove(key);
        } catch (RuntimeException ignored) {
            // A malformed remote entry is unreachable after expiry or revision advance.
        }
    }
}
