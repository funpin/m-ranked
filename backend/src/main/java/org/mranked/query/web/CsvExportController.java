package org.mranked.query.web;

import jakarta.validation.constraints.Pattern;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.application.CsvExportService;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@Validated
@RestController
@RequestMapping("/api/v1/exports")
public class CsvExportController {
    private final CsvExportService exportService;

    public CsvExportController(CsvExportService exportService) {
        this.exportService = exportService;
    }

    @GetMapping(value = "/publications.csv", produces = "text/csv")
    public ResponseEntity<StreamingResponseBody> publications(
            @RequestParam(defaultValue = "all")
            @Pattern(regexp = "all|telegram|vk|max|rutube") String platform
    ) {
        Platform parsedPlatform = Platform.fromApiValue(platform);
        var revision = exportService.currentRevision();
        StreamingResponseBody body = output -> exportService.write(parsedPlatform, revision, output);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .contentType(MediaType.parseMediaType("text/csv;charset=UTF-8"))
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"publications-" + platform + ".csv\"")
                .header("X-Dataset-Revision", Long.toString(revision.id()))
                .body(body);
    }
}
