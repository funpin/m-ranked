package org.mranked.cache.application;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import org.mranked.cache.domain.DatasetRevision;
import org.springframework.stereotype.Component;

@Component
public class PublicCacheKeyFactory {
    private static final String PREFIX = "mranked:public:v1:dto1";

    public PublicCacheKey create(
            String namespace,
            DatasetRevision revision,
            Map<String, ?> normalizedQuery
    ) {
        if (namespace == null || !namespace.matches("[a-z][a-z0-9-]{0,63}")) {
            throw new IllegalArgumentException("invalid public cache namespace");
        }
        if (revision == null) {
            throw new IllegalArgumentException("dataset revision is required");
        }
        if (normalizedQuery == null) {
            throw new IllegalArgumentException("normalized query is required");
        }

        MessageDigest digest = sha256();
        updateLengthPrefixed(digest, namespace);
        new TreeMap<>(normalizedQuery).forEach((name, value) -> {
            if (name == null || name.isBlank()) {
                throw new IllegalArgumentException("cache dimension name is required");
            }
            updateLengthPrefixed(digest, name);
            updateLengthPrefixed(digest, canonicalValue(value));
        });
        String fingerprint = HexFormat.of().formatHex(digest.digest());
        String redisKey = PREFIX + ":" + namespace + ":r" + revision.id() + ":q" + fingerprint;
        return new PublicCacheKey(redisKey, fingerprint, revision);
    }

    private static String canonicalValue(Object value) {
        if (value == null) {
            return "null:";
        }
        if (value instanceof Boolean booleanValue) {
            return "bool:" + Boolean.toString(booleanValue);
        }
        if (value instanceof Byte || value instanceof Short || value instanceof Integer
                || value instanceof Long) {
            return "int:" + value;
        }
        if (value instanceof CharSequence || value instanceof UUID) {
            return "text:" + value;
        }
        throw new IllegalArgumentException(
                "unsupported cache dimension type: " + value.getClass().getSimpleName()
        );
    }

    private static void updateLengthPrefixed(MessageDigest digest, String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        digest.update(Integer.toString(bytes.length).getBytes(StandardCharsets.US_ASCII));
        digest.update((byte) ':');
        digest.update(bytes);
        digest.update((byte) 0);
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required by the Java runtime", exception);
        }
    }
}
