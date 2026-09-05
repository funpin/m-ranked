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

    Optional<AccountView> findAccount(
            long legacyId,
            LegacyEntityType legacyEntityType,
            long datasetRevision
    );
}
