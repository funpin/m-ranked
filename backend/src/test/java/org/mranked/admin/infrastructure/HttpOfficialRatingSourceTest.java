package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.mranked.operations.infrastructure.PinnedHttpsClient;

class HttpOfficialRatingSourceTest {
    @Test void configAndRatingsShareOneDeadlineAndEveryHopUsesThePinnedHostPolicy() {
        var requests=new ArrayList<java.net.URI>();var deadlines=new ArrayList<java.time.Duration>();
        var source=new HttpOfficialRatingSource((uri,maximum,timeout,hosts)->{
            requests.add(uri);deadlines.add(timeout);
            assertThat(hosts).isEqualTo(Set.of("www.m-rating.ru","m-rating.ru"));
            return switch(requests.size()) {
                case 1 -> new PinnedHttpsClient.Response(302,"/versioned/config.js","text/plain",new byte[0]);
                case 2 -> {
                    assertThat(maximum).isEqualTo(1_000_000);
                    yield response("const config={year:2026, ratingsJson:'data/ratings.json'};");
                }
                default -> {
                    assertThat(maximum).isEqualTo(8*1024*1024);
                    yield response("{\"months\":[{\"name\":\"Август\",\"items\":[{\"code\":\"19\",\"scores\":{\"social\":0}}]}]}");
                }
            };
        });
        assertThat(source.fetch().sourceUrl()).isEqualTo("https://www.m-rating.ru/data/ratings.json");
        assertThat(requests.stream().map(java.net.URI::getPath)).containsExactly("/js/config.js","/versioned/config.js","/data/ratings.json");
        assertThat(deadlines).allMatch(value->value.compareTo(java.time.Duration.ofSeconds(30))<=0);
        assertThat(deadlines.get(2)).isLessThanOrEqualTo(deadlines.get(0));
    }
    @Test void redirectLoopsOversizedResponsesAndProviderErrorsFailWithoutSensitiveMessages() {
        var attempts=new java.util.concurrent.atomic.AtomicInteger();
        var redirects=new HttpOfficialRatingSource((uri,max,timeout,hosts)->{attempts.incrementAndGet();return new PinnedHttpsClient.Response(302,"/again",null,new byte[0]);});
        assertThatThrownBy(redirects::fetch).isInstanceOf(IllegalStateException.class).hasMessage("Official rating source is unavailable");
        assertThat(attempts.get()).isEqualTo(4);
        var oversized=new HttpOfficialRatingSource((uri,max,timeout,hosts)->new PinnedHttpsClient.Response(200,null,"text/plain",new byte[max+1]));
        assertThatThrownBy(oversized::fetch).isInstanceOf(IllegalStateException.class);
        var rejected=new HttpOfficialRatingSource((uri,max,timeout,hosts)->{throw new java.io.IOException("secret-provider-url-token");});
        assertThatThrownBy(rejected::fetch).hasMessage("Official rating source is unavailable").hasNoCause();
    }
    private static PinnedHttpsClient.Response response(String body) { return new PinnedHttpsClient.Response(200,null,"application/json",body.getBytes(StandardCharsets.UTF_8)); }
}
