package org.mranked.cache.application;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mranked.cache.domain.DatasetRevision;

class PublicCacheKeyFactoryTest {
    private final PublicCacheKeyFactory factory = new PublicCacheKeyFactory();
    private final DatasetRevision revision = new DatasetRevision(
            19, Instant.parse("2026-09-03T10:00:00Z")
    );

    @Test
    void normalizesParameterOrderAndIsolatesNamespaces() {
        Map<String, Object> firstOrder = new LinkedHashMap<>();
        firstOrder.put("platform", "telegram");
        firstOrder.put("period", "1d");
        firstOrder.put("limit", 50);
        Map<String, Object> secondOrder = new LinkedHashMap<>();
        secondOrder.put("limit", 50);
        secondOrder.put("period", "1d");
        secondOrder.put("platform", "telegram");

        PublicCacheKey first = factory.create("overview", revision, firstOrder);
        PublicCacheKey reordered = factory.create("overview", revision, secondOrder);
        PublicCacheKey anotherNamespace = factory.create("rating", revision, secondOrder);

        assertThat(first).isEqualTo(reordered);
        assertThat(first.redisKey()).isNotEqualTo(anotherNamespace.redisKey());
        assertThat(first.fingerprint()).isNotEqualTo(anotherNamespace.fingerprint());
    }

    @Test
    void isolatesRevisionsAndHashesRawQueryValues() {
        String requestText = "private-looking-search@example.test";
        PublicCacheKey first = factory.create(
                "overview", revision, Map.of("q", requestText, "cursor", "opaque-cursor")
        );
        PublicCacheKey nextRevision = factory.create(
                "overview", new DatasetRevision(20, revision.committedAt()),
                Map.of("q", requestText, "cursor", "opaque-cursor")
        );

        assertThat(first.redisKey())
                .doesNotContain(requestText)
                .doesNotContain("opaque-cursor")
                .contains(":r19:q");
        assertThat(nextRevision.redisKey()).contains(":r20:q").isNotEqualTo(first.redisKey());
    }
}
