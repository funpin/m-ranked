package org.mranked.admin.web;

import static org.assertj.core.api.Assertions.*;
import org.junit.jupiter.api.Test;
import org.mranked.admin.application.LegacyFormException;
import org.springframework.mock.web.MockHttpServletRequest;

class LegacyFormExceptionHandlerTest {
    @Test void onlyExplicitLegacyExceptionExposesWhitelistedTextWhileModernErrorsStayGeneric() {
        var handler=new AdminRfc9457ExceptionHandler();
        var request=new MockHttpServletRequest("POST","/api/v1/admin/catalog/legacy-command");
        var legacy=handler.legacyForm(LegacyFormException.safe("MAX chat_id должен быть числом"),request);
        assertThat(legacy.getStatusCode().value()).isEqualTo(400);
        assertThat(legacy.getHeaders().getCacheControl()).isEqualTo("no-store");
        assertThat(legacy.getBody().getType().toString()).isEqualTo("urn:m-ranked:problem:legacy-form");
        assertThat(legacy.getBody().getDetail()).isEqualTo("MAX chat_id должен быть числом");
        assertThat(handler.legacyForm(LegacyFormException.safe("password=secret"),request).getBody().getDetail()).doesNotContain("secret");
        var modern=handler.invalidRequest(new IllegalArgumentException("MAX chat_id должен быть числом"),request);
        assertThat(modern.getBody().getType().toString()).isEqualTo("urn:m-ranked:problem:invalid-request");
        assertThat(modern.getBody().getDetail()).isEqualTo("One or more request parameters are invalid");
    }
}
