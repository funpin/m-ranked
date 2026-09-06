package org.mranked.operations.application;

import java.util.Map;

@FunctionalInterface
public interface HealthSnapshotSource { Map<String,Object> snapshot(); }
