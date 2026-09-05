package org.mranked.cache.infrastructure;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import java.time.Duration;
import org.mranked.cache.application.PublicCacheStore;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;

@Configuration(proxyBeanMethods = false)
public class PublicCacheConfiguration {
    public static final String DEFAULT_INVALIDATION_CHANNEL = "mranked:revision.changed";

    @Bean
    Cache<String, String> publicDtoL1Cache(
            @Value("${mranked.cache.l1.maximum-weight-bytes:67108864}") long maximumWeightBytes,
            @Value("${mranked.cache.l1.ttl:PT2M}") Duration ttl
    ) {
        return Caffeine.<String, String>newBuilder()
                .maximumWeight(maximumWeightBytes)
                .weigher((String key, String value) -> (int) Math.max(1L, Math.min(
                        Integer.MAX_VALUE,
                        2L * key.length() + 2L * value.length()
                )))
                .expireAfterWrite(ttl)
                .build();
    }

    @Bean
    PublicCacheStore publicCacheStore(
            ObjectProvider<StringRedisTemplate> redisProvider,
            @Value("${mranked.cache.redis.enabled:true}") boolean redisEnabled
    ) {
        StringRedisTemplate redis = redisProvider.getIfAvailable();
        if (!redisEnabled || redis == null) {
            return new DisabledPublicCacheStore();
        }
        return new RedisPublicCacheStore(redis);
    }

    @Bean
    @ConditionalOnProperty(
            name = "mranked.cache.redis.enabled",
            havingValue = "true",
            matchIfMissing = true
    )
    RedisMessageListenerContainer publicCacheInvalidationListenerContainer(
            RedisConnectionFactory connectionFactory,
            RedisRevisionInvalidationSubscriber subscriber,
            @Value("${mranked.cache.redis.invalidation-channel:"
                    + DEFAULT_INVALIDATION_CHANNEL + "}") String channel
    ) {
        RedisMessageListenerContainer container = new RedisMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        container.setRecoveryInterval(5_000L);
        container.addMessageListener(subscriber, new ChannelTopic(channel));
        return container;
    }
}
