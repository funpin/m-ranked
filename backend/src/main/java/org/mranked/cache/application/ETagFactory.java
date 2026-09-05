package org.mranked.cache.application;

import org.springframework.stereotype.Component;

@Component
public class ETagFactory {
    public String create(PublicCacheKey key) {
        return "\"mr-" + key.revision().id() + "-" + key.fingerprint() + "\"";
    }

    public boolean matches(String ifNoneMatch, String currentEtag) {
        if (ifNoneMatch == null || ifNoneMatch.isBlank()) {
            return false;
        }
        for (String candidate : ifNoneMatch.split(",")) {
            String normalized = candidate.trim();
            if (normalized.startsWith("W/")) {
                normalized = normalized.substring(2).trim();
            }
            if ("*".equals(normalized) || currentEtag.equals(normalized)) {
                return true;
            }
        }
        return false;
    }
}
