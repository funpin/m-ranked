package org.mranked.legacyexport.web;

import java.io.IOException;
import org.mranked.legacyexport.application.LegacyCsvFormat;
import org.mranked.legacyexport.application.LegacyCsvService;
import org.mranked.legacyexport.application.LegacyCsvUnavailable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
public class LegacyCsvController {
    private final LegacyCsvService service;
    public LegacyCsvController(LegacyCsvService service) {this.service = service;}
    @GetMapping(value = "/api/v1/legacy-exports/{kind:snapshots|posts}.csv", produces = "text/csv")
    public ResponseEntity<StreamingResponseBody> export(@PathVariable String kind,
            @RequestParam org.springframework.util.MultiValueMap<String,String> parameters) throws IOException {
        var platforms = parameters.get("platform");
        String platform = platforms == null || platforms.isEmpty() ? "telegram" : platforms.getLast();
        var format = new LegacyCsvFormat(kind, platform);
        var artifact = service.prepare(format);
        return ResponseEntity.ok().header(HttpHeaders.CACHE_CONTROL, "no-store")
            .header(HttpHeaders.CONTENT_TYPE, "text/csv; charset=utf-8")
            .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + format.filename() + "\"")
            .header("X-Dataset-Revision", Long.toString(artifact.revision().id()))
            .header(HttpHeaders.CONTENT_LENGTH, Long.toString(java.nio.file.Files.size(artifact.path())))
            .body(artifact::transferTo);
    }
    @ExceptionHandler(LegacyCsvUnavailable.class)
    ResponseEntity<ProblemDetail> unavailable(LegacyCsvUnavailable failure) {
        var problem = ProblemDetail.forStatusAndDetail(org.springframework.http.HttpStatus.CONFLICT, "Exact legacy CSV cannot be produced from this published revision.");
        problem.setTitle("Legacy export compatibility unavailable"); problem.setProperty("code", failure.code());
        return ResponseEntity.status(409).header(HttpHeaders.CACHE_CONTROL, "no-store").body(problem);
    }
}
