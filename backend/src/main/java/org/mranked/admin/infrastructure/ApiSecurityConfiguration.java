package org.mranked.admin.infrastructure;

import jakarta.servlet.DispatcherType;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.mranked.admin.domain.AdminRole;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@EnableConfigurationProperties(AdminAuthenticationProperties.class)
public class ApiSecurityConfiguration {
    private static final String[] READ_ROLES = {"VIEWER", "EDITOR", "ADMIN"};
    private static final String[] WRITE_ROLES = {"EDITOR", "ADMIN"};

    @Bean
    @ConditionalOnMissingBean(UserDetailsService.class)
    UserDetailsService adminUserDetailsService(AdminAuthenticationProperties properties) {
        Set<String> usernames = new HashSet<>();
        List<UserDetails> users = properties.users().stream().map(configured -> {
            validate(configured, usernames);
            return User.withUsername(configured.username().strip())
                    .password(configured.passwordHash())
                    .roles(configured.roles().stream().map(AdminRole::name).toArray(String[]::new))
                    .build();
        }).toList();
        return new InMemoryUserDetailsManager(users);
    }

    @Bean
    SecurityFilterChain apiSecurityFilterChain(
            HttpSecurity http,
            ProblemSecurityHandler problemSecurityHandler
    ) throws Exception {
        CookieCsrfTokenRepository csrfTokens = CookieCsrfTokenRepository.withHttpOnlyFalse();
        csrfTokens.setCookiePath("/api/v1/admin");
        http
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(authorize -> authorize
                        .dispatcherTypeMatchers(DispatcherType.ERROR, DispatcherType.ASYNC).permitAll()
                        .requestMatchers(HttpMethod.GET,
                                "/api/v1/admin/csrf",
                                "/api/v1/admin/jobs",
                                "/api/v1/admin/jobs/*",
                                "/api/v1/admin/platform-accounts/*")
                        .hasAnyRole(READ_ROLES)
                        .requestMatchers(HttpMethod.PUT,
                                "/api/v1/admin/platform-accounts/*/enabled")
                        .hasAnyRole(WRITE_ROLES)
                        .requestMatchers("/api/v1/admin/**").denyAll()
                        .requestMatchers(HttpMethod.GET, "/api/v1/**").permitAll()
                        .anyRequest().denyAll())
                .exceptionHandling(exceptions -> exceptions
                        .accessDeniedHandler(problemSecurityHandler)
                        .authenticationEntryPoint(problemSecurityHandler))
                .csrf(csrf -> csrf
                        .csrfTokenRepository(csrfTokens)
                        .csrfTokenRequestHandler(new CsrfTokenRequestAttributeHandler()))
                .httpBasic(Customizer.withDefaults())
                .formLogin(form -> form.disable())
                .logout(logout -> logout.disable());
        return http.build();
    }

    private static void validate(
            AdminAuthenticationProperties.AdminUser configured,
            Set<String> usernames
    ) {
        if (configured.username() == null) {
            throw new IllegalStateException("admin auth username must be configured");
        }
        String username = configured.username().strip();
        if (username.isEmpty() || username.length() > 200
                || username.codePoints().anyMatch(Character::isISOControl)
                || !usernames.add(username)) {
            throw new IllegalStateException("admin auth usernames must be unique printable values");
        }
        if (configured.passwordHash() == null
                || !configured.passwordHash().startsWith("{bcrypt}$2")) {
            throw new IllegalStateException("admin auth passwords must be encoded bcrypt hashes");
        }
        if (configured.roles().isEmpty()) {
            throw new IllegalStateException("each admin auth user must have at least one role");
        }
    }
}
