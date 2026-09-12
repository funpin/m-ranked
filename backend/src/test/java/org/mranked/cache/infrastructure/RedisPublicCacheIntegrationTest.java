package org.mranked.cache.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import com.github.benmanes.caffeine.cache.Caffeine;
import java.net.ServerSocket;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.cache.application.*;
import org.mranked.cache.domain.DatasetRevision;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import tools.jackson.databind.json.JsonMapper;

/** Uses real Redis with isolated keys; never flushes a caller's database. */
@EnabledIfEnvironmentVariable(named="MRANKED_TEST_REDIS_PORT", matches="[0-9]+")
class RedisPublicCacheIntegrationTest {
    private static LettuceConnectionFactory connect(int port, String password) {
        var config=new RedisStandaloneConfiguration("127.0.0.1",port);
        if (password != null && !password.isEmpty()) config.setPassword(password);
        var client=LettuceClientConfiguration.builder().commandTimeout(Duration.ofMillis(300))
                .shutdownTimeout(Duration.ZERO).build();
        var factory=new LettuceConnectionFactory(config,client);
        factory.afterPropertiesSet(); factory.start();
        return factory;
    }
    private static PublicDtoCache cache(AtomicReference<DatasetRevision> revision, PublicCacheStore store) {
        return new PublicDtoCache(revision::get,new PublicCacheKeyFactory(),
                Caffeine.newBuilder().maximumSize(100).build(),store,new JsonMapper(),Duration.ofMinutes(1));
    }
    private static DatasetRevision revision(long id) {
        return new DatasetRevision(id,Instant.parse("2026-08-01T12:00:00Z"));
    }
    record Dto(String platform, long revision, Long measured, Long unavailable) {}

    @Test void realRedisEmptyColdLostEventIsolationCorruptionAndUnavailable() throws Exception {
        var connection=connect(Integer.parseInt(System.getenv("MRANKED_TEST_REDIS_PORT")),
                System.getenv("MRANKED_TEST_REDIS_PASSWORD"));
        var redis=new StringRedisTemplate(connection);
        var store=new RedisPublicCacheStore(redis);
        var keys=new ArrayList<String>();
        try {
            assertThat(redis.getConnectionFactory().getConnection().ping()).isEqualTo("PONG");
            var revision=new AtomicReference<>(revision(101));
            var namespace="integration-"+UUID.randomUUID();
            var node=cache(revision,store);
            var request=node.prepare(namespace,Map.of("platform","telegram","period","24h"));
            keys.add(request.key().redisKey());
            assertThat(store.get(request.key().redisKey())).isEmpty();
            var expected=new Dto("telegram",101,0L,null);
            assertThat(node.getOrLoadSnapshot(request,Dto.class,()->new RevisionedValue<>(revision.get(),expected)).value())
                    .isEqualTo(expected);
            assertThat(redis.getExpire(request.key().redisKey())).isBetween(1L,60L);
            var cold=cache(revision,store);
            assertThat(cold.getOrLoadSnapshot(request,Dto.class,()->{throw new AssertionError("L2 miss");}).value()).isEqualTo(expected);
            var vk=cold.prepare(namespace,Map.of("platform","vk","period","24h")); keys.add(vk.key().redisKey());
            assertThat(vk.key()).isNotEqualTo(request.key());
            assertThat(cold.getOrLoadSnapshot(vk,Dto.class,()->new RevisionedValue<>(revision.get(),new Dto("vk",101,2L,null))).value().platform())
                    .isEqualTo("vk");
            // No Pub/Sub is sent: authoritative revision must bypass stale L1/L2.
            revision.set(revision(102));
            var next=node.prepare(namespace,Map.of("platform","telegram","period","24h")); keys.add(next.key().redisKey());
            var nextDto=new Dto("telegram",102,1L,null);
            assertThat(node.getOrLoadSnapshot(next,Dto.class,()->new RevisionedValue<>(revision.get(),nextDto)).value()).isEqualTo(nextDto);
            store.put(next.key().redisKey(),"corrupt-json",Duration.ofMinutes(1));
            assertThat(cache(revision,store).getOrLoadSnapshot(next,Dto.class,()->new RevisionedValue<>(revision.get(),nextDto)).value()).isEqualTo(nextDto);
            assertThat(cache(revision,new DisabledPublicCacheStore()).getOrLoadSnapshot(next,Dto.class,
                    ()->new RevisionedValue<>(revision.get(),nextDto)).value()).isEqualTo(nextDto);
            // Reserve an unused local port so failure cannot accidentally hit another Redis.
            try (var unreachable=new ServerSocket(0)) {
                var failed=connect(unreachable.getLocalPort(),"");
                try {
                    assertThat(cache(revision,new RedisPublicCacheStore(new StringRedisTemplate(failed)))
                            .getOrLoadSnapshot(next,Dto.class,()->new RevisionedValue<>(revision.get(),nextDto)).value()).isEqualTo(nextDto);
                } finally { failed.destroy(); }
            }
        } finally { redis.delete(keys); connection.destroy(); }
    }

    @Test void sourcePublicationSurvivesUnrelatedWatermarksAndFencesLateFills() {
        var connection=connect(Integer.parseInt(System.getenv("MRANKED_TEST_REDIS_PORT")),
                System.getenv("MRANKED_TEST_REDIS_PASSWORD"));
        var redis=new StringRedisTemplate(connection);
        var store=new RedisPublicCacheStore(redis);
        var current=new AtomicReference<>(DatasetRevision.source(Instant.parse("2026-09-12T12:00:00Z")));
        String legacyId=Long.toString(1+Math.floorMod(UUID.randomUUID().getLeastSignificantBits(),Long.MAX_VALUE-1));
        var dimensions=Map.of("legacyId",legacyId,"legacyType","posts");
        var first=cache(current,store);
        var request=first.prepare("publication",dimensions);
        String key=request.key().redisKey();
        try {
            var initial=new RevisionedValue<>(current.get(),new Dto("telegram",current.get().id(),5L,null));
            first.getOrLoadSnapshot(request,Dto.class,()->initial);
            current.set(DatasetRevision.source(current.get().committedAt().plusSeconds(10)));
            var second=cache(current,store);
            var next=second.prepare("publication",dimensions);
            assertThat(next.key().redisKey()).isEqualTo(key);
            var hit=second.getOrLoadSnapshot(next,Dto.class,()->{throw new AssertionError("unrelated revision invalidated publication");});
            assertThat(hit).isEqualTo(initial);
            assertThat(new ETagFactory().create(next.key().atRevision(hit.revision())))
                    .isEqualTo(new ETagFactory().create(request.key()));
            assertThat(second.estimatedLocalSize()).isZero();
            assertThat(redis.getExpire(key)).isBetween(1L,60L);

            var inFlight=store.readScoped(key,Duration.ofMinutes(1));
            // Exact hash invalidation as performed by the transactional outbox.
            redis.delete(key);
            redis.opsForHash().put(key,"generation",UUID.randomUUID().toString());
            redis.expire(key,Duration.ofMinutes(1));
            store.putScoped(key,inFlight.generation(),"old-body",Duration.ofMinutes(1));
            assertThat(store.readScoped(key,Duration.ofMinutes(1)).payload()).isEmpty();
            var fresh=new RevisionedValue<>(current.get(),new Dto("telegram",current.get().id(),6L,null));
            assertThat(second.getOrLoadSnapshot(next,Dto.class,()->fresh)).isEqualTo(fresh);
            // Expiration must also fence the old writer; a missing generation is
            // never treated as the same generation as a previous cache miss.
            var expired=store.readScoped(key,Duration.ofMinutes(1));
            redis.delete(key);
            store.putScoped(key,expired.generation(),"old-body",Duration.ofMinutes(1));
            assertThat(redis.hasKey(key)).isFalse();
        } finally { redis.delete(key); connection.destroy(); }
    }
}
