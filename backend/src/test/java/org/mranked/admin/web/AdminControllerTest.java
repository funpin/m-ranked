package org.mranked.admin.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.admin.application.AdminCommandRepository;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.AdminQueryRepository;
import org.mranked.admin.application.AdminService;
import org.mranked.admin.application.SetPlatformAccountEnabledCommand;
import org.mranked.admin.application.SetPlatformAccountEnabledOutcome;
import org.mranked.admin.application.SetPlatformAccountEnabledResult;
import org.mranked.admin.domain.AdminAccountResult;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;

class AdminControllerTest {
    private UUID jobId;
    private UUID accountId;
    private StubQueryRepository queries;
    private StubCommandRepository commands;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        jobId = UUID.fromString("10000000-0000-0000-0000-000000000001");
        accountId = UUID.fromString("20000000-0000-0000-0000-000000000001");
        Instant now = Instant.parse("2026-09-03T10:00:00Z");
        AdminJobSummary job = new AdminJobSummary(
                jobId, "telegram", now.minusSeconds(5), now, now.plusSeconds(4),
                "partial", 1, 1,
                UUID.fromString("30000000-0000-0000-0000-000000000001")
        );
        queries = new StubQueryRepository(
                job,
                new AdminJobDetail(
                        job,
                        List.of(new AdminAccountResult(
                                7, accountId, now, now.plusSeconds(4), "failed", 2, 1,
                                "upstream_timeout"
                        )),
                        false
                ),
                new PlatformAccountAdminState(accountId, "telegram", true, 3, now)
        );
        commands = new StubCommandRepository();
        commands.result = new SetPlatformAccountEnabledResult(
                SetPlatformAccountEnabledOutcome.UPDATED,
                new PlatformAccountAdminState(accountId, "telegram", false, 4, now),
                99L
        );
        AdminService service = new AdminService(queries, commands);
        LocalValidatorFactoryBean validator = new LocalValidatorFactoryBean();
        validator.afterPropertiesSet();
        mvc = MockMvcBuilders.standaloneSetup(new AdminController(service))
                .setControllerAdvice(new AdminRfc9457ExceptionHandler())
                .setValidator(validator)
                .build();
    }

    @Test
    void returnsBoundedSanitizedCollectionStatusWithoutCaching() throws Exception {
        mvc.perform(get("/api/v1/admin/jobs").param("platform", "telegram"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(jsonPath("$.items[0].kind").value("collection"))
                .andExpect(jsonPath("$.items[0].jobId").value(jobId.toString()))
                .andExpect(jsonPath("$.items[0].errorCount").value(1));

        mvc.perform(get("/api/v1/admin/jobs/{id}", jobId))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(jsonPath("$.accountResults[0].sanitizedErrorCode")
                        .value("upstream_timeout"))
                .andExpect(content().string(org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString("raw_payload")
                )));
    }

    @Test
    void enableCommandReturnsRevisionAndCorrelationWithoutCaching() throws Exception {
        UUID correlationId = UUID.fromString("40000000-0000-0000-0000-000000000001");
        mvc.perform(put("/api/v1/admin/platform-accounts/{id}/enabled", accountId)
                        .principal(() -> "editor@example.test")
                        .header(AdminController.CORRELATION_HEADER, correlationId.toString())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\":false,\"expectedRowVersion\":3}"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(header().string(AdminController.CORRELATION_HEADER,
                        correlationId.toString()))
                .andExpect(jsonPath("$.changed").value(true))
                .andExpect(jsonPath("$.datasetRevision").value(99))
                .andExpect(jsonPath("$.account.rowVersion").value(4));
        org.assertj.core.api.Assertions.assertThat(commands.command.actor())
                .isEqualTo("editor@example.test");
    }

    @Test
    void returnsMinimalPlatformAccountStateWithoutCachingOrIdentitySecrets() throws Exception {
        mvc.perform(get("/api/v1/admin/platform-accounts/{id}", accountId))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(jsonPath("$.accountId").value(accountId.toString()))
                .andExpect(jsonPath("$.platform").value("telegram"))
                .andExpect(jsonPath("$.enabled").value(true))
                .andExpect(jsonPath("$.rowVersion").value(3))
                .andExpect(jsonPath("$.updatedAt").value("2026-09-03T10:00:00Z"))
                .andExpect(content().string(org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString("canonicalExternalId")
                )))
                .andExpect(content().string(org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString("currentUrl")
                )));

        queries.account = null;
        mvc.perform(get("/api/v1/admin/platform-accounts/{id}", accountId))
                .andExpect(status().isNotFound())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:not-found"));

        queries.unavailable = true;
        mvc.perform(get("/api/v1/admin/platform-accounts/{id}", accountId))
                .andExpect(status().isServiceUnavailable())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:admin-unavailable"));
    }

    @Test
    void invalidCorrelationAndOptimisticConflictAreRfc9457Problems() throws Exception {
        mvc.perform(put("/api/v1/admin/platform-accounts/{id}/enabled", accountId)
                        .principal(() -> "editor")
                        .header(AdminController.CORRELATION_HEADER, "not-a-uuid")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\":false,\"expectedRowVersion\":3}"))
                .andExpect(status().isBadRequest())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:invalid-request"));

        commands.result = new SetPlatformAccountEnabledResult(
                SetPlatformAccountEnabledOutcome.VERSION_CONFLICT, null, null
        );
        mvc.perform(put("/api/v1/admin/platform-accounts/{id}/enabled", accountId)
                        .principal(() -> "editor")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\":false,\"expectedRowVersion\":3}"))
                .andExpect(status().isConflict())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:optimistic-lock"));
    }

    private static final class StubQueryRepository implements AdminQueryRepository {
        private final AdminJobSummary job;
        private final AdminJobDetail detail;
        private PlatformAccountAdminState account;
        private boolean unavailable;

        private StubQueryRepository(
                AdminJobSummary job,
                AdminJobDetail detail,
                PlatformAccountAdminState account
        ) {
            this.job = job;
            this.detail = detail;
            this.account = account;
        }

        @Override
        public List<AdminJobSummary> findCollectionJobs(String platform, String status, int limit) {
            return List.of(job);
        }

        @Override
        public Optional<AdminJobDetail> findCollectionJob(UUID jobId, int accountResultLimit) {
            return Optional.of(detail);
        }

        @Override
        public Optional<PlatformAccountAdminState> findPlatformAccount(UUID accountId) {
            if (unavailable) {
                throw new AdminDatabaseUnavailableException();
            }
            return account != null && account.accountId().equals(accountId)
                    ? Optional.of(account)
                    : Optional.empty();
        }
    }

    private static final class StubCommandRepository implements AdminCommandRepository {
        private SetPlatformAccountEnabledCommand command;
        private SetPlatformAccountEnabledResult result;

        @Override
        public SetPlatformAccountEnabledResult setPlatformAccountEnabled(
                SetPlatformAccountEnabledCommand command
        ) {
            this.command = command;
            return result;
        }
    }
}
