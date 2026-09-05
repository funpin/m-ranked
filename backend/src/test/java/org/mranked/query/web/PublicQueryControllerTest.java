package org.mranked.query.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.analytics.domain.CounterMetric;
import org.mranked.analytics.domain.MetricSet;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.ETagFactory;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.application.PublicCacheKeyFactory;
import org.mranked.cache.application.PublicDtoCache;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.cache.infrastructure.DisabledPublicCacheStore;
import org.mranked.catalog.domain.InstitutionIdentity;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.application.CursorCodec;
import org.mranked.query.application.PublicQueryRepository;
import org.mranked.query.application.PublicQueryService;
import org.mranked.query.domain.InstitutionView;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.ActivityRatingEntity;
import org.mranked.query.domain.ActivityRatingPublication;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.ActivityRatingResult;
import org.mranked.query.domain.ComparisonPoint;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.ComparisonSelectionType;
import org.mranked.query.domain.ComparisonSeries;
import org.mranked.query.domain.ComparisonView;
import org.mranked.query.domain.OverviewCard;
import org.mranked.query.domain.OverviewMetric;
import org.mranked.query.domain.OverviewQuery;
import org.mranked.query.domain.PublicationView;
import org.mranked.ingestion.domain.PublicationIdentity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.json.JsonMapper;

class PublicQueryControllerTest {
    private StubRepository repository;
    private MockMvc mvc;
    private AtomicInteger revisionReads;
    private AtomicReference<DatasetRevision> currentRevision;

    @BeforeEach
    void setUp() {
        repository = new StubRepository();
        revisionReads = new AtomicInteger();
        currentRevision = new AtomicReference<>(new DatasetRevision(
                88, Instant.parse("2026-09-03T10:00:00Z")
        ));
        DatasetRevisionProvider revisions = () -> {
            revisionReads.incrementAndGet();
            return currentRevision.get();
        };
        PublicQueryService service = new PublicQueryService(repository, revisions, new CursorCodec());
        PublicDtoCache responseCache = new PublicDtoCache(
                revisions,
                new PublicCacheKeyFactory(),
                Caffeine.newBuilder().maximumSize(100).build(),
                new DisabledPublicCacheStore(),
                new JsonMapper(),
                Duration.ofMinutes(10)
        );
        LocalValidatorFactoryBean validator = new LocalValidatorFactoryBean();
        validator.afterPropertiesSet();
        mvc = MockMvcBuilders.standaloneSetup(
                        new PublicQueryController(service, responseCache, new ETagFactory())
                )
                .setControllerAdvice(new Rfc9457ExceptionHandler())
                .setValidator(validator)
                .build();
    }

    @Test
    void overviewReturnsProjectionMetadataAndHonorsConditionalGet() throws Exception {
        Instant asOf = Instant.parse("2026-09-03T10:00:00Z");
        OverviewMetric metric = new OverviewMetric(
                BigDecimal.TEN, BigDecimal.ONE, null, null, null, null
        );
        OverviewCard item = new OverviewCard(
                UUID.fromString("00000000-0000-0000-0000-000000000001"),
                "institutions", 71, "/institutions/71",
                new InstitutionIdentity(
                        UUID.fromString("00000000-0000-0000-0000-000000000001"),
                        71, "North University", "NU"
                ),
                Platform.ALL, PeriodKey.ONE_DAY, List.of(), 5, 4, 4,
                null, asOf, null, "connected", 3, new BigDecimal("91.2"),
                "2026", asOf, null, null, null, metric, metric, metric, metric,
                88, asOf
        );
        repository.overview = List.of(item);

        String etag = mvc.perform(get("/api/v1/overview"))
                .andExpect(status().isOk())
                .andExpect(header().exists(HttpHeaders.ETAG))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "max-age=30, must-revalidate, public"))
                .andExpect(jsonPath("$.datasetRevision").value(88))
                .andExpect(jsonPath("$.items[0].legacyId").value(71))
                .andExpect(jsonPath("$.items[0].connectedPlatformCount").value(4))
                .andExpect(jsonPath("$.items[0].ratingRank").value(3))
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);

        mvc.perform(get("/api/v1/overview").header(HttpHeaders.IF_NONE_MATCH, etag))
                .andExpect(status().isNotModified())
                .andExpect(header().string(HttpHeaders.ETAG, etag))
                .andExpect(content().string(""));

        assertThat(revisionReads).hasValue(2);
        assertThat(repository.overviewCalls).isEqualTo(1);
    }

    @Test
    void malformedCursorIsAnRfc9457Problem() throws Exception {
        mvc.perform(get("/api/v1/overview").param("cursor", "broken"))
                .andExpect(status().isBadRequest())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:invalid-request"))
                .andExpect(jsonPath("$.status").value(400))
                .andExpect(jsonPath("$.detail").value("The cursor is malformed or unsupported"));
    }

    @Test
    void oldValidatorCannotReturn304AfterAuthoritativeRevisionAdvances() throws Exception {
        repository.overview = List.of();
        String oldEtag = mvc.perform(get("/api/v1/overview"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.datasetRevision").value(88))
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);
        currentRevision.set(new DatasetRevision(
                89, Instant.parse("2026-09-03T10:30:00Z")
        ));

        mvc.perform(get("/api/v1/overview").header(HttpHeaders.IF_NONE_MATCH, oldEtag))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.ETAG,
                        org.hamcrest.Matchers.not(oldEtag)))
                .andExpect(jsonPath("$.datasetRevision").value(89));

        assertThat(revisionReads).hasValue(2);
        assertThat(repository.overviewCalls).isEqualTo(2);
    }

    @Test
    void rejectsLimitOutsideTheDocumentedRange() throws Exception {
        mvc.perform(get("/api/v1/overview").param("limit", "201"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:invalid-request"));
    }

    @Test
    void missingLegacyAliasIsAnRfc9457Problem() throws Exception {
        mvc.perform(get("/api/v1/institutions/999"))
                .andExpect(status().isNotFound())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:not-found"))
                .andExpect(jsonPath("$.instance").value("/api/v1/institutions/999"));
    }

    @Test
    void existingInstitutionWithoutPeriodMetricsReturnsAnEmptyMetricSet() throws Exception {
        UUID institutionId = UUID.fromString("00000000-0000-0000-0000-000000000088");
        repository.institution = Optional.of(new InstitutionView(
                new InstitutionIdentity(institutionId, 88, "Empty University", null),
                Platform.VK,
                PeriodKey.SEVEN_DAYS,
                new MetricSet(null, null, null, null, 0, null, null, null, 88)
        ));

        mvc.perform(get("/api/v1/institutions/88")
                        .param("platform", "vk")
                        .param("period", "7d"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.institutionId").value(institutionId.toString()))
                .andExpect(jsonPath("$.platform").value("vk"))
                .andExpect(jsonPath("$.period").value("7d"))
                .andExpect(jsonPath("$.metrics.sampleSize").value(0))
                .andExpect(jsonPath("$.metrics.totalReactions").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.metrics.totalViews").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.metrics.coverage").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.metrics.quality").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.datasetRevision").value(88))
                .andExpect(jsonPath("$.asOf").value("2026-09-03T10:00:00Z"));
    }

    @Test
    void existingPublicationWithoutAcceptedLatestReturnsEmptyCounters() throws Exception {
        UUID institutionId = UUID.fromString("00000000-0000-0000-0000-000000000088");
        UUID publicationId = UUID.fromString("10000000-0000-0000-0000-000000000088");
        CounterMetric emptyCounter = new CounterMetric(null, null, null);
        repository.publication = Optional.of(new PublicationView(
                new PublicationIdentity(
                        publicationId, 880, LegacyEntityType.PLATFORM_POSTS, institutionId,
                        Instant.parse("2026-09-02T12:00:00Z"), "post", null
                ),
                Platform.VK, emptyCounter, emptyCounter, emptyCounter, emptyCounter,
                null, false, false, "incomplete", null, 88
        ));

        mvc.perform(get("/api/v1/publications/880")
                        .param("legacyType", "platform_posts"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.publicationId").value(publicationId.toString()))
                .andExpect(jsonPath("$.legacyType").value("platform_posts"))
                .andExpect(jsonPath("$.institutionId").value(institutionId.toString()))
                .andExpect(jsonPath("$.platform").value("vk"))
                .andExpect(jsonPath("$.views.value").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.views.observedAt").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.views.quality").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.reactions.value").value(
                        org.hamcrest.Matchers.nullValue()
                ))
                .andExpect(jsonPath("$.quality").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.intervalUncertain").value(false))
                .andExpect(jsonPath("$.synthetic").value(false))
                .andExpect(jsonPath("$.historyCompleteness").value("incomplete"))
                .andExpect(jsonPath("$.datasetRevision").value(88))
                .andExpect(jsonPath("$.asOf").value("2026-09-03T10:00:00Z"));
    }

    @Test
    void unexpectedFailuresAreSanitizedRfc9457Problems() throws Exception {
        repository.overviewFailure = new IllegalStateException("database-password-must-not-leak");
        Logger logger = (Logger) LoggerFactory.getLogger(Rfc9457ExceptionHandler.class);
        ListAppender<ILoggingEvent> captured = new ListAppender<>();
        captured.start();
        logger.addAppender(captured);
        try {
            mvc.perform(get("/api/v1/overview"))
                    .andExpect(status().isInternalServerError())
                    .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                    .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                    .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:internal-error"))
                    .andExpect(jsonPath("$.status").value(500))
                    .andExpect(jsonPath("$.detail").value("The request could not be completed"))
                    .andExpect(content().string(org.hamcrest.Matchers.not(
                            org.hamcrest.Matchers.containsString("database-password-must-not-leak")
                    )));
        } finally {
            logger.detachAppender(captured);
            captured.stop();
        }
        assertThat(captured.list)
                .extracting(ILoggingEvent::getFormattedMessage)
                .noneMatch(message -> message.contains("database-password-must-not-leak"));
    }

    @Test
    void ratingIsBoundedRevisionedAndCacheable() throws Exception {
        Instant asOf = Instant.parse("2026-09-03T10:15:00Z");
        UUID institutionId = UUID.fromString("00000000-0000-0000-0000-000000000011");
        UUID accountId = UUID.fromString("10000000-0000-0000-0000-000000000041");
        repository.rating = new ActivityRatingResult(
                List.of(new ActivityRatingEntity(
                        institutionId, "institutions", 11, "/institutions/11",
                        institutionId, 11L, "Rating University", "RU", null, null,
                        3, new BigDecimal("2.0"), new BigDecimal("33.3"),
                        6, 100L, 2L, 1L, 9L,
                        new BigDecimal("9.0"), 500L
                )),
                List.of(new ActivityRatingPublication(
                        UUID.fromString("20000000-0000-0000-0000-000000000501"),
                        501L, "platform_posts", "/platform-posts/501",
                        institutionId, 11, "Rating University", "RU",
                        accountId, 41L, "rating-account", "Rating account",
                        "post-501", "https://example.test/post-501", asOf, null,
                        true, 2, false, 100L, 6L, 2L, 1L, 9L,
                        null, new BigDecimal("9.0")
                )),
                true
        );

        mvc.perform(get("/api/v1/rating")
                        .param("platform", "vk")
                        .param("channel_sort", "views")
                        .param("post_sort", "shares")
                        .param("entityLimit", "25"))
                .andExpect(status().isOk())
                .andExpect(header().exists(HttpHeaders.ETAG))
                .andExpect(jsonPath("$.datasetRevision").value(88))
                .andExpect(jsonPath("$.platform").value("vk"))
                .andExpect(jsonPath("$.period").value("30d"))
                .andExpect(jsonPath("$.entityType").value("institutions"))
                .andExpect(jsonPath("$.channelSort").value("views"))
                .andExpect(jsonPath("$.entities[0].legacyId").value(11))
                .andExpect(jsonPath("$.entities[0].totalInteractions").value(9))
                .andExpect(jsonPath("$.publications[0].legacyRoute")
                        .value("/platform-posts/501"))
                .andExpect(jsonPath("$.publications[0].joint").value(true))
                .andExpect(jsonPath("$.entityLimit").value(25))
                .andExpect(jsonPath("$.entitiesTruncated").value(true));

        assertThat(repository.ratingQuery.platform()).isEqualTo(Platform.VK);
        assertThat(repository.ratingQuery.period()).isEqualTo(PeriodKey.THIRTY_DAYS);
        assertThat(repository.ratingEntityLimit).isEqualTo(25);
    }

    @Test
    void ratingUsesLegacyFallbacksForInvalidControls() throws Exception {
        mvc.perform(get("/api/v1/rating")
                        .param("platform", "not-a-platform")
                        .param("period", "not-a-period")
                        .param("channel_sort", "not-a-sort")
                        .param("channel_direction", "sideways")
                        .param("post_sort", "not-a-sort")
                        .param("post_direction", "sideways"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.platform").value("telegram"))
                .andExpect(jsonPath("$.period").value("1d"))
                .andExpect(jsonPath("$.channelSort").value("engagement"))
                .andExpect(jsonPath("$.channelDirection").value("desc"))
                .andExpect(jsonPath("$.postSort").value("reactions"))
                .andExpect(jsonPath("$.postDirection").value("desc"));
    }

    @Test
    void comparisonReturnsOneBoundedFixedCohortPayload() throws Exception {
        Instant asOf = Instant.parse("2026-09-03T10:20:00Z");
        InstitutionIdentity institution = new InstitutionIdentity(
                UUID.fromString("00000000-0000-0000-0000-000000000012"),
                12, "Curve University", "CU"
        );
        repository.comparison = Optional.of(new ComparisonView(
                UUID.fromString("10000000-0000-0000-0000-000000000001"),
                Platform.TELEGRAM, 72, false, "reactions", "median",
                ComparisonSelectionType.CHANNELS, 7,
                List.of(new ComparisonSeries(
                        UUID.fromString("20000000-0000-0000-0000-000000000012"),
                        ComparisonSelectionType.CHANNELS, 920012, "Curve channel",
                        institution, 7, 6, List.of(
                            new ComparisonPoint(0, BigDecimal.TEN, 7, BigDecimal.ONE, "exact")
                        ), List.of(
                            new ComparisonPoint(
                                    1, new BigDecimal("12.50"), 6, BigDecimal.ONE, "exact"
                            )
                        ))),
                88, asOf
        ));

        mvc.perform(get("/api/v1/compare")
                        .param("channels", "920012"))
                .andExpect(status().isOk())
                .andExpect(header().exists(HttpHeaders.ETAG))
                .andExpect(jsonPath("$.selectionType").value("channels"))
                .andExpect(jsonPath("$.cohortSampleSize").value(7))
                .andExpect(jsonPath("$.series[0].selectionLegacyId").value(920012))
                .andExpect(jsonPath("$.series[0].selectionLabel").value("Curve channel"))
                .andExpect(jsonPath("$.series[0].legacyId").value(12))
                .andExpect(jsonPath("$.series[0].primaryCohortSize").value(7))
                .andExpect(jsonPath("$.series[0].engagementCohortSize").value(6))
                .andExpect(jsonPath("$.series[0].points[0].hourOffset").value(0))
                .andExpect(jsonPath("$.series[0].engagementPoints[0].hourOffset").value(1))
                .andExpect(jsonPath("$.series[0].engagementPoints[0].value").value(12.5));

        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.CHANNELS);
        assertThat(repository.comparisonSelection.legacyIds()).containsExactly(920012L);
    }

    @Test
    void comparisonRejectsMalformedAndExcessRelevantSelectionsAsRfc9457() throws Exception {
        mvc.perform(get("/api/v1/compare").param("channels", "not-an-id"))
                .andExpect(status().isBadRequest())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.type").value("urn:m-ranked:problem:invalid-request"))
                .andExpect(jsonPath("$.detail").value("Channel IDs must be positive integers"));

        mvc.perform(get("/api/v1/compare")
                        .param("platform", "vk")
                        .param("institutions", "not-an-id"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value(
                        "Institution IDs must be positive integers"
                ));

        String[] excess = java.util.stream.LongStream.rangeClosed(1, 51)
                .mapToObj(String::valueOf)
                .toArray(String[]::new);
        mvc.perform(get("/api/v1/compare").param("channels", excess))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value("At most 50 channel IDs may be selected"));

        assertThat(repository.comparisonCalls).isEqualTo(0);
    }

    @Test
    void comparisonDeduplicatesRelevantIdsAndPreservesFirstSelectionOrder() throws Exception {
        mvc.perform(get("/api/v1/compare").param("channels", "12", "7", "12"))
                .andExpect(status().isNotFound());

        assertThat(repository.comparisonSelection.legacyIds())
                .containsExactly(12L, 7L);
        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.CHANNELS);
    }

    @Test
    void comparisonPreservesInstitutionOrderForNonTelegramPlatforms() throws Exception {
        mvc.perform(get("/api/v1/compare")
                        .param("platform", "vk")
                        .param("institutions", "91", "17"))
                .andExpect(status().isNotFound());

        assertThat(repository.comparisonSelection.legacyIds()).containsExactly(91L, 17L);
        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.INSTITUTIONS);
    }

    @Test
    void comparisonIgnoresTheSelectionNamespaceThatDoesNotMatchThePlatform() throws Exception {
        mvc.perform(get("/api/v1/compare")
                        .param("channels", "12")
                        .param("institutions", "91"))
                .andExpect(status().isNotFound());
        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.CHANNELS);
        assertThat(repository.comparisonSelection.legacyIds()).containsExactly(12L);

        mvc.perform(get("/api/v1/compare").param("institutions", "91"))
                .andExpect(status().isNotFound());
        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.CHANNELS);
        assertThat(repository.comparisonSelection.legacyIds()).isEmpty();

        mvc.perform(get("/api/v1/compare")
                        .param("platform", "rutube")
                        .param("channels", "12"))
                .andExpect(status().isNotFound());
        assertThat(repository.comparisonSelection.type())
                .isEqualTo(ComparisonSelectionType.INSTITUTIONS);
        assertThat(repository.comparisonSelection.legacyIds()).isEmpty();

        assertThat(repository.comparisonCalls).isEqualTo(3);
    }

    @Test
    void comparisonCacheIdentityIncludesOrderButNormalizesTheIgnoredDefaultLimit() throws Exception {
        Instant asOf = Instant.parse("2026-09-03T10:20:00Z");
        InstitutionIdentity institution = new InstitutionIdentity(
                UUID.fromString("00000000-0000-0000-0000-000000000012"),
                12, "Curve University", "CU"
        );
        repository.comparison = Optional.of(new ComparisonView(
                UUID.fromString("10000000-0000-0000-0000-000000000001"),
                Platform.TELEGRAM, 72, false, "reactions", "median",
                ComparisonSelectionType.CHANNELS, 7,
                List.of(new ComparisonSeries(
                        UUID.fromString("20000000-0000-0000-0000-000000000012"),
                        ComparisonSelectionType.CHANNELS, 12, "Curve channel",
                        institution, 7, 7, List.of(
                            new ComparisonPoint(0, BigDecimal.TEN, 7, BigDecimal.ONE, "exact")
                        ), List.of(
                            new ComparisonPoint(1, BigDecimal.TEN, 7, BigDecimal.ONE, "exact")
                        ))),
                88, asOf
        ));

        String first = mvc.perform(get("/api/v1/compare")
                        .param("institutionLimit", "1")
                        .param("channels", "12", "7"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);
        String sameSelection = mvc.perform(get("/api/v1/compare")
                        .param("institutionLimit", "50")
                        .param("channels", "12", "7"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);
        String reversed = mvc.perform(get("/api/v1/compare")
                        .param("channels", "7", "12"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getHeader(HttpHeaders.ETAG);

        assertThat(sameSelection).isEqualTo(first);
        assertThat(reversed).isNotEqualTo(first);
    }

    @Test
    void accountResolvesBothLegacyNamespacesWithoutRawSnapshots() throws Exception {
        Instant asOf = Instant.parse("2026-09-03T10:25:00Z");
        InstitutionIdentity institution = new InstitutionIdentity(
                UUID.fromString("00000000-0000-0000-0000-000000000013"),
                13, "Account University", "AU"
        );
        repository.account = Optional.of(new AccountView(
                UUID.fromString("20000000-0000-0000-0000-000000000001"),
                41, LegacyEntityType.CHANNELS, 41L, 501L, institution, Platform.TELEGRAM,
                "native-41", "account41", "Account 41", "https://example.test/account41",
                "public_web", true, 9, asOf, 88, asOf
        ));

        mvc.perform(get("/api/v1/accounts/41").param("legacyType", "channels"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.legacyType").value("channels"))
                .andExpect(jsonPath("$.channelLegacyId").value(41))
                .andExpect(jsonPath("$.platformAccountLegacyId").value(501))
                .andExpect(jsonPath("$.institutionLegacyId").value(13))
                .andExpect(jsonPath("$.publicationCount").value(9))
                .andExpect(jsonPath("$.datasetRevision").value(88));
    }

    private static final class StubRepository implements PublicQueryRepository {
        private List<OverviewCard> overview = List.of();
        private RuntimeException overviewFailure;
        private ActivityRatingResult rating = new ActivityRatingResult(
                List.of(), List.of(), false
        );
        private ActivityRatingQuery ratingQuery;
        private int ratingEntityLimit;
        private Optional<ComparisonView> comparison = Optional.empty();
        private Optional<AccountView> account = Optional.empty();
        private Optional<InstitutionView> institution = Optional.empty();
        private Optional<PublicationView> publication = Optional.empty();
        private int overviewCalls;
        private int comparisonCalls;
        private ComparisonSelection comparisonSelection = ComparisonSelection.defaults(
                ComparisonSelectionType.CHANNELS
        );

        @Override
        public List<OverviewCard> findOverview(
                OverviewQuery query,
                int fetchLimit,
                UUID afterEntityId,
                long datasetRevision
        ) {
            overviewCalls++;
            if (overviewFailure != null) {
                throw overviewFailure;
            }
            return overview;
        }

        @Override
        public Optional<InstitutionView> findInstitution(
                long legacyId,
                Platform platform,
                PeriodKey period,
                long datasetRevision
        ) {
            return institution;
        }

        @Override
        public Optional<PublicationView> findPublication(
                long legacyId,
                LegacyEntityType legacyEntityType,
                long datasetRevision
        ) {
            return publication;
        }

        @Override
        public ActivityRatingResult findActivityRating(
                ActivityRatingQuery query,
                int entityLimit,
                long datasetRevision
        ) {
            ratingQuery = query;
            ratingEntityLimit = entityLimit;
            return rating;
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
            return comparison;
        }

        @Override
        public Optional<AccountView> findAccount(
                long legacyId,
                LegacyEntityType legacyEntityType,
                long datasetRevision
        ) {
            return account;
        }
    }
}
