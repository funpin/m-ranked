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

    public String encode(UUID id) {
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString(id.toString().getBytes(StandardCharsets.US_ASCII));
    }
}
