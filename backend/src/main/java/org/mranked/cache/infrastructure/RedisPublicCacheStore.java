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
        return Optional.ofNullable(redis.opsForValue().get(opaqueKey));
    }

    @Override
    public void put(String opaqueKey, String publicDtoJson, Duration ttl) {
        redis.opsForValue().set(opaqueKey, publicDtoJson, ttl);
    }

    @Override
    public void remove(String opaqueKey) {
        redis.delete(opaqueKey);
    }
}
