package org.mranked.operations.application;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.mranked.operations.domain.ProbeStatus;
import org.mranked.operations.domain.ReadinessResult;

class ReadinessServiceTest {
    @Test
    void passesThroughAHealthyProbe() {
        ReadinessService service = new ReadinessService(() -> ReadinessResult.up(12));

        assertThat(service.status()).isEqualTo(ReadinessResult.up(12));
    }

    @Test
    void convertsDependencyFailureToADataFreeDownResult() {
        ReadinessService service = new ReadinessService(() -> {
            throw new IllegalStateException("database password must never leave the service");
        });

        ReadinessResult result = service.status();

        assertThat(result.status()).isEqualTo(ProbeStatus.DOWN);
        assertThat(result.datasetRevision()).isNull();
    }
}
