package org.mranked.query.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.mranked.analytics.domain.CounterMetric;
import org.mranked.analytics.domain.MetricSet;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.catalog.domain.InstitutionIdentity;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.domain.InstitutionView;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.ActivityRatingResult;
import org.mranked.query.domain.ComparisonView;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.ComparisonSelectionType;
import org.mranked.query.domain.InvalidComparisonSelectionException;
import org.mranked.query.domain.OverviewCard;
import org.mranked.query.domain.OverviewMetric;
import org.mranked.query.domain.OverviewQuery;
import org.mranked.query.domain.PublicationView;
import org.mranked.ingestion.domain.PublicationIdentity;

class PublicQueryServiceTest {
    @Test
    void usesOneRevisionAndLimitPlusOneForAKeysetPage() {
        DatasetRevision revision = new DatasetRevision(17, Instant.parse("2026-09-03T10:00:00Z"));
        OverviewCard first = item("00000000-0000-0000-0000-000000000001", 1, "Alpha", "2026-09-03T10:05:00Z");
        OverviewCard second = item("00000000-0000-0000-0000-000000000002", 2, "Beta", "2026-09-03T10:07:00Z");
        OverviewCard lookahead = item("00000000-0000-0000-0000-000000000003", 3, "Gamma", "2026-09-03T10:08:00Z");
        RecordingRepository repository = new RecordingRepository();
        repository.overview = List.of(first, second, lookahead);
        AtomicInteger revisionReads = new AtomicInteger();
        DatasetRevisionProvider revisionProvider = () -> {
            revisionReads.incrementAndGet();
            return revision;
        };
        CursorCodec cursorCodec = new CursorCodec();
        PublicQueryService service = new PublicQueryService(repository, revisionProvider, cursorCodec);

        OverviewQuery query = OverviewQuery.normalized(
                Platform.ALL, PeriodKey.ONE_DAY, "  needle  ", "accounts", "asc"
        );
        var page = service.overview(query, 2, null);

        assertThat(page.items()).containsExactly(first, second);
        assertThat(cursorCodec.decode(page.nextCursor())).contains(second.entityId());
        assertThat(page.datasetRevision()).isEqualTo(17);
        assertThat(page.asOf()).isEqualTo(Instant.parse("2026-09-03T10:07:00Z"));
        assertThat(revisionReads).hasValue(1);
        assertThat(repository.overviewCalls).isEqualTo(1);
        assertThat(repository.platform).isEqualTo(Platform.ALL);
        assertThat(repository.period).isEqualTo(PeriodKey.ONE_DAY);
        assertThat(repository.search).isEqualTo("needle");
        assertThat(repository.overviewQuery.sort()).isEqualTo("accounts");
        assertThat(repository.overviewQuery.direction()).isEqualTo("asc");
        assertThat(repository.fetchLimit).isEqualTo(3);
        assertThat(repository.afterInstitutionId).isNull();
        assertThat(repository.datasetRevision).isEqualTo(17);
    }

    @Test
    void resolvesDetailAgainstTheSelectedRevisionAndReportsMissingAlias() {
        RecordingRepository repository = new RecordingRepository();
        DatasetRevisionProvider revisionProvider = () -> new DatasetRevision(
                23, Instant.parse("2026-09-03T10:00:00Z")
        );
        PublicQueryService service = new PublicQueryService(
                repository, revisionProvider, new CursorCodec()
        );

        assertThatThrownBy(() -> service.institution(404, Platform.VK, PeriodKey.SEVEN_DAYS))
                .isInstanceOf(ResourceNotFoundException.class)
                .hasMessageContaining("legacy id 404");
        assertThat(repository.institutionLegacyId).isEqualTo(404);
        assertThat(repository.platform).isEqualTo(Platform.VK);
        assertThat(repository.period).isEqualTo(PeriodKey.SEVEN_DAYS);
        assertThat(repository.datasetRevision).isEqualTo(23);
    }

    @Test
    void emptyDetailMetricsUseTheSelectedRevisionCommitAsResponseAsOf() {
        Instant committedAt = Instant.parse("2026-09-03T10:00:00Z");
        DatasetRevision revision = new DatasetRevision(23, committedAt);
        UUID institutionId = UUID.fromString("00000000-0000-0000-0000-000000000023");
        InstitutionIdentity institution = new InstitutionIdentity(
                institutionId, 23, "Empty University", null
        );
        RecordingRepository repository = new RecordingRepository();
        repository.institution = Optional.of(new InstitutionView(
                institution, Platform.VK, PeriodKey.SEVEN_DAYS,
                new MetricSet(null, null, null, null, 0, null, null, null, 23)
        ));
        CounterMetric emptyCounter = new CounterMetric(null, null, null);
        repository.publication = Optional.of(new PublicationView(
                new PublicationIdentity(
                        UUID.fromString("10000000-0000-0000-0000-000000000023"),
                        230, LegacyEntityType.PLATFORM_POSTS, institutionId,
                        Instant.parse("2026-09-02T12:00:00Z"), "post", null
                ),
                Platform.VK, emptyCounter, emptyCounter, emptyCounter, emptyCounter,
                null, false, false, "incomplete", null, 23
        ));
        PublicQueryService service = new PublicQueryService(
                repository, () -> revision, new CursorCodec()
        );

        InstitutionView institutionView = service.institution(
                23, Platform.VK, PeriodKey.SEVEN_DAYS
        );
        PublicationView publicationView = service.publication(
                230, LegacyEntityType.PLATFORM_POSTS
        );

        assertThat(institutionView.metrics().asOf()).isEqualTo(committedAt);
        assertThat(institutionView.metrics().sampleSize()).isZero();
        assertThat(institutionView.metrics().totalReactions()).isNull();
        assertThat(institutionView.metrics().coverage()).isNull();
        assertThat(institutionView.metrics().quality()).isNull();
        assertThat(publicationView.observedAt()).isEqualTo(committedAt);
        assertThat(publicationView.views().value()).isNull();
        assertThat(publicationView.views().observedAt()).isNull();
        assertThat(publicationView.views().quality()).isNull();
        assertThat(repository.institutionCalls).isEqualTo(1);
        assertThat(repository.publicationCalls).isEqualTo(1);
        assertThat(repository.datasetRevision).isEqualTo(23);
    }

    @Test
    void parityQueriesUseOneRevisionAndOneRepositoryCallPerRequest() {
        RecordingRepository repository = new RecordingRepository();
        AtomicInteger revisionReads = new AtomicInteger();
        DatasetRevisionProvider revisionProvider = () -> {
            revisionReads.incrementAndGet();
            return new DatasetRevision(31, Instant.parse("2026-09-03T11:00:00Z"));
        };
        PublicQueryService service = new PublicQueryService(
                repository, revisionProvider, new CursorCodec()
        );

        ActivityRatingQuery ratingQuery = ActivityRatingQuery.normalized(
                Platform.TELEGRAM, PeriodKey.THIRTY_DAYS,
                "engagement", "desc", "view_share", "desc"
        );
        var rating = service.rating(ratingQuery, 20);
        assertThat(rating.datasetRevision()).isEqualTo(31);
        assertThat(rating.asOf()).isEqualTo(Instant.parse("2026-09-03T11:00:00Z"));

        assertThatThrownBy(() -> service.comparison(
                Platform.VK, 72, false, "views", "median", 25,
                new ComparisonSelection(
                        ComparisonSelectionType.INSTITUTIONS, List.of(91L, 12L)
                )
        )).isInstanceOf(ResourceNotFoundException.class);
        assertThatThrownBy(() -> service.account(8, LegacyEntityType.PLATFORM_ACCOUNTS))
                .isInstanceOf(ResourceNotFoundException.class);

        assertThat(revisionReads).hasValue(3);
        assertThat(repository.ratingCalls).isEqualTo(1);
        assertThat(repository.comparisonCalls).isEqualTo(1);
        assertThat(repository.comparisonSelection.legacyIds())
                .containsExactly(91L, 12L);
        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.INSTITUTIONS);
        assertThat(repository.accountCalls).isEqualTo(1);
        assertThat(repository.ratingQuery).isEqualTo(ratingQuery);
        assertThat(repository.ratingLimit).isEqualTo(20);
        assertThat(repository.datasetRevision).isEqualTo(31);
    }

    @Test
    void rejectsPlatformMismatchedComparisonSelectionBeforeCallingTheRepository() {
        RecordingRepository repository = new RecordingRepository();
        PublicQueryService service = new PublicQueryService(
                repository,
                () -> new DatasetRevision(31, Instant.parse("2026-09-03T11:00:00Z")),
                new CursorCodec()
        );

        assertThatThrownBy(() -> service.comparison(
                Platform.TELEGRAM, 72, false, "reactions", "median", 25,
                new ComparisonSelection(
                        ComparisonSelectionType.INSTITUTIONS, List.of(4L)
                )
        )).isInstanceOf(InvalidComparisonSelectionException.class)
                .hasMessageContaining("must be channels for platform telegram");

        assertThat(repository.comparisonCalls).isZero();
    }

    private static OverviewCard item(String id, long legacyId, String name, String asOf) {
        OverviewMetric metric = new OverviewMetric(
                BigDecimal.TEN, BigDecimal.ONE, null, null, null, null
        );
        return new OverviewCard(
                UUID.fromString(id), "institutions", legacyId,
                "/institutions/" + legacyId,
                new InstitutionIdentity(UUID.fromString(id), legacyId, name, null),
                Platform.ALL, PeriodKey.ONE_DAY, List.of(), 3, 2, 2,
                null, null, null, "connected", null, null, null, null,
                null, null, null, metric, metric, metric, metric, 17,
                Instant.parse(asOf)
        );
    }

    private static final class RecordingRepository implements PublicQueryRepository {
        private List<OverviewCard> overview = List.of();
        private OverviewQuery overviewQuery;
        private Platform platform;
        private PeriodKey period;
        private String search;
        private int fetchLimit;
        private UUID afterInstitutionId;
        private long datasetRevision;
        private int overviewCalls;
        private long institutionLegacyId;
        private Optional<InstitutionView> institution = Optional.empty();
        private Optional<PublicationView> publication = Optional.empty();
        private int institutionCalls;
        private int publicationCalls;
        private int ratingCalls;
        private int comparisonCalls;
        private int accountCalls;
        private ActivityRatingQuery ratingQuery;
        private int ratingLimit;
        private ComparisonSelection comparisonSelection;

        @Override
        public List<OverviewCard> findOverview(
                OverviewQuery query,
                int fetchLimit,
                UUID afterEntityId,
                long datasetRevision
        ) {
            this.overviewQuery = query;
            this.platform = query.platform();
            this.period = query.period();
            this.search = query.search();
            this.fetchLimit = fetchLimit;
            this.afterInstitutionId = afterEntityId;
            this.datasetRevision = datasetRevision;
            overviewCalls++;
            return overview;
        }

        @Override
        public Optional<InstitutionView> findInstitution(
                long legacyId,
                Platform platform,
                PeriodKey period,
                long datasetRevision
        ) {
            institutionLegacyId = legacyId;
            this.platform = platform;
            this.period = period;
            this.datasetRevision = datasetRevision;
            institutionCalls++;
            return institution;
        }

        @Override
        public Optional<PublicationView> findPublication(
                long legacyId,
                LegacyEntityType legacyEntityType,
                long datasetRevision
        ) {
            publicationCalls++;
            this.datasetRevision = datasetRevision;
            return publication;
        }

        @Override
        public ActivityRatingResult findActivityRating(
                ActivityRatingQuery query,
                int entityLimit,
                long datasetRevision
        ) {
            ratingCalls++;
            this.ratingQuery = query;
            this.ratingLimit = entityLimit;
            this.datasetRevision = datasetRevision;
            return new ActivityRatingResult(List.of(), List.of(), false);
        }

        @Override
        public Optional<ComparisonView> findComparison(
                Platform platform,
                int horizonHours,
                boolean includePartial,
                String metric,
                String aggregation,
                int institutionLimit,
                ComparisonSelection selection,
                long datasetRevision
        ) {
            comparisonCalls++;
            comparisonSelection = selection;
            this.datasetRevision = datasetRevision;
            return Optional.empty();
        }

        @Override
        public Optional<AccountView> findAccount(
                long legacyId,
                LegacyEntityType legacyEntityType,
                long datasetRevision
        ) {
            accountCalls++;
            this.datasetRevision = datasetRevision;
            return Optional.empty();
        }
    }
}
