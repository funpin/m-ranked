package org.mranked.analysis.web;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import org.mranked.analysis.application.AnalysisService;
import org.mranked.analysis.domain.PublicationAnalysis;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/publications")
public class AnalysisController {
    private static final CacheControl CACHE = CacheControl.maxAge(Duration.ofSeconds(30)).mustRevalidate().cachePublic();
    private final AnalysisService service;

    public AnalysisController(AnalysisService service) {
        this.service = service;
    }

    @GetMapping("/{id}/anomaly-analysis")
    public ResponseEntity<?> analysis(
            @PathVariable String id,
            @RequestParam(defaultValue = "posts") @Pattern(regexp = "posts|platform_posts") String legacyType,
            @RequestParam(defaultValue = "25") @Min(1) @Max(100) int limit,
            @RequestParam(required = false) @Size(max = 512) String cursor,
            @RequestHeader(value = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        PublicationAnalysis result = service.get(id, legacyType, limit, cursor);
        String etag = etag(result, legacyType, limit, cursor);
        if (matches(ifNoneMatch, etag)) return ResponseEntity.status(304).cacheControl(CACHE).eTag(etag).build();
        return ResponseEntity.ok().cacheControl(CACHE).eTag(etag).body(result);
    }

    static String etag(PublicationAnalysis result, String legacyType, int limit, String cursor) {
        String identity = result.publicationId() + ":" + result.datasetRevision() + ":"
                + result.analysisRevision() + ":" + legacyType + ":" + limit + ":"
                + (cursor == null ? "" : cursor) + ":v1";
        try {
            String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(identity.getBytes(StandardCharsets.UTF_8))).substring(0, 24);
            return "\"mr-analysis-" + digest + "\"";
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private static boolean matches(String supplied, String etag) {
        if (supplied == null) return false;
        for (String value : supplied.split(",")) {
            String normalized = value.trim();
            if (normalized.startsWith("W/")) normalized = normalized.substring(2).trim();
            if (normalized.equals("*") || normalized.equals(etag)) return true;
        }
        return false;
    }
}
