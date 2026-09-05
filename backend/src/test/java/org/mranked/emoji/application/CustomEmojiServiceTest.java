package org.mranked.emoji.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class CustomEmojiServiceTest {
    @Test
    void acceptsOnlyOneToThirtyTwoAsciiDigits() {
        AtomicInteger fetches = new AtomicInteger();
        CustomEmojiService service = new CustomEmojiService(identifier -> {
            fetches.incrementAndGet();
            return new CustomEmojiAsset(new byte[]{1}, "image/webp");
        }, Clock.systemUTC());

        assertThat(service.get("0").content()).containsExactly(1);
        assertThat(service.get("12345678901234567890123456789012").content()).containsExactly(1);
        for (String invalid : new String[]{
                "", "12a", "+12", "١٢", "123456789012345678901234567890123"
        }) {
            assertThatThrownBy(() -> service.get(invalid))
                    .isInstanceOf(CustomEmojiNotFoundException.class)
                    .hasMessage(CustomEmojiNotFoundException.LEGACY_DETAIL);
        }
        assertThat(fetches).hasValue(2);
    }

    @Test
    void cachesOnlySuccessfulAssetsForExactlySixHours() {
        MutableClock clock = new MutableClock(Instant.parse("2026-09-03T10:00:00Z"));
        AtomicInteger fetches = new AtomicInteger();
        CustomEmojiService service = new CustomEmojiService(identifier ->
                new CustomEmojiAsset(
                        new byte[]{(byte) fetches.incrementAndGet()}, "image/png"
                ), clock);

        assertThat(service.get("42").content()).containsExactly(1);
        clock.advance(Duration.ofHours(6).minusMillis(1));
        assertThat(service.get("42").content()).containsExactly(1);
        clock.advance(Duration.ofMillis(1));
        assertThat(service.get("42").content()).containsExactly(2);
        assertThat(fetches).hasValue(2);
    }

    @Test
    void doesNotCacheNotFoundResponses() {
        AtomicInteger fetches = new AtomicInteger();
        CustomEmojiService service = new CustomEmojiService(identifier -> {
            fetches.incrementAndGet();
            throw new CustomEmojiNotFoundException();
        }, Clock.systemUTC());

        assertThatThrownBy(() -> service.get("42"))
                .isInstanceOf(CustomEmojiNotFoundException.class);
        assertThatThrownBy(() -> service.get("42"))
                .isInstanceOf(CustomEmojiNotFoundException.class);
        assertThat(fetches).hasValue(2);
    }

    private static final class MutableClock extends Clock {
        private Instant instant;

        private MutableClock(Instant instant) {
            this.instant = instant;
        }

        private void advance(Duration duration) {
            instant = instant.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }
}
