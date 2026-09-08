package org.mranked.analysis.application;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.UUID;
import org.mranked.query.application.InvalidCursorException;

final class AnalysisCursor {
    private AnalysisCursor() {
    }

    static String encode(UUID publicationId, long revision, int limit, UUID findingId) {
        String value = publicationId + ":" + revision + ":" + limit + ":" + findingId;
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(StandardCharsets.US_ASCII));
    }

    static UUID decode(String cursor, UUID publicationId, long revision, int limit) {
        if (cursor == null || cursor.isBlank()) return null;
        try {
            String value = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.US_ASCII);
            String[] parts = value.split(":", -1);
            if (parts.length != 4 || !UUID.fromString(parts[0]).equals(publicationId)
                    || Long.parseLong(parts[1]) != revision || Integer.parseInt(parts[2]) != limit) {
                throw new InvalidCursorException();
            }
            return UUID.fromString(parts[3]);
        } catch (IllegalArgumentException exception) {
            throw new InvalidCursorException();
        }
    }
}
