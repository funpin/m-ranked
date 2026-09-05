package org.mranked.admin.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.admin.domain.AdminJobDetail;
import org.mranked.admin.domain.AdminJobSummary;
import org.mranked.admin.domain.PlatformAccountAdminState;

class AdminServiceTest {
    private StubQueryRepository queries;
    private StubCommandRepository commands;
    private AdminService service;

    @BeforeEach
    void setUp() {
        queries = new StubQueryRepository();
        commands = new StubCommandRepository();
        service = new AdminService(queries, commands);
    }

    @Test
    void normalizesAndBoundsCollectionJobFilters() {
        service.collectionJobs(" Telegram ", " RUNNING ", 25);

        assertThat(queries.platform).isEqualTo("telegram");
        assertThat(queries.status).isEqualTo("running");
        assertThat(queries.limit).isEqualTo(25);
        assertThatThrownBy(() -> service.collectionJobs("all", "", 25))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.collectionJobs("", "", 101))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void missingJobGetsAStableNotFoundFailure() {
        assertThatThrownBy(() -> service.collectionJob(UUID.randomUUID(), 100))
                .isInstanceOf(AdminResourceNotFoundException.class)
                .hasMessage("Collection job was not found");
    }

    @Test
    void accountReadReturnsOnlyTheCurrentAdministrativeState() {
        UUID accountId = UUID.randomUUID();
        PlatformAccountAdminState expected = new PlatformAccountAdminState(
                accountId, "rutube", true, 12, Instant.parse("2026-09-03T10:00:00Z")
        );
        queries.account = expected;

        assertThat(service.platformAccount(accountId)).isEqualTo(expected);
        assertThat(queries.accountId).isEqualTo(accountId);
        assertThatThrownBy(() -> service.platformAccount(UUID.randomUUID()))
                .isInstanceOf(AdminResourceNotFoundException.class)
                .hasMessage("Platform account was not found");
        assertThatThrownBy(() -> service.platformAccount(null))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void commandUsesSanitizedActorAndReturnsUpdatedState() {
        UUID accountId = UUID.randomUUID();
        UUID correlationId = UUID.randomUUID();
        PlatformAccountAdminState account = new PlatformAccountAdminState(
                accountId, "vk", false, 8, Instant.parse("2026-09-03T10:00:00Z")
        );
        commands.result = new SetPlatformAccountEnabledResult(
                SetPlatformAccountEnabledOutcome.UPDATED, account, 91L
        );

        SetPlatformAccountEnabledResult result = service.setPlatformAccountEnabled(
                accountId, false, 7, " editor@example.test ", correlationId
        );

        assertThat(result.datasetRevision()).isEqualTo(91L);
        assertThat(commands.command.actor()).isEqualTo("editor@example.test");
        assertThat(commands.command.expectedRowVersion()).isEqualTo(7);
        assertThat(commands.command.correlationId()).isEqualTo(correlationId);
    }

    @Test
    void conflictAndMissingOutcomesBecomeTypedFailuresAfterTheRepositoryAuditsThem() {
        commands.result = new SetPlatformAccountEnabledResult(
                SetPlatformAccountEnabledOutcome.VERSION_CONFLICT, null, null
        );
        assertThatThrownBy(() -> service.setPlatformAccountEnabled(
                UUID.randomUUID(), false, 0, "editor", UUID.randomUUID()
        )).isInstanceOf(AdminOptimisticLockException.class);

        commands.result = new SetPlatformAccountEnabledResult(
                SetPlatformAccountEnabledOutcome.NOT_FOUND, null, null
        );
        assertThatThrownBy(() -> service.setPlatformAccountEnabled(
                UUID.randomUUID(), false, 0, "editor", UUID.randomUUID()
        )).isInstanceOf(AdminResourceNotFoundException.class);
    }

    @Test
    void rejectsUnsafeActorAndNegativeVersionBeforeCallingTheWritePort() {
        assertThatThrownBy(() -> service.setPlatformAccountEnabled(
                UUID.randomUUID(), true, -1, "editor", UUID.randomUUID()
        )).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.setPlatformAccountEnabled(
                UUID.randomUUID(), true, 0, "editor\nforged", UUID.randomUUID()
        )).isInstanceOf(IllegalArgumentException.class);
        assertThat(commands.command).isNull();
    }

    private static final class StubQueryRepository implements AdminQueryRepository {
        private String platform;
        private String status;
        private int limit;
        private UUID accountId;
        private PlatformAccountAdminState account;

        @Override
        public List<AdminJobSummary> findCollectionJobs(String platform, String status, int limit) {
            this.platform = platform;
            this.status = status;
            this.limit = limit;
            return List.of();
        }

        @Override
        public Optional<AdminJobDetail> findCollectionJob(UUID jobId, int accountResultLimit) {
            return Optional.empty();
        }

        @Override
        public Optional<PlatformAccountAdminState> findPlatformAccount(UUID accountId) {
            this.accountId = accountId;
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
