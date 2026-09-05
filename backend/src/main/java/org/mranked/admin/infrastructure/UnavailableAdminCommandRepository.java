package org.mranked.admin.infrastructure;

import org.mranked.admin.application.AdminCommandRepository;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.SetPlatformAccountEnabledCommand;
import org.mranked.admin.application.SetPlatformAccountEnabledResult;

final class UnavailableAdminCommandRepository implements AdminCommandRepository {
    @Override
    public SetPlatformAccountEnabledResult setPlatformAccountEnabled(
            SetPlatformAccountEnabledCommand command
    ) {
        throw new AdminDatabaseUnavailableException();
    }
}
