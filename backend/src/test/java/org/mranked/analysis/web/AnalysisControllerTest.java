package org.mranked.analysis.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.analysis.application.AnalysisQueryPort;
import org.mranked.analysis.application.AnalysisService;
import org.mranked.analysis.application.AnalysisSnapshot;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.web.Rfc9457ExceptionHandler;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;

class AnalysisControllerTest {
    private static final UUID PUBLICATION = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private StubPort port;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        port = new StubPort();
        var service = new AnalysisService(port, () -> new DatasetRevision(20, Instant.EPOCH));
        var validator = new LocalValidatorFactoryBean();
        validator.afterPropertiesSet();
        mvc = MockMvcBuilders.standaloneSetup(new AnalysisController(service))
                .setControllerAdvice(new Rfc9457ExceptionHandler()).setValidator(validator).build();
    }

    @Test
    void returnsIndependentEtagAndHonorsConditionalRequest() throws Exception {
        var response = mvc.perform(get("/api/v1/publications/{id}/anomaly-analysis", PUBLICATION))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "max-age=30, must-revalidate, public"))
                .andExpect(jsonPath("$.analysisRevision").value(4))
                .andExpect(jsonPath("$.sourceDatasetRevision").value(19))
                .andExpect(jsonPath("$.suspicionScore").value(0))
                .andReturn().getResponse();
        String etag = response.getHeader(HttpHeaders.ETAG);
        assertThat(etag).startsWith("\"mr-analysis-");
        mvc.perform(get("/api/v1/publications/{id}/anomaly-analysis", PUBLICATION)
                        .header(HttpHeaders.IF_NONE_MATCH, "W/" + etag))
                .andExpect(status().isNotModified()).andExpect(content().string(""));
    }

    @Test
    void queryShapeChangesEtagAndInvalidLimitIsSafeProblem() throws Exception {
        String first = mvc.perform(get("/api/v1/publications/{id}/anomaly-analysis", PUBLICATION)
                        .param("limit", "25"))
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);
        String second = mvc.perform(get("/api/v1/publications/{id}/anomaly-analysis", PUBLICATION)
                        .param("limit", "50"))
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);
        assertThat(first).isNotEqualTo(second);
        mvc.perform(get("/api/v1/publications/{id}/anomaly-analysis", PUBLICATION).param("limit", "101"))
                .andExpect(status().isBadRequest())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"));
    }

    private static final class StubPort implements AnalysisQueryPort {
        public Optional<UUID> resolvePublication(String id, String type) { return Optional.of(PUBLICATION); }
        public AnalysisSnapshot load(UUID id, int limit, UUID after) {
            return new AnalysisSnapshot(PUBLICATION, 4, 19L, Instant.EPOCH, "ready", Instant.EPOCH,
                    BigDecimal.ZERO, null, false, List.of(), 0, List.of(), null);
        }
    }
}
