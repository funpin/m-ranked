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

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public PageResult<OverviewCard> overview(
            OverviewQuery query,
            int limit,
            String cursor
    ) {
        return overviewAtRevision(query, limit, cursor, revisionProvider.current());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
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

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public InstitutionView institution(
            long legacyId,
            Platform platform,
            PeriodKey period
    ) {
        return institutionAtRevision(legacyId, platform, period, revisionProvider.current());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
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

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public PublicationView publication(long legacyId, LegacyEntityType legacyEntityType) {
        return publicationAtRevision(legacyId, legacyEntityType, revisionProvider.current());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
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
        return ratingPageAtRevision(query, entityLimit, null, revision);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public RatingPage ratingPageAtRevision(ActivityRatingQuery query, int entityLimit,
                                          String entityCursor, DatasetRevision revision) {
        UUID after = cursorCodec.decodeRating(entityCursor, revision.id(), query);
        var result = repository.findActivityRatingPage(query, entityLimit, revision.id(), after);
        return new RatingPage(
                query.platform(), query.period(), query.entityType(),
                query.publicationLegacyType(), query.channelSort(),
                query.channelDirection(), query.postSort(), query.postDirection(),
                result.entities(), result.publications(), entityLimit,
                result.entitiesTruncated(), revision.id(), revision.committedAt(),
                result.entitiesTruncated() && !result.entities().isEmpty()
                        ? cursorCodec.encodeRating(result.entities().getLast().entityId(), revision.id(), query)
                        : null, result.entityOffset()
        );
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
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

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
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

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AccountView account(long legacyId, LegacyEntityType legacyEntityType) {
        return accountAtRevision(legacyId, legacyEntityType, revisionProvider.current());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AccountView accountAtRevision(
            long legacyId,
            LegacyEntityType legacyEntityType,
            DatasetRevision revision
    ) {
        return repository.findAccount(legacyId, legacyEntityType, revision.id())
                .map(account -> account.withFallbackAsOf(revision.committedAt()))
                .orElseThrow(() -> new ResourceNotFoundException("account", legacyId));
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public <T> org.mranked.cache.application.RevisionedValue<T> readSnapshot(
            java.util.function.Function<DatasetRevision, T> reader
    ) {
        DatasetRevision revision = revisionProvider.current();
        return new org.mranked.cache.application.RevisionedValue<>(revision, reader.apply(revision));
    }

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public PageResult<org.mranked.query.domain.ComparisonCandidate> comparisonCandidatesAtRevision(
            Platform platform,int limit,String cursor,DatasetRevision revision) {
        String dimensions="compare-candidates:"+platform.databaseValue();
        UUID after=cursorCodec.decodeRating(cursor,revision.id(),dimensions);
        var rows=repository.findComparisonCandidates(platform,limit+1,after,revision.id());
        boolean more=rows.size()>limit;
        var visible=rows.subList(0,Math.min(limit,rows.size()));
        String next=more?cursorCodec.encodeRating(visible.getLast().selectionId(),revision.id(),dimensions):null;
        return new PageResult<>(visible,next,revision.id(),revision.committedAt());
    }

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public ComparisonView comparisonPageAtRevision(Platform platform,int horizonHours,boolean includePartial,
            String metric,String aggregation,int limit,ComparisonSelection selection,String cursor,DatasetRevision revision) {
        String dimensions=platform+":"+horizonHours+":"+includePartial+":"+metric+":"+aggregation+":"+selection;
        UUID after=cursorCodec.decodeRating(cursor,revision.id(),dimensions);
        List<Long> ids;
        String next=null;
        if (selection.explicit()) {
            if(after!=null&&(after.getMostSignificantBits()!=0||after.getLeastSignificantBits()>Integer.MAX_VALUE))
                throw new InvalidCursorException();
            int offset=after==null?0:(int)after.getLeastSignificantBits();
            if(offset<0||offset>=selection.legacyIds().size())throw new InvalidCursorException();
            int end=Math.min(offset+limit,selection.legacyIds().size());
            ids=selection.legacyIds().subList(offset,end);
            if(end<selection.legacyIds().size())next=cursorCodec.encodeRating(new UUID(0,end),revision.id(),dimensions);
        } else {
            var rows=repository.findComparisonCandidates(platform,limit+1,after,revision.id());
            boolean more=rows.size()>limit;
            var visible=rows.subList(0,Math.min(limit,rows.size()));
            ids=visible.stream().map(org.mranked.query.domain.ComparisonCandidate::selectionLegacyId).toList();
            if(more)next=cursorCodec.encodeRating(visible.getLast().selectionId(),revision.id(),dimensions);
        }
        // Every database query remains bounded to the selected page, with the existing fixed cohort unchanged.
        ComparisonView view=comparisonAtRevision(platform,horizonHours,includePartial,metric,aggregation,
                limit,ids.isEmpty()?selection:new ComparisonSelection(selection.type(),ids),revision);
        return new ComparisonView(view.cohortId(),view.platform(),view.horizonHours(),view.includePartial(),
                view.metric(),view.aggregation(),view.selectionType(),view.cohortSampleSize(),view.series(),
                view.datasetRevision(),view.asOf(),next);
    }

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public PageResult<org.mranked.query.domain.PublicationListItem> accountPublicationsAtRevision(
            long legacyId,LegacyEntityType type,int limit,String cursor,DatasetRevision revision) {
        var account=accountAtRevision(legacyId,type,revision);
        String dimensions="account-publications:"+legacyId+":"+type;
        UUID after=cursorCodec.decodeRating(cursor,revision.id(),dimensions);
        var rows=repository.findAccountPublications(account.id(),type,limit+1,after,revision.id());
        boolean more=rows.size()>limit;var visible=rows.subList(0,Math.min(limit,rows.size()));
        return new PageResult<>(visible,more?cursorCodec.encodeRating(visible.getLast().publicationId(),revision.id(),dimensions):null,
                revision.id(),revision.committedAt());
    }

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public org.mranked.query.domain.InstitutionAccountPage institutionAccountsAtRevision(
            long legacyId,Platform platform,int limit,String cursor,DatasetRevision revision) {
        institutionAtRevision(legacyId,platform,PeriodKey.ONE_DAY,revision);
        String dimensions="institution-accounts:"+legacyId+":"+platform;
        UUID after=cursorCodec.decodeRating(cursor,revision.id(),dimensions);
        var rows=repository.findInstitutionAccounts(legacyId,platform,limit+1,after,revision.id());
        boolean more=rows.size()>limit;var visible=rows.subList(0,Math.min(limit,rows.size()));
        return new org.mranked.query.domain.InstitutionAccountPage(visible,
                more?cursorCodec.encodeRating(visible.getLast().id(),revision.id(),dimensions):null,
                repository.countInstitutionAccounts(legacyId,platform),revision.id(),revision.committedAt());
    }

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public org.mranked.query.domain.PublicationHistoryView publicationHistoryAtRevision(
            long legacyId,LegacyEntityType type,int limit,String cursor,DatasetRevision revision) {
        var publication=publicationAtRevision(legacyId,type,revision);
        String dimensions="publication-history:"+legacyId+":"+type;
        UUID after=cursorCodec.decodeRating(cursor,revision.id(),dimensions);
        if(after!=null&&(after.getMostSignificantBits()!=0||after.getLeastSignificantBits()<=0))throw new InvalidCursorException();
        var rows=repository.findPublicationHistory(publication.publication().id(),limit+1,
                after==null?null:after.getLeastSignificantBits(),revision.id());
        boolean more=rows.size()>limit;var visible=rows.subList(0,Math.min(limit,rows.size()));
        var neighbours=repository.findPublicationNeighbours(publication.publication().id(),type);
        return new org.mranked.query.domain.PublicationHistoryView(publication,visible,
                more?cursorCodec.encodeRating(new UUID(0,Long.parseLong(visible.getLast().snapshotId())),revision.id(),dimensions):null,
                neighbours.get(0),neighbours.get(1),repository.findPublicationArchivedText(publication.publication().id(),revision.id()),revision.id(),revision.committedAt());
    }

    public DatasetRevision currentRevision() {
        return revisionProvider.current();
    }

    public String normalizeCursor(String cursor) {
        return cursorCodec.decode(cursor).map(cursorCodec::encode).orElse(null);
    }
}
