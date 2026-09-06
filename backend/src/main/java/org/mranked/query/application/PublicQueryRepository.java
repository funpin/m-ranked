package org.mranked.query.application;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.domain.InstitutionView;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.ActivityRatingResult;
import org.mranked.query.domain.ComparisonView;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.OverviewCard;
import org.mranked.query.domain.OverviewQuery;
import org.mranked.query.domain.PublicationView;

public interface PublicQueryRepository {
    List<OverviewCard> findOverview(
            OverviewQuery query,
            int fetchLimit,
            UUID afterEntityId,
            long datasetRevision
    );

    Optional<InstitutionView> findInstitution(
            long legacyId,
            Platform platform,
            PeriodKey period,
            long datasetRevision
    );

    Optional<PublicationView> findPublication(
            long legacyId,
            LegacyEntityType legacyEntityType,
            long datasetRevision
    );

    ActivityRatingResult findActivityRating(
            ActivityRatingQuery query,
            int entityLimit,
            long datasetRevision
    );

    default ActivityRatingResult findActivityRatingPage(
            ActivityRatingQuery query, int entityLimit, long datasetRevision, UUID afterEntityId
    ) {
        if (afterEntityId != null) throw new UnsupportedOperationException("rating pagination unavailable");
        return findActivityRating(query, entityLimit, datasetRevision);
    }

    default List<org.mranked.query.domain.ComparisonCandidate> findComparisonCandidates(
            Platform platform, int limit, UUID afterId, long revision) {
        return List.of();
    }

    Optional<ComparisonView> findComparison(
            Platform platform,
            int horizonHours,
            boolean includePartial,
            String metric,
            String aggregation,
            int institutionLimit,
            ComparisonSelection selection,
            long datasetRevision
    );

    default List<org.mranked.query.domain.PublicationListItem> findAccountPublications(
            UUID accountId,LegacyEntityType accountType,int limit,UUID afterId,long revision) {return List.of();}
    default List<AccountView> findInstitutionAccounts(long legacyId,Platform platform,int limit,UUID afterId,
            long revision) {return List.of();}
    default long countInstitutionAccounts(long legacyId,Platform platform) {return 0;}
    default List<org.mranked.query.domain.HistorySnapshot> findPublicationHistory(
            UUID publicationId,int limit,Long afterSnapshotId,long revision) {return List.of();}
    default String findPublicationArchivedText(UUID publicationId,long revision) {return null;}
    default List<Long> findPublicationNeighbours(UUID publicationId,LegacyEntityType type) {return java.util.Arrays.asList(null,null);}

    Optional<AccountView> findAccount(
            long legacyId,
            LegacyEntityType legacyEntityType,
            long datasetRevision
    );
}
