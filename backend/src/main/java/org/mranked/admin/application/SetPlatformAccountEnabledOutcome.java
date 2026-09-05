package org.mranked.admin.application;

public enum SetPlatformAccountEnabledOutcome {
    UPDATED,
    IDEMPOTENT,
    NOT_FOUND,
    VERSION_CONFLICT
}
