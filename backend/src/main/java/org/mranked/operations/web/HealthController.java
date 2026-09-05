package org.mranked.operations.web;

import java.util.LinkedHashMap;
import java.util.Map;
import org.mranked.operations.application.ReadinessService;
import org.mranked.operations.domain.ProbeStatus;
import org.mranked.operations.domain.ReadinessResult;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/health")
public class HealthController {
    private final ReadinessService readinessService;

    public HealthController(ReadinessService readinessService) {
        this.readinessService = readinessService;
    }

    @GetMapping("/live")
    public ResponseEntity<Map<String, Object>> liveness() {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(Map.of("status", ProbeStatus.UP.name()));
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> readiness() {
        ReadinessResult result = readinessService.status();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", result.status().name());
        if (result.datasetRevision() != null) {
            body.put("datasetRevision", result.datasetRevision());
        }
        HttpStatus status = result.status() == ProbeStatus.UP
                ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE;
        return ResponseEntity.status(status)
                .cacheControl(CacheControl.noStore())
                .body(body);
    }
}
