package org.mranked.admin.application;

import static org.assertj.core.api.Assertions.*;
import org.junit.jupiter.api.Test;

class AccountReferenceTest {
    @Test void preservesLegacyTelegramPreviewPostAndCaseRules() {
        var actual=AccountReference.parse("telegram"," https://t.me/s/Some_Channel/42 ","","");
        assertThat(actual.username()).isEqualTo("Some_Channel");
        assertThat(actual.externalKey()).isEqualTo("some_channel");
        assertThat(actual.url()).isEqualTo("https://t.me/Some_Channel");
        assertThat(AccountReference.parse("telegram","@@12345",null,null).username()).isEqualTo("12345");
        assertThatThrownBy(()->AccountReference.parse("telegram","abcd",null,null)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void preservesLegacyVkCyrillicQueryAndSignedIdRules() {
        assertThat(AccountReference.parse("vk","https://m.vk.ru/Университет?x=1",null,null).externalKey()).isEqualTo("Университет");
        assertThat(AccountReference.parse("vk","-12345",null,null).externalKey()).isEqualTo("-12345");
        assertThatThrownBy(()->AccountReference.parse("vk","bad!",null,null)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void maxAndRutubeUseLastPathComponentAndNeverFetchReferences() {
        assertThat(AccountReference.parse("rutube","https://rutube.ru/channel/123456/",null,null).externalKey()).isEqualTo("123456");
        assertThat(AccountReference.parse("max","@SomeChannel",null,null).externalKey()).isEqualTo("SomeChannel");
        assertThat(AccountReference.parse("max","http://max.ru/SomeChannel",null,null).url()).isEqualTo("http://max.ru/SomeChannel");
        assertThatThrownBy(()->AccountReference.parse("max","https://name:password@example.com/channel",null,null)).isInstanceOf(IllegalArgumentException.class);
    }
}
