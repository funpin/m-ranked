package org.mranked.query.web;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.mranked.analytics.domain.AggregateMetric;
import org.mranked.query.domain.InstitutionView;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.ComparisonView;
import org.mranked.query.domain.OverviewCard;
import org.mranked.query.domain.PageResult;
import org.mranked.query.domain.PublicationView;
import org.mranked.query.domain.RatingPage;

public final class PublicApiModels {
    private PublicApiModels() {
    }

    public record InstitutionAccounts(List<Account> items,String nextCursor,long legacyTotalAccountCount,
                                      long datasetRevision,Instant asOf) {}
    public record PublicationHistory(Publication publication,List<org.mranked.query.domain.HistorySnapshot> items,
            String nextCursor,Long previousLegacyId,Long nextLegacyId,String archivedText,long datasetRevision,Instant asOf) {}
    public static InstitutionAccounts institutionAccounts(org.mranked.query.domain.InstitutionAccountPage page) {
        return new InstitutionAccounts(page.items().stream().map(PublicApiModels::account).toList(),page.nextCursor(),
                page.legacyTotalAccountCount(),page.datasetRevision(),page.asOf());
    }
    public static PublicationHistory history(org.mranked.query.domain.PublicationHistoryView page) {
        return new PublicationHistory(publication(page.publication()),page.items(),page.nextCursor(),page.previousLegacyId(),
                page.nextLegacyId(),page.archivedText(),page.datasetRevision(),page.asOf());
    }

    public record Metrics(
            BigDecimal totalReactions,
            BigDecimal totalViews,
            BigDecimal medianReactions,
            BigDecimal medianViews,
            int sampleSize,
            BigDecimal coverage,
            String quality,
            java.util.Map<String, AggregateMetric> aggregates
    ) {
    }

    public record OverviewMetric(
            BigDecimal total,
            BigDecimal median,
            BigDecimal previousTotal,
            BigDecimal previousMedian,
            BigDecimal totalTrend,
            BigDecimal medianTrend,
            AggregateMetric totalMetadata, AggregateMetric medianMetadata,
            AggregateMetric previousTotalMetadata, AggregateMetric previousMedianMetadata
    ) {
    }

    public record OverviewAccountRow(
            UUID accountId,
            Long legacyId,
            String legacyRoute,
            String platform,
            String canonicalExternalId,
            String username,
            String title,
            String url,
            String accessMode,
            boolean enabled,
            Long subscriberCount,
            String subscriberDisplay,
            Instant subscriberObservedAt,
            Instant latestPollStartedAt,
            Instant latestPollCompletedAt,
            String latestPollStatus,
            String latestErrorCode
    ) {
    }

    public record OverviewRow(
            UUID entityId,
            String entityType,
            long legacyId,
            String legacyRoute,
            UUID institutionId,
            long institutionLegacyId,
            String canonicalName,
            String shortName,
            String platform,
            String period,
            List<OverviewAccountRow> accounts,
            int accountCount,
            int enabledAccountCount,
            int connectedPlatformCount,
            Long subscriberCount,
            Instant lastCheckedAt,
            String lastErrorCode,
            String statusCode,
            Integer ratingRank,
            BigDecimal ratingScore,
            String ratingPeriod,
            Instant ratingFetchedAt,
            Long totalPublicationCount,
            Long activityPublicationCount,
            Long newPublicationCount,
            OverviewMetric views,
            OverviewMetric reactions,
            OverviewMetric comments,
            OverviewMetric shares,
            Instant asOf
    ) {
    }

    public record OverviewPage(
            List<OverviewRow> items,
            String nextCursor,
            long datasetRevision,
            Instant asOf,String integrationStatus,String integrationWarning
    ) {
    }

    public record Institution(
            UUID institutionId,
            long legacyId,
            String canonicalName,
            String shortName,
            String platform,
            String period,
            Metrics metrics,
            long datasetRevision,
            Instant asOf
    ) {
    }

    public record Publication(
            UUID publicationId,
            long legacyId,
            String legacyType,
            UUID institutionId,
            String platform,
            Instant publishedAt,
            String publicationType,
            Instant deletedAt,
            CounterMetric views,
            CounterMetric reactions,
            CounterMetric comments,
            CounterMetric shares,
            String quality,
            boolean intervalUncertain,
            boolean synthetic,
            String historyCompleteness,
            long datasetRevision,
            Instant asOf,
            Long accountLegacyId,String accountLegacyType,String accountName,String accountUsername,
            String externalId,String publicUrl,String displayExternalId,boolean repost,boolean joint,
            int additionalAuthorCount,boolean ambiguousAlbumReactions
    ) {
    }

    public record CounterMetric(Long value, Instant observedAt, String quality) {
    }

    public record ActivityRatingEntityRow(
            UUID entityId,
            String entityType,
            long legacyId,
            String legacyRoute,
            UUID institutionId,
            Long institutionLegacyId,
            String canonicalName,
            String shortName,
            String username,
            String title,
            int publicationCount,
            BigDecimal averageReactions,
            BigDecimal averageViews,
            long totalReactions,
            Long totalViews,
            Long totalComments,
            Long totalShares,
            Long totalInteractions,
            BigDecimal engagementRate,
            Long subscriberCount
    ) {
    }

    public record ActivityRatingPublicationRow(
            UUID publicationId,
            Long legacyId,
            String legacyType,
            String legacyRoute,
            UUID institutionId,
            long institutionLegacyId,
            String institutionCanonicalName,
            String institutionShortName,
            UUID accountId,
            Long accountLegacyId,
            String accountUsername,
            String accountTitle,
            String externalId,
            String publicUrl,
            Instant publishedAt,
            Instant deletedAt,
            boolean joint,
            int additionalAuthorCount,
            boolean repost,
            Long views,
            Long reactions,
            Long comments,
            Long shares,
            Long interactions,
            BigDecimal subscriberShare,
            BigDecimal viewShare
    ) {
    }

    public record Rating(
            String platform,
            String period,
            String entityType,
            String publicationLegacyType,
            String channelSort,
            String channelDirection,
            String postSort,
            String postDirection,
            List<ActivityRatingEntityRow> entities,
            List<ActivityRatingPublicationRow> publications,
            int entityLimit,
            boolean entitiesTruncated,
            long datasetRevision,
            Instant asOf,
            String nextEntityCursor,
            int entityOffset
    ) {
    }

    public record ComparisonPoint(
            int hourOffset,
            BigDecimal value,
            int sampleSize,
            BigDecimal coverage,
            String quality
    ) {
    }

    public record ComparisonSeries(
            UUID selectionId,
            String selectionType,
            long selectionLegacyId,
            String selectionLabel,
            UUID institutionId,
            long legacyId,
            String canonicalName,
            String shortName,
            int primaryCohortSize,
            int engagementCohortSize,
            List<ComparisonPoint> points,
            List<ComparisonPoint> engagementPoints
    ) {
    }

    public record Comparison(
            UUID cohortId,
            String platform,
            int horizonHours,
            boolean includePartial,
            String metric,
            String aggregation,
            String selectionType,
            int cohortSampleSize,
            List<ComparisonSeries> series,
            long datasetRevision,
            Instant asOf,
            String nextSelectionCursor
    ) {
    }

    public record Account(
            UUID accountId,
            long legacyId,
            String legacyType,
            Long channelLegacyId,
            Long platformAccountLegacyId,
            UUID institutionId,
            long institutionLegacyId,
            String institutionName,
            String institutionShortName,
            String platform,
            String canonicalExternalId,
            String username,
            String title,
            String url,
            String accessMode,
            boolean enabled,
            long publicationCount,
            Instant latestObservedAt,
            long datasetRevision,
            Instant asOf,
            org.mranked.query.domain.AccountStats stats
    ) {
    }

    public static OverviewPage overview(PageResult<OverviewCard> page) {return overview(page,"unknown");}
    public static OverviewPage overview(PageResult<OverviewCard> page,String integrationStatus) {
        return overview(page,integrationStatus,null);
    }
    public static OverviewPage overview(PageResult<OverviewCard> page,String integrationStatus,String integrationWarning) {
        return new OverviewPage(
                page.items().stream().map(PublicApiModels::overviewRow).toList(),
                page.nextCursor(), page.datasetRevision(), page.asOf(),integrationStatus,integrationWarning
        );
    }

    public static Institution institution(InstitutionView view) {
        var identity = view.institution();
        var metrics = view.metrics();
        return new Institution(
                identity.id(), identity.legacyId(), identity.canonicalName(), identity.shortName(),
                view.platform().databaseValue(), view.period().databaseValue(), metrics(metrics),
                metrics.datasetRevision(), metrics.asOf()
        );
    }

    public static Publication publication(PublicationView view) {
        var identity = view.publication();
        return new Publication(
                identity.id(), identity.legacyId(), identity.legacyEntityType().databaseValue(),
                identity.institutionId(), view.platform().databaseValue(), identity.publishedAt(),
                identity.publicationType(), identity.deletedAt(), counter(view.views()),
                counter(view.reactions()), counter(view.comments()), counter(view.shares()), view.quality(),
                view.intervalUncertain(), view.synthetic(), view.historyCompleteness(),
                view.datasetRevision(), view.observedAt(), view.accountLegacyId(),view.accountLegacyType(),view.accountName(),
                view.accountUsername(),view.externalId(),view.publicUrl(),view.presentation().displayExternalId(),
                view.presentation().repost(),view.presentation().joint(),view.presentation().additionalAuthorCount(),view.presentation().ambiguousAlbumReactions()
        );
    }

    public static Rating rating(RatingPage page) {
        return new Rating(
                page.platform().databaseValue(), page.period().databaseValue(),
                page.entityType(), page.publicationLegacyType(),
                page.channelSort(), page.channelDirection(),
                page.postSort(), page.postDirection(),
                page.entities().stream().map(item -> new ActivityRatingEntityRow(
                        item.entityId(), item.entityType(), item.legacyId(), item.legacyRoute(),
                        item.institutionId(), item.institutionLegacyId(), item.canonicalName(),
                        item.shortName(), item.username(), item.title(), item.publicationCount(),
                        item.averageReactions(), item.averageViews(), item.totalReactions(), item.totalViews(),
                        item.totalComments(), item.totalShares(), item.totalInteractions(),
                        item.engagementRate(), item.subscriberCount()
                )).toList(),
                page.publications().stream().map(item -> new ActivityRatingPublicationRow(
                        item.publicationId(), item.legacyId(), item.legacyType(), item.legacyRoute(),
                        item.institutionId(), item.institutionLegacyId(),
                        item.institutionCanonicalName(), item.institutionShortName(),
                        item.accountId(), item.accountLegacyId(), item.accountUsername(),
                        item.accountTitle(), item.externalId(), item.publicUrl(), item.publishedAt(),
                        item.deletedAt(), item.joint(), item.additionalAuthorCount(), item.repost(),
                        item.views(), item.reactions(), item.comments(), item.shares(),
                        item.interactions(), item.subscriberShare(), item.viewShare()
                )).toList(),
                page.entityLimit(), page.entitiesTruncated(),
                page.datasetRevision(), page.asOf(), page.nextEntityCursor(), page.entityOffset()
        );
    }

    public static Comparison comparison(ComparisonView view) {
        return new Comparison(
                view.cohortId(), view.platform().databaseValue(), view.horizonHours(),
                view.includePartial(), view.metric(), view.aggregation(),
                view.selectionType().apiValue(), view.cohortSampleSize(),
                view.series().stream().map(series -> {
                    var institution = series.institution();
                    return new ComparisonSeries(
                            series.selectionId(), series.selectionType().apiValue(),
                            series.selectionLegacyId(), series.selectionLabel(),
                            institution.id(), institution.legacyId(), institution.canonicalName(),
                            institution.shortName(), series.primaryCohortSize(),
                            series.engagementCohortSize(), series.points().stream().map(point ->
                                    new ComparisonPoint(
                                            point.hourOffset(), point.value(), point.sampleSize(),
                                            point.coverage(), point.quality()
                                    )
                            ).toList(), series.engagementPoints().stream().map(point ->
                                    new ComparisonPoint(
                                            point.hourOffset(), point.value(), point.sampleSize(),
                                            point.coverage(), point.quality()
                                    )
                            ).toList()
                    );
                }).toList(),
                view.datasetRevision(), view.asOf(), view.nextSelectionCursor()
        );
    }

    public static Account account(AccountView view) {
        var institution = view.institution();
        return new Account(
                view.id(), view.legacyId(), view.legacyEntityType().databaseValue(),
                view.channelLegacyId(), view.platformAccountLegacyId(),
                institution.id(), institution.legacyId(), institution.canonicalName(),
                institution.shortName(), view.platform().databaseValue(),
                view.canonicalExternalId(), view.username(), view.title(), view.url(),
                view.accessMode(), view.enabled(), view.publicationCount(), view.latestObservedAt(),
                view.datasetRevision(), view.asOf(),view.stats()
        );
    }

    private static CounterMetric counter(org.mranked.analytics.domain.CounterMetric metric) {
        return new CounterMetric(metric.value(), metric.observedAt(), metric.quality());
    }

    private static OverviewRow overviewRow(OverviewCard item) {
        var institution = item.institution();
        return new OverviewRow(
                item.entityId(), item.entityType(), item.legacyId(), item.legacyRoute(),
                institution.id(), institution.legacyId(), institution.canonicalName(),
                institution.shortName(), item.platform().databaseValue(),
                item.period().databaseValue(), item.accounts().stream().map(account ->
                        new OverviewAccountRow(
                                account.id(), account.legacyId(), account.legacyRoute(),
                                account.platform().databaseValue(), account.canonicalExternalId(),
                                account.username(), account.title(), account.url(),
                                account.accessMode(), account.enabled(), account.subscriberCount(),
                                account.subscriberDisplay(), account.subscriberObservedAt(),
                                account.latestPollStartedAt(), account.latestPollCompletedAt(),
                                account.latestPollStatus(), account.latestErrorCode()
                        )
                ).toList(), item.accountCount(), item.enabledAccountCount(),
                item.connectedPlatformCount(), item.subscriberCount(), item.lastCheckedAt(),
                item.lastErrorCode(), item.statusCode(), item.ratingRank(), item.ratingScore(),
                item.ratingPeriod(), item.ratingFetchedAt(), item.totalPublicationCount(),
                item.activityPublicationCount(), item.newPublicationCount(),
                overviewMetric(item.views()), overviewMetric(item.reactions()),
                overviewMetric(item.comments()), overviewMetric(item.shares()), item.asOf()
        );
    }

    private static OverviewMetric overviewMetric(
            org.mranked.query.domain.OverviewMetric metric
    ) {
        return new OverviewMetric(
                metric.total(), metric.median(), metric.previousTotal(),
                metric.previousMedian(), metric.totalTrend(), metric.medianTrend(), metric.totalMetadata(), metric.medianMetadata(),
                metric.previousTotalMetadata(), metric.previousMedianMetadata()
        );
    }

    private static Metrics metrics(org.mranked.analytics.domain.MetricSet metrics) {
        return new Metrics(
                metrics.totalReactions(), metrics.totalViews(), metrics.medianReactions(),
                metrics.medianViews(), metrics.sampleSize(), metrics.coverage(), metrics.quality(), metrics.aggregates()
        );
    }
}
