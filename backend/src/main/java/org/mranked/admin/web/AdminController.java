package org.mranked.admin.web;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import java.security.Principal;
import java.util.UUID;
import org.mranked.admin.application.AdminService;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {
    static final String CORRELATION_HEADER = "X-Correlation-Id";

    private final AdminService adminService;

    public AdminController(AdminService adminService) {
        this.adminService = adminService;
    }

    @GetMapping("/csrf")
    @PreAuthorize("hasAnyRole('VIEWER', 'EDITOR', 'ADMIN')")
    public ResponseEntity<AdminApiModels.Csrf> csrf(CsrfToken csrfToken) {
        return noStore(new AdminApiModels.Csrf(
                csrfToken.getHeaderName(), csrfToken.getParameterName(), csrfToken.getToken()
        ));
    }

    @GetMapping("/jobs")
    @PreAuthorize("hasAnyRole('VIEWER', 'EDITOR', 'ADMIN')")
    public ResponseEntity<AdminApiModels.JobPage> jobs(
            @RequestParam(defaultValue = "")
            @Pattern(regexp = "|telegram|vk|max|rutube") String platform,
            @RequestParam(defaultValue = "")
            @Pattern(regexp = "|pending|running|succeeded|partial|failed|skipped|cancelled")
            String status,
            @RequestParam(defaultValue = "50") @Min(1) @Max(100) int limit
    ) {
        return noStore(AdminApiModels.jobs(adminService.collectionJobs(platform, status, limit)));
    }

    @GetMapping("/jobs/{jobId}")
    @PreAuthorize("hasAnyRole('VIEWER', 'EDITOR', 'ADMIN')")
    public ResponseEntity<AdminApiModels.JobDetail> job(
            @PathVariable UUID jobId,
            @RequestParam(defaultValue = "100") @Min(1) @Max(200) int accountResultLimit
    ) {
        return noStore(AdminApiModels.jobDetail(
                adminService.collectionJob(jobId, accountResultLimit)
        ));
    }

    @GetMapping("/platform-accounts/{accountId}")
    @PreAuthorize("hasAnyRole('VIEWER', 'EDITOR', 'ADMIN')")
    public ResponseEntity<AdminApiModels.PlatformAccountState> platformAccount(
            @PathVariable UUID accountId
    ) {
        return noStore(AdminApiModels.platformAccount(adminService.platformAccount(accountId)));
    }

    @PutMapping("/platform-accounts/{accountId}/enabled")
    @PreAuthorize("hasAnyRole('EDITOR', 'ADMIN')")
    public ResponseEntity<AdminApiModels.SetEnabledResponse> setEnabled(
            @PathVariable UUID accountId,
            @Valid @RequestBody AdminApiModels.SetEnabledRequest request,
            @RequestHeader(value = CORRELATION_HEADER, required = false) String correlationHeader,
            Principal principal
    ) {
        if (request.enabled() == null || request.expectedRowVersion() == null
                || request.expectedRowVersion() < 0) {
            throw new IllegalArgumentException("enabled and a non-negative expectedRowVersion are required");
        }
        UUID correlationId = correlationId(correlationHeader);
        var result = adminService.setPlatformAccountEnabled(
                accountId,
                request.enabled(),
                request.expectedRowVersion(),
                principal == null ? null : principal.getName(),
                correlationId
        );
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(CORRELATION_HEADER, correlationId.toString())
                .body(AdminApiModels.enabled(result, correlationId));
    }

    private static UUID correlationId(String supplied) {
        if (supplied == null || supplied.isBlank()) {
            return UUID.randomUUID();
        }
        if (supplied.length() > 36) {
            throw new IllegalArgumentException("correlation id must be a UUID");
        }
        try {
            return UUID.fromString(supplied);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("correlation id must be a UUID");
        }
    }

    private static <T> ResponseEntity<T> noStore(T body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }
}
