package org.mranked.query.domain;
import java.time.Instant;
import java.math.BigDecimal;
import java.util.Map;
import java.util.List;
import org.mranked.analytics.domain.CounterMetric;
public record HistorySnapshot(String snapshotId,Instant observedAt,BigDecimal ageHours,
        CounterMetric views,CounterMetric reactions,CounterMetric comments,CounterMetric shares,
        Long deltaViews,Long deltaReactions,Long deltaComments,Long deltaShares,
        Map<String,Long> reactionsBreakdown,boolean synthetic,boolean intervalUncertain,String quality,
        Map<String,Object> rawEvidence,Map<String,Long> deltaReactionsBreakdown,
        List<ReactionBreakdownEntry> reactionsBreakdownEntries,
        List<ReactionBreakdownEntry> deltaReactionsBreakdownEntries) {}
