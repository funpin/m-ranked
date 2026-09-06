package org.mranked.exportjob.application;

import java.time.Duration;

public record ExportJobPolicy(long maxRows, long maxBytes, Duration maxDuration,
                              Duration ttl, int workers, int artifacts) {
    public ExportJobPolicy {
        if (maxRows < 1 || maxRows > 2_000_000 || maxBytes < 1 || maxBytes > 512L * 1024 * 1024
                || maxDuration.isNegative() || maxDuration.isZero() || maxDuration.toSeconds() > 300
                || ttl.compareTo(maxDuration) < 0 || ttl.toMinutes() > 15
                || workers < 1 || workers > 2 || artifacts < workers || artifacts > 4) {
            throw new IllegalArgumentException("Invalid export job policy");
        }
    }

    public static ExportJobPolicy defaults() {
        return new ExportJobPolicy(2_000_000, 512L * 1024 * 1024,
                Duration.ofMinutes(5), Duration.ofMinutes(15), 2, 4);
    }
}
