package org.mranked.query.domain;
import java.time.Instant;
import java.util.UUID;
import org.mranked.analytics.domain.CounterMetric;
public record PublicationListItem(UUID publicationId,Long legacyId,String legacyType,String legacyRoute,
        String externalId,Instant publishedAt,String publicUrl,String publicationType,Instant deletedAt,
        String historyCompleteness,CounterMetric views,CounterMetric reactions,CounterMetric comments,
        CounterMetric shares,String title,String archivedText,String displayExternalId,boolean repost,boolean joint,
        int additionalAuthorCount,boolean ambiguousAlbumReactions) {}
