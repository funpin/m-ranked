package org.mranked.admin.infrastructure;

import java.util.List;
import org.mranked.admin.domain.AdminRole;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("mranked.admin.auth")
public record AdminAuthenticationProperties(List<AdminUser> users) {
    public AdminAuthenticationProperties {
        users = users == null ? List.of() : List.copyOf(users);
    }

    public record AdminUser(String username, String passwordHash, List<AdminRole> roles) {
        public AdminUser {
            roles = roles == null ? List.of() : List.copyOf(roles);
        }
    }
}
