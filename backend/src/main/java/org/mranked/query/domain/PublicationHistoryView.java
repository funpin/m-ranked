package org.mranked.query.domain;
import java.time.Instant;
import java.util.List;
public record PublicationHistoryView(PublicationView publication,List<HistorySnapshot> items,String nextCursor,
        Long previousLegacyId,Long nextLegacyId,String archivedText,long datasetRevision,Instant asOf) {}
