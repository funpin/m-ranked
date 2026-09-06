package org.mranked.query.domain;

import java.time.Instant;
import org.mranked.analytics.domain.AggregateMetric;

public record AccountStats(int retentionDays,long postCount,long monitored,
        AggregateMetric medianReactions,AggregateMetric medianViews,AggregateMetric medianComments,
        Integer ratingRank,String ratingPeriod,Long subscriberCount,String lastError,Instant lastCheckedAt) {}
