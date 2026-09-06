package org.mranked.query.application;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import org.junit.jupiter.api.Test;
import org.mranked.analytics.domain.Platform;
class ProviderConfigurationTest {
    @Test void maxPhoneAndSessionWarningsRequireExplicitMissingConfiguration() {
        var missingPhone=new ProviderConfiguration("configured","missing","missing","missing",false);
        var missingSession=new ProviderConfiguration("configured","missing","missing","missing",true);
        assertThat(missingPhone.warning(Platform.MAX)).isEqualTo("max_phone_required");
        assertThat(missingSession.warning(Platform.MAX)).isEqualTo("max_session_required");
        assertThat(missingPhone.warning(Platform.VK)).isEqualTo("vk_token_required");
        assertThat(missingPhone.warning(Platform.RUTUBE)).isEqualTo("rutube_api_disabled");
        assertThat(missingPhone.warning(Platform.ALL)).isNull();
        assertThat(ProviderConfiguration.unknown().warning(Platform.MAX)).isNull();
        assertThat(new ProviderConfiguration("configured","configured","configured","configured",false).warning(Platform.MAX)).isNull();
        assertThat(missingPhone.representationVersion("same-build"))
                .isNotEqualTo(missingSession.representationVersion("same-build"))
                .isNotEqualTo(missingPhone.representationVersion("different-build"))
                .isEqualTo(new ProviderConfiguration("configured","missing","missing","missing",false).representationVersion("same-build"));
    }
    @Test void missingAndConfiguredRequireExplicitNonSecretConfiguration() {
        assertThat(ProviderConfiguration.unknown().status(Platform.VK)).isEqualTo("unknown");
        var configured=new ProviderConfiguration("configured","missing","unknown","configured");
        assertThat(configured.status(Platform.VK)).isEqualTo("missing");
        assertThat(configured.status(Platform.TELEGRAM)).isEqualTo("configured");
        assertThat(configured.status(Platform.ALL)).isEqualTo("unknown");
        assertThatThrownBy(()->new ProviderConfiguration("token-value","missing","unknown","unknown"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageNotContaining("token-value");
    }
}
