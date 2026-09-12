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
    public String representationVersion() {return keyFactory.representationVersion();}
    private final DatasetRevisionProvider revisionProvider;
    private final PublicCacheKeyFactory keyFactory;
    private final Cache<String, String> l1;
    private final PublicCacheStore l2;
    private final ObjectMapper objectMapper;
    private final Duration l2Ttl;
    private final AtomicLong highestObservedRevision = new AtomicLong(Long.MIN_VALUE);
    private final java.util.concurrent.atomic.LongAdder localHits = new java.util.concurrent.atomic.LongAdder();
    private final java.util.concurrent.atomic.LongAdder remoteHits = new java.util.concurrent.atomic.LongAdder();
    private final java.util.concurrent.atomic.LongAdder misses = new java.util.concurrent.atomic.LongAdder();
    private final java.util.concurrent.atomic.LongAdder storeFailures = new java.util.concurrent.atomic.LongAdder();

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

    public <T> RevisionedValue<T> getOrLoadSnapshot(
            PublicCacheRequest request,
            Class<T> dtoType,
            java.util.function.Supplier<RevisionedValue<T>> loader
    ) {
        if (request.revision().id() == 0) {
            misses.increment();
            return loader.get();
        }
        String key = request.key().redisKey();
        if (key.startsWith("mranked:source:publication:")) {
            return getOrLoadSourcePublication(request, dtoType, loader);
        }
        Optional<T> local = decode(l1.getIfPresent(key), dtoType);
        if (local.isPresent()) {
            localHits.increment();
            return new RevisionedValue<>(request.revision(), local.get());
        }

        Optional<String> remotePayload = safeGet(key);
        Optional<T> remote = remotePayload.flatMap(payload -> decode(payload, dtoType));
        if (remote.isPresent()) {
            remoteHits.increment();
            l1.put(key, remotePayload.orElseThrow());
            return new RevisionedValue<>(request.revision(), remote.get());
        }
        if (remotePayload.isPresent()) {
            safeRemove(key);
        }

        misses.increment();
        RevisionedValue<T> loaded = loader.get();
        key = request.key().atRevision(loaded.revision()).redisKey();
        String encoded = encode(loaded.value());
        l1.put(key, encoded);
        safePut(key, encoded);
        return loaded;
    }

    // Source publications deliberately use L2 only. Every replica observes the
    // exact same invalidation; a disconnected Pub/Sub listener cannot serve L1
    // data beyond the invalidation or extend an L2 entry's ten-minute lifetime.
    private <T> RevisionedValue<T> getOrLoadSourcePublication(PublicCacheRequest request, Class<T> type,
            java.util.function.Supplier<RevisionedValue<T>> loader) {
        Duration ttl = l2Ttl.compareTo(Duration.ofMinutes(10)) > 0 ? Duration.ofMinutes(10) : l2Ttl;
        PublicCacheStore.ScopedEntry entry;
        try {
            entry = l2.readScoped(request.key().redisKey(), ttl);
            if (entry.payload().isPresent()) {
                var envelope = objectMapper.readTree(entry.payload().get());
                if (request.key().fingerprint().equals(envelope.path("shape").asString())
                        && envelope.path("revision").asLong() <= request.revision().id()) {
                    var revision = new DatasetRevision(envelope.path("revision").asLong(),
                            java.time.Instant.parse(envelope.path("committedAt").asString()));
                    T dto = objectMapper.treeToValue(envelope.path("value"), type);
                    remoteHits.increment();
                    return new RevisionedValue<>(revision, dto);
                }
            }
        } catch (RuntimeException error) {
            storeFailures.increment();
            misses.increment();
            return loader.get();
        }
        misses.increment();
        RevisionedValue<T> loaded = loader.get();
        String payload = encode(Map.of("shape", request.key().fingerprint(), "revision", loaded.revision().id(),
                "committedAt", loaded.revision().committedAt().toString(), "value", loaded.value()));
        try {
            l2.putScoped(request.key().redisKey(), entry.generation(), payload, ttl);
        } catch (RuntimeException error) {
            storeFailures.increment();
        }
        return loaded;
    }

    /** Compatibility adapter for callers that already own a pinned snapshot. */
    public <T> T getOrLoad(PublicCacheRequest request, Class<T> dtoType,
                           Function<DatasetRevision, T> loader) {
        return getOrLoadSnapshot(request, dtoType,
                () -> new RevisionedValue<>(request.revision(), loader.apply(request.revision()))).value();
    }

    public void invalidateLocal() {
        l1.invalidateAll();
    }

    public long estimatedLocalSize() {
        return l1.estimatedSize();
    }

    public long localHitCount() { return localHits.sum(); }
    public long remoteHitCount() { return remoteHits.sum(); }
    public long missCount() { return misses.sum(); }
    public long storeFailureCount() { return storeFailures.sum(); }

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
            storeFailures.increment();
            return Optional.empty();
        }
    }

    private void safePut(String key, String value) {
        try {
            l2.put(key, value, l2Ttl);
        } catch (RuntimeException ignored) {
            storeFailures.increment();
            // L2 is optional; the authoritative revision and database remain available.
        }
    }

    private void safeRemove(String key) {
        try {
            l2.remove(key);
        } catch (RuntimeException ignored) {
            storeFailures.increment();
            // A malformed remote entry is unreachable after expiry or revision advance.
        }
    }
}
