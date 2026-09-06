package org.mranked.query.application;

import java.util.Map;
import org.mranked.analytics.domain.Platform;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;

/** Explicit non-secret deployment status; absence means unknown, never a guessed credential failure. */
@Component
public final class ProviderConfiguration {
    private final Map<Platform,String> values;
    private final boolean maxPhoneConfigured;
    public ProviderConfiguration(String telegram,String vk,String max,String rutube) {
        this(telegram,vk,max,rutube,false);
    }
    @Autowired
    public ProviderConfiguration(@Value("${mranked.integrations.telegram:unknown}") String telegram,
            @Value("${mranked.integrations.vk:unknown}") String vk,@Value("${mranked.integrations.max:unknown}") String max,
            @Value("${mranked.integrations.rutube:unknown}") String rutube,
            @Value("${mranked.health.max-phone-configured:false}") boolean maxPhoneConfigured) {
        for(String value:java.util.List.of(telegram,vk,max,rutube))
            if(!java.util.Set.of("configured","missing","unknown").contains(value))
                throw new IllegalArgumentException("integration status must be configured, missing or unknown");
        values=Map.of(Platform.TELEGRAM,telegram,Platform.VK,vk,Platform.MAX,max,Platform.RUTUBE,rutube);
        this.maxPhoneConfigured=maxPhoneConfigured;
    }
    public String status(Platform platform) {return values.getOrDefault(platform,"unknown");}
    public String warning(Platform platform) {
        if (!"missing".equals(status(platform))) return null;
        return switch(platform) {
            case VK -> "vk_token_required";
            case MAX -> maxPhoneConfigured ? "max_session_required" : "max_phone_required";
            case RUTUBE -> "rutube_api_disabled";
            default -> null;
        };
    }
    /** Public deployment flags can change without a new database revision/build. */
    public String representationVersion(String buildVersion) {
        try {
            var digest=java.security.MessageDigest.getInstance("SHA-256");
            digest.update(buildVersion.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            for (var platform:java.util.List.of(Platform.TELEGRAM,Platform.VK,Platform.MAX,Platform.RUTUBE)) {
                digest.update((byte)0);
                digest.update(status(platform).getBytes(java.nio.charset.StandardCharsets.US_ASCII));
                digest.update((byte)0);
                digest.update(java.util.Objects.toString(warning(platform),"").getBytes(java.nio.charset.StandardCharsets.US_ASCII));
            }
            return java.util.HexFormat.of().formatHex(digest.digest());
        } catch(java.security.NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is required",error);
        }
    }
    public static ProviderConfiguration unknown() {return new ProviderConfiguration("unknown","unknown","unknown","unknown");}
}
