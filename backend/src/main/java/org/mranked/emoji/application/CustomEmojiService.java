package org.mranked.emoji.application;

import java.time.Clock;
import java.time.Duration;
import java.util.Objects;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.github.benmanes.caffeine.cache.Ticker;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public final class CustomEmojiService {
    static final Duration CACHE_TTL = Duration.ofHours(6);
    static final long CACHE_MAX_BYTES = 32L * 1024 * 1024;

    private final TelegramEmojiGateway gateway;
    private final Cache<String, CustomEmojiAsset> cache;

    @Autowired
    public CustomEmojiService(TelegramEmojiGateway gateway) {
        this(gateway, Clock.systemUTC(), Ticker.systemTicker());
    }

    CustomEmojiService(TelegramEmojiGateway gateway, Clock clock) {
        this(gateway, clock, () -> java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(clock.millis()));
    }

    private CustomEmojiService(TelegramEmojiGateway gateway, Clock clock, Ticker ticker) {
        this.gateway = Objects.requireNonNull(gateway, "gateway");
        Objects.requireNonNull(clock, "clock");
        this.cache = Caffeine.newBuilder().maximumWeight(CACHE_MAX_BYTES)
                .weigher((String key, CustomEmojiAsset value) -> key.length() * 2 + value.sizeBytes() + 128)
                .expireAfterWrite(CACHE_TTL).ticker(ticker).build();
    }

    public CustomEmojiAsset get(String emojiId) {
        if (!isLegacyIdentifier(emojiId)) {
            throw new CustomEmojiNotFoundException();
        }

        return cache.get(emojiId, gateway::fetch);
    }

    static boolean isLegacyIdentifier(String value) {
        if (value == null || value.isEmpty() || value.length() > 32) {
            return false;
        }
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character < '0' || character > '9') {
                return false;
            }
        }
        return true;
    }

    long cachedWeight() { cache.cleanUp(); return cache.policy().eviction().orElseThrow().weightedSize().orElseThrow(); }
}
