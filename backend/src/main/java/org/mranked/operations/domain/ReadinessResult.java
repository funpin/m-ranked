package org.mranked.operations.domain;

public record ReadinessResult(ProbeStatus status, Long datasetRevision) {
    public static ReadinessResult up(long datasetRevision) {
        return new ReadinessResult(ProbeStatus.UP, datasetRevision);
    }

    public static ReadinessResult down() {
        return new ReadinessResult(ProbeStatus.DOWN, null);
    }
}
