package org.mranked.operations.application;

import org.mranked.operations.domain.ReadinessResult;
import org.springframework.stereotype.Service;

@Service
public class ReadinessService {
    private final ReadinessProbe readinessProbe;

    public ReadinessService(ReadinessProbe readinessProbe) {
        this.readinessProbe = readinessProbe;
    }

    public ReadinessResult status() {
        try {
            return readinessProbe.probe();
        } catch (RuntimeException exception) {
            return ReadinessResult.down();
        }
    }
}
