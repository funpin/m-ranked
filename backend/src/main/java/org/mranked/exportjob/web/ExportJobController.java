package org.mranked.exportjob.web;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import java.io.IOException;
import java.net.URI;
import java.security.Principal;
import java.util.UUID;
import org.mranked.analytics.domain.Platform;
import org.mranked.exportjob.application.ExportJobService;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/v1/admin/exports")
@PreAuthorize("hasAnyRole('EDITOR', 'ADMIN')")
public class ExportJobController {
    public record CreateRequest(@NotNull @Pattern(regexp = "all|telegram|vk|max|rutube") String platform) {}
    private final ExportJobService jobs;
    public ExportJobController(ExportJobService jobs) { this.jobs = jobs; }

    @PostMapping
    public ResponseEntity<ExportJobService.JobView> create(@Valid @RequestBody CreateRequest request,
                                                          Principal principal) throws IOException {
        var job = jobs.create(principal.getName(), Platform.fromApiValue(request.platform()));
        return ResponseEntity.accepted().location(URI.create("/api/v1/admin/exports/" + job.id()))
                .cacheControl(CacheControl.noStore()).body(job);
    }

    @GetMapping("/{id}")
    public ResponseEntity<ExportJobService.JobView> status(@PathVariable UUID id, Principal principal) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(jobs.status(principal.getName(), id));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<ExportJobService.JobView> cancel(@PathVariable UUID id, Principal principal) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(jobs.cancel(principal.getName(), id));
    }

    @GetMapping(value = "/{id}/download", produces = "text/csv")
    public ResponseEntity<StreamingResponseBody> download(@PathVariable UUID id, Principal principal) throws IOException {
        var artifact = jobs.download(principal.getName(), id);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .contentType(MediaType.parseMediaType("text/csv;charset=UTF-8"))
                .contentLength(artifact.size())
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"publications-" + artifact.platform() + ".csv\"")
                .header("X-Dataset-Revision", Long.toString(artifact.revision()))
                .body(artifact::transferTo);
    }

    @ExceptionHandler(ExportJobService.ExportNotReadyException.class)
    public ResponseEntity<ProblemDetail> notReady() {
        var problem = ProblemDetail.forStatusAndDetail(org.springframework.http.HttpStatus.CONFLICT, "Export job has no completed, unexpired artifact");
        problem.setType(URI.create("urn:m-ranked:problem:export-not-ready"));
        return ResponseEntity.status(409).cacheControl(CacheControl.noStore())
                .contentType(MediaType.APPLICATION_PROBLEM_JSON).body(problem);
    }
}
