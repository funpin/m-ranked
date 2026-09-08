package org.mranked.analysis.application;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import org.springframework.stereotype.Service;
import tools.jackson.databind.json.JsonMapper;

@Service
public class AnalysisAdminService {
    private static final JsonMapper JSON = new JsonMapper();
    private final AnalysisAdminCommandPort commands;

    public AnalysisAdminService(AnalysisAdminCommandPort commands) {
        this.commands = commands;
    }

    public AnalysisCommandResult createManual(
            UUID publicationId, String metric, String severity, String explanationCode,
            Instant startAt, Instant endAt, Map<String, Object> evidence,
            String actor, UUID correlation, UUID idempotency
    ) {
        if (actor == null || actor.isBlank() || endAt == null || startAt == null || !endAt.isAfter(startAt)
                || evidence == null || evidence.size() > 32) throw new IllegalArgumentException("invalid manual signal");
        String digest = digest(Map.of("publicationId", publicationId, "metric", metric, "severity", severity,
                "explanationCode", explanationCode, "startAt", startAt, "endAt", endAt,
                "evidence", new TreeMap<>(evidence)));
        return commands.createManual(publicationId, metric, severity, explanationCode, startAt, endAt,
                Map.copyOf(evidence), actor, correlation, idempotency, digest);
    }

    public AnalysisCommandResult review(
            UUID findingId, String decision, String privateComment, String actor,
            UUID correlation, UUID idempotency
    ) {
        if (actor == null || actor.isBlank() || (privateComment != null && privateComment.length() > 2000)) {
            throw new IllegalArgumentException("invalid review");
        }
        return commands.review(findingId, decision, privateComment, actor, correlation, idempotency,
                digest(Map.of("findingId", findingId, "decision", decision,
                        "privateComment", privateComment == null ? "" : privateComment)));
    }

    private static String digest(Object value) {
        try {
            byte[] canonical = JSON.writeValueAsBytes(value);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
