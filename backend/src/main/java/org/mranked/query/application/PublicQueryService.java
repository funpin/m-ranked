package org.mranked.query.application;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.domain.InstitutionView;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.ComparisonView;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.ComparisonSelectionType;
import org.mranked.query.domain.InvalidComparisonSelectionException;
import org.mranked.query.domain.OverviewCard;
import org.mranked.query.domain.OverviewQuery;
import org.mranked.query.domain.PageResult;
import org.mranked.query.domain.PublicationView;
import org.mranked.query.domain.RatingPage;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PublicQueryService {
    private final PublicQueryRepository repository;
    private final DatasetRevisionProvider revisionProvider;
    private final CursorCodec cursorCodec;

    public PublicQueryService(
            PublicQueryRepository repository,
            DatasetRevisionProvider revisionProvider,
            CursorCodec cursorCodec
    ) {
        this.repository = repository;
        this.revisionProvider = revisionProvider;
        this.cursorCodec = cursorCodec;
    }

    @Transactional(readOnly = true)
    public PageResult<OverviewCard> overview(
            OverviewQuery query,
            int limit,
            String cursor
    ) {
        return overviewAtRevision(query, limit, cursor, revisionProvider.current());
    }

    @Transactional(readOnly = true)
    public PageResult<OverviewCard> overviewAtRevision(
            OverviewQuery query,
            int limit,
            String cursor,
            DatasetRevision revision
    ) {
        UUID after = cursorCodec.decode(cursor).orElse(null);
        List<OverviewCard> fetched = repository.findOverview(
                query, limit + 1, after, revision.id()
        );
        boolean hasMore = fetched.size() > limit;
        List<OverviewCard> visible = new ArrayList<>(
                fetched.subList(0, Math.min(limit, fetched.size()))
        );
        String nextCursor = hasMore && !visible.isEmpty()
                ? cursorCodec.encode(visible.getLast().entityId())
                : null;
        Instant asOf = visible.stream()
                .map(OverviewCard::asOf)
                .filter(java.util.Objects::nonNull)
                .max(Instant::compareTo)
                .orElse(revision.committedAt());
        return new PageResult<>(visible, nextCursor, revision.id(), asOf);
    }

    @Transactional(readOnly = true)
    public InstitutionView institution(
            long legacyId,
            Platform platform,
            PeriodKey period
    ) {
        return institutionAtRevision(legacyId, platform, period, revisionProvider.current());
    }

    @Transactional(readOnly = true)
    public InstitutionView institutionAtRevision(
            long legacyId,
            Platform platform,
            PeriodKey period,
            DatasetRevision revision
    ) {
        return repository.findInstitution(legacyId, platform, period, revision.id())
                .map(institution -> institution.withFallbackAsOf(revision.committedAt()))
                .orElseThrow(() -> new ResourceNotFoundException("institution", legacyId));
    }

    @Transactional(readOnly = true)
    public PublicationView publication(long legacyId, LegacyEntityType legacyEntityType) {
        return publicationAtRevision(legacyId, legacyEntityType, revisionProvider.current());
    }

    @Transactional(readOnly = true)
    public PublicationView publicationAtRevision(
            long legacyId,
            LegacyEntityType legacyEntityType,
            DatasetRevision revision
    ) {
        return repository.findPublication(legacyId, legacyEntityType, revision.id())
                .map(publication -> publication.withFallbackAsOf(revision.committedAt()))
                .orElseThrow(() -> new ResourceNotFoundException("publication", legacyId));
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public RatingPage rating(ActivityRatingQuery query, int entityLimit) {
        return ratingAtRevision(query, entityLimit, revisionProvider.current());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public RatingPage ratingAtRevision(
            ActivityRatingQuery query,
            int entityLimit,
            DatasetRevision revision
    ) {
        var result = repository.findActivityRating(query, entityLimit, revision.id());
        return new RatingPage(
                query.platform(), query.period(), query.entityType(),
                query.publicationLegacyType(), query.channelSort(),
                query.channelDirection(), query.postSort(), query.postDirection(),
                result.entities(), result.publications(), entityLimit,
                result.entitiesTruncated(), revision.id(), revision.committedAt()
        );
    }

    @Transactional(readOnly = true)
    public ComparisonView comparison(
            Platform platform,
            int horizonHours,
            boolean includePartial,
            String metric,
            String aggregation,
            int institutionLimit,
            ComparisonSelection selection
    ) {
        return comparisonAtRevision(
                platform, horizonHours, includePartial, metric, aggregation,
                institutionLimit, selection, revisionProvider.current()
        );
    }

    @Transactional(readOnly = true)
    public ComparisonView comparisonAtRevision(
            Platform platform,
            int horizonHours,
            boolean includePartial,
            String metric,
            String aggregation,
            int institutionLimit,
            ComparisonSelection selection,
            DatasetRevision revision
    ) {
        ComparisonSelectionType expectedSelectionType = ComparisonSelectionType.forPlatform(
                platform
        );
        if (selection == null || selection.type() != expectedSelectionType) {
            throw new InvalidComparisonSelectionException(
                    "Comparison selection type must be "
                            + expectedSelectionType.apiValue()
                            + " for platform " + platform.databaseValue()
            );
        }
        return repository.findComparison(
                platform, horizonHours, includePartial, metric, aggregation,
                institutionLimit, selection, revision.id()
        ).orElseThrow(() -> new ResourceNotFoundException(
                "comparison cohort for the requested dimensions was not found"
        ));
    }

    @Transactional(readOnly = true)
    public AccountView account(long legacyId, LegacyEntityType legacyEntityType) {
        return accountAtRevision(legacyId, legacyEntityType, revisionProvider.current());
    }

    @Transactional(readOnly = true)
    public AccountView accountAtRevision(
            long legacyId,
            LegacyEntityType legacyEntityType,
            DatasetRevision revision
    ) {
        return repository.findAccount(legacyId, legacyEntityType, revision.id())
                .map(account -> account.withFallbackAsOf(revision.committedAt()))
                .orElseThrow(() -> new ResourceNotFoundException("account", legacyId));
    }

    public DatasetRevision currentRevision() {
        return revisionProvider.current();
    }

    public String normalizeCursor(String cursor) {
        return cursorCodec.decode(cursor).map(cursorCodec::encode).orElse(null);
    }
}
