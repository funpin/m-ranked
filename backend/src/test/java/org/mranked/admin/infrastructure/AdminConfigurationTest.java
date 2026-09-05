package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.mranked.admin.application.AdminDatabaseUnavailableException;
import org.mranked.admin.application.SetPlatformAccountEnabledCommand;
import org.mranked.admin.domain.AdminRole;
import org.springframework.security.core.userdetails.UserDetailsService;

class AdminConfigurationTest {
    @Test
    void writeDatasourceIsFailClosedAndRequiresTheExactDatabaseRole() {
        AdminDatabaseProperties disabled = new AdminDatabaseProperties(false, null, null, null);
        disabled.validateEnabledConfiguration();

        AdminDatabaseProperties wrongRole = new AdminDatabaseProperties(
                true,
                "jdbc:postgresql://127.0.0.1:5432/mranked",
                "api_read",
                "not-a-real-secret"
        );
        assertThatThrownBy(wrongRole::validateEnabledConfiguration)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("api_write_admin");

        AdminDatabaseConfiguration configuration = new AdminDatabaseConfiguration();
        var context = configuration.adminJdbcContext(disabled);
        assertThat(context.enabled()).isFalse();
        assertThatThrownBy(() -> configuration.adminCommandRepository(context)
                .setPlatformAccountEnabled(new SetPlatformAccountEnabledCommand(
                        java.util.UUID.randomUUID(), true, 0, "editor", java.util.UUID.randomUUID()
                )))
                .isInstanceOf(AdminDatabaseUnavailableException.class);
        assertThatThrownBy(() -> configuration.adminQueryRepository(context)
                .findPlatformAccount(java.util.UUID.randomUUID()))
                .isInstanceOf(AdminDatabaseUnavailableException.class);
    }

    @Test
    void configuredHttpIdentitiesRequireBcryptAndAnExplicitRole() {
        ApiSecurityConfiguration configuration = new ApiSecurityConfiguration();
        AdminAuthenticationProperties weak = new AdminAuthenticationProperties(List.of(
                new AdminAuthenticationProperties.AdminUser(
                        "admin", "{noop}secret", List.of(AdminRole.ADMIN)
                )
        ));
        assertThatThrownBy(() -> configuration.adminUserDetailsService(weak))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("bcrypt");

        AdminAuthenticationProperties valid = new AdminAuthenticationProperties(List.of(
                new AdminAuthenticationProperties.AdminUser(
                        "viewer",
                        "{bcrypt}$2a$10$012345678901234567890u12345678901234567890123456789012",
                        List.of(AdminRole.VIEWER)
                )
        ));
        UserDetailsService users = configuration.adminUserDetailsService(valid);
        assertThat(users.loadUserByUsername("viewer").getAuthorities())
                .extracting(Object::toString)
                .containsExactly("ROLE_VIEWER");
    }
}
