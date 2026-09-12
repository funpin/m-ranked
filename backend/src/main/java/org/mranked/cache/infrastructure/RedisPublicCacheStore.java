package org.mranked.cache.infrastructure;

import java.time.Duration;
import java.util.Optional;
import java.util.List;
import org.springframework.data.redis.core.script.DefaultRedisScript;
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

    // A read stays a read. Redis here runs with an append-only file on the same
    // single-core disk as PostgreSQL, so turning every cache hit into a write
    // would buy the fence with I/O the box does not have. The empty string is
    // the generation a reader observes when the key carries none yet; a fill
    // may then establish its own, and any invalidation in between stamps a
    // non-empty generation that fences the late writer out.
    private static final String NO_GENERATION = "";
    private static final DefaultRedisScript<List> READ_SCOPED = new DefaultRedisScript<>("""
        local entry=redis.call('HMGET',KEYS[1],'generation','payload')
        return {entry[1] or '',entry[2] or ''}
        """, List.class);
    private static final DefaultRedisScript<Long> PUT_SCOPED = new DefaultRedisScript<>("""
        local observed=redis.call('HGET',KEYS[1],'generation')
        if (observed or '') ~= ARGV[1] then return 0 end
        if observed == false then redis.call('HSET',KEYS[1],'generation',ARGV[1]) end
        redis.call('HSET',KEYS[1],'payload',ARGV[2])
        redis.call('PEXPIRE',KEYS[1],ARGV[3])
        return 1
        """, Long.class);

    @Override
    public ScopedEntry readScoped(String key, Duration ttl) {
        List<?> result = redis.execute(READ_SCOPED, List.of(key));
        if (result == null || result.size() != 2) throw new IllegalStateException("invalid scoped cache result");
        String payload = (String) result.get(1);
        return new ScopedEntry((String) result.get(0), payload.isEmpty() ? Optional.empty() : Optional.of(payload));
    }

    @Override
    public void putScoped(String key, String generation, String payload, Duration ttl) {
        redis.execute(PUT_SCOPED, List.of(key), generation == null ? NO_GENERATION : generation,
                payload, Long.toString(ttl.toMillis()));
    }
}
