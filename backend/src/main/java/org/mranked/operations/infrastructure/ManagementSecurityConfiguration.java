package org.mranked.operations.infrastructure;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.core.env.Environment;
import org.springframework.security.authorization.AuthorizationDecision;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

/** Scraping is available only on the dedicated loopback management listener. */
@Configuration(proxyBeanMethods=false)
public class ManagementSecurityConfiguration {
    private static final Set<String> LOOPBACK=Set.of("127.0.0.1","::1","0:0:0:0:0:0:0:1");

    @Bean @Order(0)
    SecurityFilterChain managementSecurity(HttpSecurity http, Environment environment) throws Exception {
        http.securityMatcher("/actuator/**").authorizeHttpRequests(auth->auth.anyRequest().access((authentication,context)-> {
            Integer port=environment.getProperty("local.management.port",Integer.class,
                    environment.getProperty("management.server.port",Integer.class,0));
            return new AuthorizationDecision(allowed(context.getRequest(),port));
        }));
        return http.build();
    }

    static boolean allowed(HttpServletRequest request, int managementPort) {
        return managementPort>0 && request.getLocalPort()==managementPort
                && LOOPBACK.contains(request.getRemoteAddr()) && request.getMethod().equals("GET")
                && Set.of("/actuator/health","/actuator/prometheus").contains(request.getRequestURI());
    }
}
