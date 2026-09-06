package org.mranked.operations.web;

import java.util.Map;
import org.mranked.operations.application.LegacyHealthService;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public final class LegacyHealthController {
    private final LegacyHealthService service;
    public LegacyHealthController(LegacyHealthService service) {this.service=service;}
    @GetMapping("/api/v1/health/legacy")
    public ResponseEntity<Map<String,Object>> legacy() {
        try {return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(service.legacy());}
        catch(RuntimeException unavailable) {return unavailable();}
    }
    @GetMapping("/api/v1/health/freshness")
    public ResponseEntity<Map<String,Object>> freshness() {
        try {
            var body=service.freshness();return ResponseEntity.status("UP".equals(body.get("status"))?200:503)
                    .cacheControl(CacheControl.noStore()).body(body);
        } catch(RuntimeException unavailable) {return unavailable();}
    }
    private ResponseEntity<Map<String,Object>> unavailable() {
        return ResponseEntity.status(503).cacheControl(CacheControl.noStore()).body(Map.of("status","DOWN"));
    }
}
