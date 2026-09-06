package org.mranked.admin.domain;

import java.util.UUID;

public record ManagedAccount(UUID id, long legacyId, Long channelId, UUID institutionId, String platform,
        String externalKey, String username, String title, String url, String accessMode, boolean enabled,
        long rowVersion, String nativeId, Long subscribers, String legacyAccessMode, String lastErrorCode) { }
