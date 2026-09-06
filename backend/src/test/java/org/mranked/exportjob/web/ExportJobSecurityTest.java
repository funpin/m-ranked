package org.mranked.exportjob.web;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.security.test.web.servlet.setup.SecurityMockMvcConfigurers.springSecurity;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Files;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.admin.infrastructure.ApiSecurityConfiguration;
import org.mranked.admin.infrastructure.ProblemSecurityHandler;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.exportjob.application.ExportJobGenerator;
import org.mranked.exportjob.application.ExportJobPolicy;
import org.mranked.exportjob.application.ExportJobService;
import org.mranked.query.domain.PublicationCsvRow;
import org.mranked.query.web.Rfc9457ExceptionHandler;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.junit.jupiter.web.SpringJUnitWebConfig;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

@SpringJUnitWebConfig(ExportJobSecurityTest.Config.class)
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class ExportJobSecurityTest {
    @Autowired WebApplicationContext context;
    @Autowired ExportJobService jobs;
    MockMvc mvc;

    @BeforeEach void setup() { mvc = MockMvcBuilders.webAppContextSetup(context).apply(springSecurity()).build(); }

    @Test
    void anonymousViewerAndMissingCsrfCannotCreateOrReadJobs() throws Exception {
        UUID id = UUID.randomUUID();
        mvc.perform(get("/api/v1/admin/exports/{id}", id)).andExpect(status().isUnauthorized())
                .andExpect(header().string("Cache-Control", "no-store"));
        mvc.perform(post("/api/v1/admin/exports").with(csrf()).with(user("viewer").roles("VIEWER"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"platform\":\"vk\"}"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/api/v1/admin/exports").with(user("editor").roles("EDITOR"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"platform\":\"vk\"}"))
                .andExpect(status().isForbidden());
        mvc.perform(delete("/api/v1/admin/exports/{id}", id).with(user("editor").roles("EDITOR")))
                .andExpect(status().isForbidden());
    }

    @Test
    void editorLifecycleIsOwnerScopedNoStoreAndRevisioned() throws Exception {
        String owner = "editor-" + UUID.randomUUID();
        var response = mvc.perform(post("/api/v1/admin/exports").with(user(owner).roles("EDITOR")).with(csrf())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"platform\":\"vk\"}"))
                .andExpect(status().isAccepted()).andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.datasetRevision").value(17)).andReturn().getResponse();
        String location = response.getHeader("Location");
        UUID id = UUID.fromString(location.substring(location.lastIndexOf('/') + 1));
        try {
            long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
            while (jobs.status(owner, id).state() != ExportJobService.State.succeeded && System.nanoTime() < deadline) Thread.sleep(5);
            mvc.perform(get(location).with(user(owner).roles("EDITOR"))).andExpect(status().isOk())
                    .andExpect(jsonPath("$.state").value("succeeded")).andExpect(jsonPath("$.rowsWritten").value(1));
            mvc.perform(get(location).with(user("another-admin").roles("ADMIN"))).andExpect(status().isNotFound());
            mvc.perform(get(location + "/download").with(user("another-editor").roles("EDITOR")))
                    .andExpect(status().isNotFound());
            var download = mvc.perform(get(location + "/download").with(user(owner).roles("EDITOR")))
                    .andExpect(status().isOk()).andExpect(header().string("X-Dataset-Revision", "17"))
                    .andExpect(header().string("Cache-Control", "no-store")).andReturn();
            mvc.perform(asyncDispatch(download)).andExpect(status().isOk())
                    .andExpect(content().string(org.hamcrest.Matchers.containsString(",0,,,,exact,17\r\n")));
            mvc.perform(delete(location).with(user(owner).roles("EDITOR")).with(csrf()))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.state").value("cancelled"));
            mvc.perform(get(location + "/download").with(user(owner).roles("EDITOR")))
                    .andExpect(status().isConflict()).andExpect(header().string("Cache-Control", "no-store"));
        } finally { jobs.cancel(owner, id); }
    }

    @Test
    void malformedPlatformAndUuidAreBoundedProblems() throws Exception {
        mvc.perform(post("/api/v1/admin/exports").with(user("editor").roles("EDITOR")).with(csrf())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"platform\":\"vk;secret\"}"))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON));
        mvc.perform(get("/api/v1/admin/exports/not-an-id").with(user("editor").roles("EDITOR")))
                .andExpect(status().isBadRequest());
    }

    @Configuration @EnableWebMvc
    @Import({ApiSecurityConfiguration.class, ProblemSecurityHandler.class, ExportJobController.class,
            Rfc9457ExceptionHandler.class})
    static class Config {
        @Bean ObjectMapper objectMapper() { return new JsonMapper(); }
        @Bean DatasetRevisionProvider revisions() { return () -> new DatasetRevision(17, Instant.EPOCH); }
        @Bean ExportJobService jobs(DatasetRevisionProvider revisions) throws Exception {
            var generator = new ExportJobGenerator(revisions, (platform, revision, consumer) -> consumer.accept(
                    new PublicationCsvRow("vk", "fixture", UUID.randomUUID(), Instant.EPOCH, Instant.EPOCH,
                            0L, null, null, null, "exact")));
            return new ExportJobService(generator, revisions, Files.createTempDirectory("mranked-export-security-"),
                    ExportJobPolicy.defaults(), Clock.systemUTC());
        }
    }
}
