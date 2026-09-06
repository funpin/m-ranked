package org.mranked.cache.infrastructure;

import io.micrometer.core.instrument.FunctionCounter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.binder.MeterBinder;
import org.mranked.cache.application.PublicDtoCache;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods=false)
public class CacheMetricsConfiguration {
    @Bean MeterBinder publicCacheMetrics(PublicDtoCache cache) {
        return registry -> {
            FunctionCounter.builder("mranked.cache.requests",cache,PublicDtoCache::localHitCount)
                    .tags("outcome","hit","layer","l1").register(registry);
            FunctionCounter.builder("mranked.cache.requests",cache,PublicDtoCache::remoteHitCount)
                    .tags("outcome","hit","layer","l2").register(registry);
            FunctionCounter.builder("mranked.cache.requests",cache,PublicDtoCache::missCount)
                    .tags("outcome","miss","layer","database").register(registry);
            FunctionCounter.builder("mranked.cache.store.failures",cache,PublicDtoCache::storeFailureCount).register(registry);
            Gauge.builder("mranked.cache.local.entries",cache,PublicDtoCache::estimatedLocalSize).register(registry);
        };
    }
}
