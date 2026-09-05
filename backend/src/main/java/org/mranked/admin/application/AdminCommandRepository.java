package org.mranked.admin.application;

public interface AdminCommandRepository {
    SetPlatformAccountEnabledResult setPlatformAccountEnabled(
            SetPlatformAccountEnabledCommand command
    );
}
