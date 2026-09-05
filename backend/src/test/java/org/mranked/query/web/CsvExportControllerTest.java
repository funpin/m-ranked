package org.mranked.query.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.application.CsvExportService;
import org.mranked.query.application.PublicationCsvRowSource;
import org.mranked.query.domain.PublicationCsvRow;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.RequestMapping;

class CsvExportControllerTest {
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        DatasetRevision revision = new DatasetRevision(91, Instant.parse("2026-09-03T10:00:00Z"));
        DatasetRevisionProvider revisions = () -> revision;
        PublicationCsvRowSource rows = (platform, datasetRevision, consumer) -> consumer.accept(
                new PublicationCsvRow(
                        platform.databaseValue(), "North University",
                        UUID.fromString("00000000-0000-0000-0000-000000000091"),
                        Instant.parse("2026-09-01T10:00:00Z"),
                        Instant.parse("2026-09-03T09:00:00Z"),
                        100L, 7L, null, 2L, "exact"
                )
        );
        var service = new CsvExportService(rows, revisions);
        mvc = MockMvcBuilders.standaloneSetup(new CsvExportController(service))
                .setControllerAdvice(new Rfc9457ExceptionHandler())
                .build();
    }

    @Test
    void streamsUtf8CsvWithPinnedRevisionHeaders() throws Exception {
        MvcResult started = mvc.perform(get("/api/v1/exports/publications.csv")
                        .param("platform", "telegram"))
                .andExpect(request().asyncStarted())
                .andReturn();

        mvc.perform(asyncDispatch(started))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(header().string("X-Dataset-Revision", "91"))
                .andExpect(header().string(
                        HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"publications-telegram.csv\""
                ))
                .andExpect(content().contentType("text/csv;charset=UTF-8"))
                .andExpect(content().string(org.hamcrest.Matchers.containsString(
                        "telegram,North University,00000000-0000-0000-0000-000000000091"
                )))
                .andExpect(content().string(org.hamcrest.Matchers.containsString(",100,7,,2,exact,91\r\n")));
    }

    @Test
    void rejectsAnUnsupportedPlatformAsAProblem() throws Exception {
        mvc.perform(get("/api/v1/exports/publications.csv").param("platform", "unknown"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentType("application/problem+json"));
    }

    @Test
    void doesNotSilentlyMountTheModernProjectionAtLegacyCsvUrls() {
        RequestMapping mapping = CsvExportController.class.getAnnotation(RequestMapping.class);

        assertThat(mapping.value()).containsExactly("/api/v1/exports");
    }
}
