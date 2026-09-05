package org.mranked.emoji.application;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import org.springframework.stereotype.Service;

@Service
public final class CustomEmojiService {
    static final Duration CACHE_TTL = Duration.ofHours(6);

    private final TelegramEmojiGateway gateway;
    private final Clock clock;
    private final ConcurrentMap<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public CustomEmojiService(TelegramEmojiGateway gateway) {
        this(gateway, Clock.systemUTC());
    }

    CustomEmojiService(TelegramEmojiGateway gateway, Clock clock) {
        this.gateway = Objects.requireNonNull(gateway, "gateway");
        this.clock = Objects.requireNonNull(clock, "clock");
    }

    public CustomEmojiAsset get(String emojiId) {
        if (!isLegacyIdentifier(emojiId)) {
            throw new CustomEmojiNotFoundException();
        }

        Instant now = clock.instant();
        CacheEntry cached = cache.get(emojiId);
        if (cached != null && cached.expiresAt().isAfter(now)) {
            return cached.asset();
        }

        CustomEmojiAsset asset = gateway.fetch(emojiId);
        cache.put(emojiId, new CacheEntry(now.plus(CACHE_TTL), asset));
        return asset;
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

    private record CacheEntry(Instant expiresAt, CustomEmojiAsset asset) {
    }
}
