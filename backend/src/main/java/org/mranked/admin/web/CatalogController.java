package org.mranked.admin.web;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.security.Principal;
import java.util.List;
import java.util.UUID;
import org.mranked.admin.application.CatalogService;
import org.mranked.admin.domain.CatalogCommandResult;
import org.mranked.admin.domain.ManagedInstitution;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/admin/catalog")
@Validated
public class CatalogController {
    private final CatalogService service;
    private final org.mranked.admin.application.LegacyCatalogService legacy;
    private final org.mranked.admin.application.CatalogStatusPort status;
    public CatalogController(CatalogService service,org.mranked.admin.application.LegacyCatalogService legacy,
            org.mranked.admin.application.CatalogStatusPort status) { this.service=service;this.legacy=legacy;this.status=status; }
    public record InstitutionRequest(@NotBlank @Size(max=1000) String name,@Size(max=1000) String shortName,Long expectedRowVersion) { }
    public record AccountRequest(@NotNull UUID institutionId,Long expectedRowVersion,@NotBlank String platform,
            @NotBlank @Size(max=2048) String reference,@Size(max=1000) String title,@Size(max=2048) String url) { }
    public record AccountCommand(@NotNull @Min(0) Long expectedRowVersion,@Size(max=200) String nativeId) { }
    public record CatalogPage(List<ManagedInstitution> items,Long nextAfter) { }
    public record CatalogAccountPage(List<org.mranked.admin.domain.ManagedAccount> items,Long nextAfter) { }
    public record LegacyCommandRequest(@NotBlank @Size(max=200) String path,@NotNull java.util.Map<String,String> fields) { }
    public record LegacyCommandResponse(String location) { }
    public record CatalogSession(String headerName,String token,boolean canEdit,boolean canDelete) { }
    @GetMapping("/status")
    @PreAuthorize("hasAnyRole('VIEWER','EDITOR','ADMIN')")
    public ResponseEntity<org.mranked.admin.domain.CatalogStatus> status() { return noStore(status.status()); }

    @GetMapping("/session")
    @PreAuthorize("hasAnyRole('VIEWER','EDITOR','ADMIN')")
    public ResponseEntity<CatalogSession> session(org.springframework.security.web.csrf.CsrfToken csrf,
            org.springframework.security.core.Authentication authentication) {
        var roles=authentication.getAuthorities().stream().map(value->value.getAuthority()).toList();
        return noStore(new CatalogSession(csrf.getHeaderName(),csrf.getToken(),roles.contains("ROLE_ADMIN")||roles.contains("ROLE_EDITOR"),roles.contains("ROLE_ADMIN")));
    }
    @PostMapping("/legacy-command")
    @PreAuthorize("hasAnyRole('EDITOR','ADMIN')")
    public ResponseEntity<LegacyCommandResponse> legacy(@Valid @RequestBody LegacyCommandRequest body,
            @RequestHeader("X-Correlation-Id") UUID correlation,org.springframework.security.core.Authentication authentication) {
        if(body.path().endsWith("/delete") && authentication.getAuthorities().stream().noneMatch(role->role.getAuthority().equals("ROLE_ADMIN")))
            throw new org.springframework.security.access.AccessDeniedException("Administrator role is required");
        return noStore(new LegacyCommandResponse(legacy.execute(body.path(),body.fields(),authentication.getName(),correlation)));
    }

    @GetMapping("/institutions")
    @PreAuthorize("hasAnyRole('VIEWER','EDITOR','ADMIN')")
    public ResponseEntity<CatalogPage> institutions(@RequestParam(defaultValue="0") @Min(0) long after,
            @RequestParam(defaultValue="100") @Min(1) @Max(200) int limit) {
        var items=service.institutions(after,limit);
        return noStore(new CatalogPage(items,items.size()==limit?items.getLast().legacyId():null));
    }
    @GetMapping("/institutions/{id}/accounts")
    @PreAuthorize("hasAnyRole('VIEWER','EDITOR','ADMIN')")
    public ResponseEntity<CatalogAccountPage> accounts(@PathVariable UUID id,@RequestParam(defaultValue="0") @Min(0) long after,
            @RequestParam(defaultValue="100") @Min(1) @Max(200) int limit) {
        var items=service.accounts(id,after,limit);
        return noStore(new CatalogAccountPage(items,items.size()==limit?items.getLast().legacyId():null));
    }
    @PostMapping("/institutions")
    @PreAuthorize("hasAnyRole('EDITOR','ADMIN')")
    public ResponseEntity<CatalogCommandResult> create(@Valid @RequestBody InstitutionRequest body,
            @RequestHeader("X-Correlation-Id") UUID correlation,Principal actor) {
        return noStore(service.createInstitution(body.name(),body.shortName(),actor.getName(),correlation));
    }
    @PutMapping("/institutions/{id}")
    @PreAuthorize("hasAnyRole('EDITOR','ADMIN')")
    public ResponseEntity<CatalogCommandResult> update(@PathVariable UUID id,@Valid @RequestBody InstitutionRequest body,
            @RequestHeader("X-Correlation-Id") UUID correlation,Principal actor) {
        if(body.expectedRowVersion()==null) throw new IllegalArgumentException("Expected row version is required");
        return noStore(service.updateInstitution(id,body.expectedRowVersion(),body.name(),body.shortName(),actor.getName(),correlation));
    }
    @DeleteMapping("/institutions/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<CatalogCommandResult> delete(@PathVariable UUID id,@RequestParam @Min(0) long expectedRowVersion,
            @RequestHeader("X-Correlation-Id") UUID correlation,Principal actor) {
        return noStore(service.deleteInstitution(id,expectedRowVersion,actor.getName(),correlation));
    }
    @PostMapping("/accounts")
    @PreAuthorize("hasAnyRole('EDITOR','ADMIN')")
    public ResponseEntity<CatalogCommandResult> account(@Valid @RequestBody AccountRequest body,
            @RequestHeader("X-Correlation-Id") UUID correlation,Principal actor) {
        return noStore(service.versionedAccount(body.institutionId(),body.expectedRowVersion(),body.platform(),body.reference(),body.title(),body.url(),actor.getName(),correlation));
    }
    @PostMapping("/accounts/{id}/{operation:enable|disable|native-id}")
    @PreAuthorize("hasAnyRole('EDITOR','ADMIN')")
    public ResponseEntity<CatalogCommandResult> accountCommand(@PathVariable UUID id,@PathVariable String operation,
            @Valid @RequestBody AccountCommand body,@RequestHeader("X-Correlation-Id") UUID correlation,Principal actor) {
        return noStore(service.accountCommand(id,body.expectedRowVersion(),operation.replace('-','_'),body.nativeId(),actor.getName(),correlation));
    }
    @DeleteMapping("/accounts/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<CatalogCommandResult> deleteAccount(@PathVariable UUID id,@RequestParam @Min(0) long expectedRowVersion,
            @RequestHeader("X-Correlation-Id") UUID correlation,Principal actor) {
        return noStore(service.accountCommand(id,expectedRowVersion,"delete",null,actor.getName(),correlation));
    }
    private static <T> ResponseEntity<T> noStore(T body) { return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body); }
}
