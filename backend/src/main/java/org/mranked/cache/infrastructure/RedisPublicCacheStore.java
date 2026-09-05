package org.mranked.cache.infrastructure;

import java.time.Duration;
import java.util.Optional;
import org.mranked.cache.application.PublicCacheStore;
import org.springframework.data.redis.core.StringRedisTemplate;

public final class RedisPublicCacheStore implements PublicCacheStore {
    private final StringRedisTemplate redis;

    public RedisPublicCacheStore(StringRedisTemplate redis) {
        this.redis = redis;
    }

    @Override
    public Optional<String> get(String opaqueKey) {
        try {
            return Optional.ofNullable(redis.opsForValue().get(opaqueKey));
        } catch (RuntimeException ignored) {
            return Optional.empty();
        }
    }

    @Override
    public void put(String opaqueKey, String publicDtoJson, Duration ttl) {
        try {
            redis.opsForValue().set(opaqueKey, publicDtoJson, ttl);
        } catch (RuntimeException ignored) {
            // Redis failure must never change public response correctness.
        }
    }

    @Override
    public void remove(String opaqueKey) {
        try {
            redis.delete(opaqueKey);
        } catch (RuntimeException ignored) {
            // Redis failure must never change public response correctness.
        }
    }
}
