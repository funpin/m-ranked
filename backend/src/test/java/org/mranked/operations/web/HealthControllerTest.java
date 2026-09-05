package org.mranked.operations.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.mranked.operations.application.ReadinessService;
import org.mranked.operations.domain.ReadinessResult;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class HealthControllerTest {
    @Test
    void livenessDoesNotDependOnDatabase() throws Exception {
        MockMvc mvc = mvc(new ReadinessService(() -> {
            throw new AssertionError("liveness must not invoke the readiness probe");
        }));

        mvc.perform(get("/api/v1/health/live"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.status").value("UP"));
    }

    @Test
    void readinessExposesOnlyStatusAndRevision() throws Exception {
        MockMvc mvc = mvc(new ReadinessService(() -> ReadinessResult.up(44)));

        mvc.perform(get("/api/v1/health/ready"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.datasetRevision").value(44));
    }

    @Test
    void failedReadinessIsServiceUnavailableWithoutInternalDetails() throws Exception {
        MockMvc mvc = mvc(new ReadinessService(ReadinessResult::down));

        mvc.perform(get("/api/v1/health/ready"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.status").value("DOWN"))
                .andExpect(jsonPath("$.datasetRevision").doesNotExist())
                .andExpect(jsonPath("$.error").doesNotExist());
    }

    private static MockMvc mvc(ReadinessService readinessService) {
        return MockMvcBuilders.standaloneSetup(new HealthController(readinessService)).build();
    }
}
