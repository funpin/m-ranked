package org.mranked.operations.application;

import java.time.Instant;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/** Legacy shape with safe configuration flags; current target runs supersede imported checkpoints. */
@Service
public final class LegacyHealthService {
    private static final String[] PLATFORMS={"telegram","vk","max","rutube"};
    private final HealthSnapshotSource source;
    private final String mode;
    private final long freshnessSeconds;
    private final Map<String,Boolean> configured;
    private final boolean maxPhone, maxSession;

    public LegacyHealthService(HealthSnapshotSource source,
            @Value("${mranked.health.data-source:public_web}") String mode,
            @Value("${mranked.health.poll-interval-minutes:60}") long pollMinutes,
            @Value("${mranked.integrations.telegram:unknown}") String telegram,
            @Value("${mranked.integrations.vk:unknown}") String vk,
            @Value("${mranked.integrations.max:unknown}") String max,
            @Value("${mranked.integrations.rutube:unknown}") String rutube,
            @Value("${mranked.health.max-phone-configured:false}") boolean maxPhone,
            @Value("${mranked.health.max-session-exists:false}") boolean maxSession) {
        if (!Set.of("public_web","telegram_web","mtproto").contains(mode) || pollMinutes<1 || pollMinutes>1440)
            throw new IllegalArgumentException("invalid public health configuration");
        this.source=source;this.mode=mode;this.freshnessSeconds=Math.max(pollMinutes*120,600);
        this.configured=Map.of("telegram",mode.equals("public_web")||mode.equals("telegram_web")||telegram.equals("configured"),
                "vk",vk.equals("configured"),"max",max.equals("configured"),"rutube",rutube.equals("configured"));
        this.maxPhone=maxPhone;this.maxSession=maxSession;
    }

    public Map<String,Object> legacy() {
        var snapshot=source.snapshot();var checkpoints=object(snapshot.get("checkpoints"));
        var cycles=cycles(snapshot,checkpoints);var telegram=cycles.get("telegram");
        boolean fresh=fresh(snapshot,telegram,"telegram");
        var integrations=new LinkedHashMap<String,Object>();
        integrations.put("telegram",nullableMap("configured",configured.get("telegram"),"mode",mode,
                "comments_last_success_at",checkpoints.get("telegram_web_last_success_at"),
                "comments_last_error",checkpoints.get("telegram_web_last_error")));
        integrations.put("vk",nullableMap("configured",configured.get("vk"),"poll_cycle",cycles.get("vk")));
        integrations.put("max",nullableMap("configured",configured.get("max"),"mode","user_session",
                "phone_configured",maxPhone,"session_exists",maxSession,"poll_cycle",cycles.get("max")));
        integrations.put("rutube",nullableMap("configured",configured.get("rutube"),"mode","official_public_api","poll_cycle",cycles.get("rutube")));
        return nullableMap("status","ok","data_source",mode,"source_connected",fresh,"collector_fresh",fresh,
                "telegram_connected",mode.equals("telegram_web") && fresh && checkpoints.get("telegram_web_last_success_at")!=null && checkpoints.get("telegram_web_last_error")==null,
                "channels",snapshot.get("channels"),"last_poll",checkpoints.get("last_poll"),"next_poll",checkpoints.get("next_poll"),
                "poll_cycle",telegram,"integrations",integrations);
    }

    public Map<String,Object> freshness() {
        var snapshot=source.snapshot();var checkpoints=object(snapshot.get("checkpoints"));
        var cycles=cycles(snapshot,checkpoints);var platforms=new LinkedHashMap<String,Object>();
        boolean healthy=true;
        for (String platform:PLATFORMS) {
            boolean fresh=fresh(snapshot,cycles.get(platform),platform);
            if (configured.get(platform) && !fresh) healthy=false;
            platforms.put(platform,nullableMap("configured",configured.get(platform),"fresh",fresh,
                    "completedAt",cycles.get(platform).get("completed_at")));
        }
        long raw=((Number)snapshot.get("rawRevision")).longValue();
        long published=((Number)snapshot.get("publishedRevision")).longValue();
        healthy=healthy && raw>0 && raw==published;
        return nullableMap("status",healthy?"UP":"DOWN","asOf",snapshot.get("asOf"),
                "datasetRevision",published,"revisionLag",Math.max(0,raw-published),
                "freshnessThresholdSeconds",freshnessSeconds,"platforms",platforms);
    }

    private Map<String,Map<String,Object>> cycles(Map<String,Object> snapshot,Map<String,Object> checkpoints) {
        var result=new LinkedHashMap<String,Map<String,Object>>();var runs=object(snapshot.get("runs"));
        for(String platform:PLATFORMS) {
            var run=object(runs.get(platform));boolean target=run.get("started_at")!=null;
            String prefix=platform.equals("telegram")?"poll_last_":platform+"_poll_last_";
            var cycle=nullableMap("completed_at",target?run.get("completed_at"):checkpoints.get(prefix+"completed_at"),
                    "duration_seconds",target?run.get("duration_seconds"):checkpoints.get(prefix+"duration_seconds"),
                    "error_count",target?run.get("error_count"):checkpoints.get(prefix+"error_count"));
            if (platform.equals("telegram")) {
                cycle.put("started_at",target?run.get("started_at"):checkpoints.get(prefix+"started_at"));
                cycle.put("channel_count",target?run.get("account_count"):checkpoints.get(prefix+"channel_count"));
            } else cycle.put("account_count",target?run.get("account_count"):checkpoints.get(prefix+"account_count"));
            result.put(platform,cycle);
        }
        return result;
    }

    private boolean fresh(Map<String,Object> snapshot,Map<String,Object> cycle,String platform) {
        try {
            var run=object(object(snapshot.get("runs")).get(platform));
            if(run.get("started_at")!=null && !"succeeded".equals(run.get("status"))) return false;
            Instant now=Instant.parse(snapshot.get("asOf").toString());
            Instant completed=Instant.parse(cycle.get("completed_at").toString());
            long age=Duration.between(completed,now).getSeconds();
            return age>=0 && age<=freshnessSeconds;
        } catch(RuntimeException ignored) {return false;}
    }
    @SuppressWarnings("unchecked") private static Map<String,Object> object(Object value) {
        return value instanceof Map<?,?> ? (Map<String,Object>)value : Map.of();
    }
    private static LinkedHashMap<String,Object> nullableMap(Object... values) {
        var map=new LinkedHashMap<String,Object>();for(int i=0;i<values.length;i+=2)map.put((String)values[i],values[i+1]);return map;
    }
}
