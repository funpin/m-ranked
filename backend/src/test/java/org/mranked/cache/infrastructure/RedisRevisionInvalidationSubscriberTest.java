package org.mranked.cache.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import com.github.benmanes.caffeine.cache.Caffeine;
import java.time.Duration;
import java.time.Instant;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mranked.cache.application.PublicCacheKeyFactory;
import org.mranked.cache.application.PublicDtoCache;
import org.mranked.cache.domain.DatasetRevision;
import tools.jackson.databind.json.JsonMapper;

class RedisRevisionInvalidationSubscriberTest {
    @Test
    void acceptsOutboxRevisionEnvelopeAndInvalidatesL1WithoutRetainingPayload() {
        PublicDtoCache cache = new PublicDtoCache(
                () -> new DatasetRevision(41, Instant.parse("2026-09-03T10:00:00Z")),
                new PublicCacheKeyFactory(),
                Caffeine.newBuilder().maximumSize(10).build(),
                new DisabledPublicCacheStore(),
                new JsonMapper(),
                Duration.ofMinutes(10)
        );
        cache.getOrLoad(
                cache.prepare("overview", Map.of("limit", 1)), CachedValue.class,
                revision -> new CachedValue("value")
        );
        RedisRevisionInvalidationSubscriber subscriber =
                new RedisRevisionInvalidationSubscriber(cache);

        boolean accepted = subscriber.accept(
                ("{\"id\":7,\"datasetRevisionId\":42,"
                        + "\"eventType\":\"projection.published\",\"payload\":{}}")
                        .getBytes(StandardCharsets.UTF_8)
        );

        assertThat(accepted).isTrue();
        assertThat(cache.estimatedLocalSize()).isZero();
        assertThat(subscriber.accept("not-an-event".getBytes(StandardCharsets.UTF_8))).isFalse();
    }

    private record CachedValue(String value) {
    }
}
