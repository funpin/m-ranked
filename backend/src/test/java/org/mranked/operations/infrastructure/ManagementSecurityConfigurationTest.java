package org.mranked.operations.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class ManagementSecurityConfigurationTest {
    @Test void scrapeRequiresDedicatedPortLoopbackAndAllowlistedRead() {
        var request=new MockHttpServletRequest("GET","/actuator/prometheus");
        request.setRemoteAddr("127.0.0.1"); request.setLocalPort(8081);
        assertThat(ManagementSecurityConfiguration.allowed(request,8081)).isTrue();
        assertThat(ManagementSecurityConfiguration.allowed(request,8080)).isFalse();
        assertThat(ManagementSecurityConfiguration.allowed(request,0)).isFalse();
        request.setRemoteAddr("192.0.2.1");
        assertThat(ManagementSecurityConfiguration.allowed(request,8081)).isFalse();
        request.setRemoteAddr("127.0.0.1"); request.setRequestURI("/actuator/env");
        assertThat(ManagementSecurityConfiguration.allowed(request,8081)).isFalse();
        request.setRequestURI("/actuator/prometheus"); request.setMethod("POST");
        assertThat(ManagementSecurityConfiguration.allowed(request,8081)).isFalse();
    }
}
