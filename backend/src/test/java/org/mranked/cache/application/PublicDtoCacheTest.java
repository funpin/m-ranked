package org.mranked.cache.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.github.benmanes.caffeine.cache.Caffeine;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.cache.infrastructure.DisabledPublicCacheStore;
import tools.jackson.databind.json.JsonMapper;

class PublicDtoCacheTest {
    private static final Duration TTL = Duration.ofMinutes(10);

    @Test
    void checksAuthoritativeRevisionOnEveryRequestEvenForAnL1Hit() {
        AtomicInteger revisionReads = new AtomicInteger();
        DatasetRevision revision = revision(7);
        PublicDtoCache cache = cache(() -> {
            revisionReads.incrementAndGet();
            return revision;
        }, new DisabledPublicCacheStore());
        AtomicInteger loads = new AtomicInteger();

        TestDto first = cache.getOrLoad(
                cache.prepare("overview", Map.of("platform", "all")),
                TestDto.class,
                selected -> new TestDto("same-body", selected.id(), loads.incrementAndGet())
        );
        TestDto second = cache.getOrLoad(
                cache.prepare("overview", Map.of("platform", "all")),
                TestDto.class,
                selected -> new TestDto("must-not-load", selected.id(), loads.incrementAndGet())
        );

        assertThat(second).isEqualTo(first);
        assertThat(revisionReads).hasValue(2);
        assertThat(loads).hasValue(1);
    }

    @Test
    void revisionAdvanceCannotServeOldDataWhenPubSubEventIsLost() {
        AtomicReference<DatasetRevision> current = new AtomicReference<>(revision(11));
        PublicDtoCache cache = cache(current::get, new DisabledPublicCacheStore());
        AtomicInteger loads = new AtomicInteger();

        TestDto oldBody = cache.getOrLoad(
                cache.prepare("rating", Map.of("limit", 50)), TestDto.class,
                selected -> new TestDto("revision-" + selected.id(), selected.id(), loads.incrementAndGet())
        );
        current.set(revision(12));
        TestDto newBody = cache.getOrLoad(
                cache.prepare("rating", Map.of("limit", 50)), TestDto.class,
                selected -> new TestDto("revision-" + selected.id(), selected.id(), loads.incrementAndGet())
        );

        assertThat(oldBody.revision()).isEqualTo(11);
        assertThat(newBody.revision()).isEqualTo(12);
        assertThat(newBody.value()).isEqualTo("revision-12");
        assertThat(loads).hasValue(2);
        assertThat(cache.estimatedLocalSize()).isEqualTo(1);
    }

    @Test
    void coldL2AndDisabledRedisProduceTheSamePublicDto() {
        MemoryStore redis = new MemoryStore();
        DatasetRevisionProvider revisions = () -> revision(22);
        TestDto expected = new TestDto("public", 22, 1);
        PublicDtoCache seedingNode = cache(revisions, redis);
        seedingNode.getOrLoad(
                seedingNode.prepare("account", Map.of("legacyId", 9L)),
                TestDto.class,
                selected -> expected
        );

        PublicDtoCache coldNode = cache(revisions, redis);
        TestDto fromColdL2 = coldNode.getOrLoad(
                coldNode.prepare("account", Map.of("legacyId", 9L)),
                TestDto.class,
                selected -> {
                    throw new AssertionError("cold L1 must use Redis L2");
                }
        );
        PublicDtoCache redisDisabled = cache(revisions, new DisabledPublicCacheStore());
        TestDto withoutRedis = redisDisabled.getOrLoad(
                redisDisabled.prepare("account", Map.of("legacyId", 9L)),
                TestDto.class,
                selected -> expected
        );

        assertThat(fromColdL2).isEqualTo(expected);
        assertThat(withoutRedis).isEqualTo(expected);
        assertThat(redis.gets).isEqualTo(2);
        assertThat(redis.puts).isEqualTo(1);
    }

    @Test
    void unavailableRedisFailsOpenToTheLoader() {
        PublicCacheStore unavailable = new PublicCacheStore() {
            @Override
            public Optional<String> get(String opaqueKey) {
                throw new IllegalStateException("redis unavailable");
            }

            @Override
            public void put(String opaqueKey, String publicDtoJson, Duration ttl) {
                throw new IllegalStateException("redis unavailable");
            }

            @Override
            public void remove(String opaqueKey) {
                throw new IllegalStateException("redis unavailable");
            }
        };
        PublicDtoCache cache = cache(() -> revision(31), unavailable);

        TestDto body = cache.getOrLoad(
                cache.prepare("publication", Map.of("legacyId", 4L)), TestDto.class,
                selected -> new TestDto("database", selected.id(), 1)
        );

        assertThat(body).isEqualTo(new TestDto("database", 31, 1));
    }

    private static PublicDtoCache cache(
            DatasetRevisionProvider revisions,
            PublicCacheStore l2
    ) {
        return new PublicDtoCache(
                revisions,
                new PublicCacheKeyFactory(),
                Caffeine.newBuilder().maximumSize(100).build(),
                l2,
                new JsonMapper(),
                TTL
        );
    }

    private static DatasetRevision revision(long id) {
        return new DatasetRevision(id, Instant.parse("2026-09-03T10:00:00Z"));
    }

    private record TestDto(String value, long revision, int loadNumber) {
    }

    private static final class MemoryStore implements PublicCacheStore {
        private final Map<String, String> values = new HashMap<>();
        private int gets;
        private int puts;

        @Override
        public Optional<String> get(String opaqueKey) {
            gets++;
            return Optional.ofNullable(values.get(opaqueKey));
        }

        @Override
        public void put(String opaqueKey, String publicDtoJson, Duration ttl) {
            puts++;
            values.put(opaqueKey, publicDtoJson);
        }

        @Override
        public void remove(String opaqueKey) {
            values.remove(opaqueKey);
        }
    }
}
