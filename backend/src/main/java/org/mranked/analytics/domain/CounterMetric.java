package org.mranked.analytics.domain;

import java.time.Instant;

public record CounterMetric(Long value, Instant observedAt, String quality) {
}
