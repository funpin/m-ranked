package org.mranked.analysis.web;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.security.Principal;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.mranked.analysis.application.AnalysisAdminService;
import org.mranked.analysis.application.AnalysisCommandResult;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin")
public class AnalysisAdminController {
    private final AnalysisAdminService service;

    public AnalysisAdminController(AnalysisAdminService service) {
        this.service = service;
    }

    @PostMapping("/publications/{publicationId}/anomaly-signals")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<AnalysisCommandResult> create(
            @PathVariable UUID publicationId, @Valid @RequestBody ManualSignalRequest request,
            @RequestHeader("Idempotency-Key") UUID idempotency,
            @RequestHeader(value = "X-Correlation-Id", required = false) UUID correlation,
            Principal principal
    ) {
        UUID actualCorrelation = correlation == null ? UUID.randomUUID() : correlation;
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).header("X-Correlation-Id", actualCorrelation.toString())
                .body(service.createManual(publicationId, request.metric(), request.severity(), request.explanationCode(),
                        request.suspiciousStartAt(), request.suspiciousEndAt(), request.evidence(),
                        principal == null ? null : principal.getName(), actualCorrelation, idempotency));
    }

    @PostMapping("/anomaly-signals/{findingId}/reviews")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<AnalysisCommandResult> review(
            @PathVariable UUID findingId, @Valid @RequestBody ReviewRequest request,
            @RequestHeader("Idempotency-Key") UUID idempotency,
            @RequestHeader(value = "X-Correlation-Id", required = false) UUID correlation,
            Principal principal
    ) {
        UUID actualCorrelation = correlation == null ? UUID.randomUUID() : correlation;
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).header("X-Correlation-Id", actualCorrelation.toString())
                .body(service.review(findingId, request.decision(), request.privateComment(),
                        principal == null ? null : principal.getName(), actualCorrelation, idempotency));
    }

    public record ManualSignalRequest(
            @NotBlank @Pattern(regexp = "views|reactions|comments|shares") String metric,
            @NotBlank @Pattern(regexp = "low|medium|high") String severity,
            @NotBlank @Pattern(regexp = "[a-z0-9_]{1,80}") String explanationCode,
            @NotNull Instant suspiciousStartAt, @NotNull Instant suspiciousEndAt,
            @NotNull @Size(max = 32) Map<String, Object> evidence
    ) {
    }

    public record ReviewRequest(
            @NotBlank @Pattern(regexp = "explained|unresolved|data_error|dismissed") String decision,
            @Size(max = 2000) String privateComment
    ) {
    }
}
