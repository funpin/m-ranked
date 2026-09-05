package org.mranked.operations.application;

import org.mranked.operations.domain.ReadinessResult;

public interface ReadinessProbe {
    ReadinessResult probe();
}
