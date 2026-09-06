package org.mranked.query.domain;
import java.time.Instant;
import java.util.List;
public record InstitutionAccountPage(List<AccountView> items,String nextCursor,long legacyTotalAccountCount,
        long datasetRevision,Instant asOf) {}
