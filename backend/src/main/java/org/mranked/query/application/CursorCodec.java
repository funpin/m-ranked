package org.mranked.query.application;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class CursorCodec {
    public Optional<UUID> decode(String cursor) {
        if (cursor == null || cursor.isBlank()) {
            return Optional.empty();
        }
        try {
            byte[] decoded = Base64.getUrlDecoder().decode(cursor);
            String value = new String(decoded, StandardCharsets.US_ASCII);
            if (!value.equals(value.trim()) || value.length() != 36) {
                throw new InvalidCursorException();
            }
            return Optional.of(UUID.fromString(value));
        } catch (IllegalArgumentException exception) {
            throw new InvalidCursorException();
        }
    }

    public String encodeRating(UUID id, long revision, Object query) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
                (revision + ":" + fingerprint(query) + ":" + id).getBytes(StandardCharsets.US_ASCII));
    }

    public UUID decodeRating(String cursor, long revision, Object query) {
        if (cursor == null || cursor.isBlank()) return null;
        try {
            String[] parts = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.US_ASCII).split(":");
            if (parts.length != 3 || Long.parseLong(parts[0]) != revision
                    || !parts[1].equals(fingerprint(query))) throw new InvalidCursorException();
            return UUID.fromString(parts[2]);
        } catch (IllegalArgumentException exception) {
            throw new InvalidCursorException();
        }
    }

    private static String fingerprint(Object query) {
        try {
            return java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256")
                    .digest(query.toString().getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException exception) { throw new IllegalStateException(exception); }
    }

    public String encode(UUID id) {
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString(id.toString().getBytes(StandardCharsets.US_ASCII));
    }
}
