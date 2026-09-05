package org.mranked.cache.application;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mranked.cache.domain.DatasetRevision;

class ETagFactoryTest {
    private final ETagFactory factory = new ETagFactory();
    private final PublicCacheKeyFactory keyFactory = new PublicCacheKeyFactory();

    @Test
    void etagIsStableAndRevisionAware() {
        DatasetRevision revision = new DatasetRevision(42, Instant.parse("2026-09-03T12:00:00Z"));

        String first = factory.create(keyFactory.create(
                "overview", revision, Map.of("platform", "all", "period", "1d", "limit", 50)
        ));
        String same = factory.create(keyFactory.create(
                "overview", revision, Map.of("limit", 50, "period", "1d", "platform", "all")
        ));
        String anotherRevision = factory.create(keyFactory.create(
                "overview", new DatasetRevision(43, revision.committedAt()),
                Map.of("platform", "all", "period", "1d", "limit", 50)
        ));
        String anotherQuery = factory.create(keyFactory.create(
                "overview", revision,
                Map.of("platform", "telegram", "period", "1d", "limit", 50)
        ));

        assertThat(first).isEqualTo(same).startsWith("\"mr-42-").endsWith("\"");
        assertThat(first).isNotEqualTo(anotherRevision).isNotEqualTo(anotherQuery);
    }

    @Test
    void acceptsWildcardWeakAndCommaSeparatedValidators() {
        String etag = factory.create(keyFactory.create(
                "institution",
                new DatasetRevision(7, Instant.parse("2026-09-03T12:00:00Z")),
                Map.of("legacyId", 12L)
        ));

        assertThat(factory.matches("*", etag)).isTrue();
        assertThat(factory.matches("\"old\", W/" + etag, etag)).isTrue();
        assertThat(factory.matches("\"old\"", etag)).isFalse();
        assertThat(factory.matches(null, etag)).isFalse();
    }
}
