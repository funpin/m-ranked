package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.time.Instant;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class OfficialRatingParserTest {
    private final JsonMapper json=new JsonMapper();
    @Test void agreesWithUnchangedPythonOracleIncludingCasefoldNullZeroAndTies() throws Exception {
        try(var input=getClass().getResourceAsStream("/admin/official-rating-legacy-golden.json")) {
            var fixtures=json.readTree(input);
            for(var fixture:fixtures.path("cases")) {
                byte[] payload=json.writeValueAsBytes(fixture.path("payload"));
                var actual=OfficialRatingParser.parse(payload,2026,"https://www.m-rating.ru/data.json",Instant.parse("2026-09-05T00:00:00Z"));
                assertThat(actual.period()).isEqualTo(fixture.path("period").asString());
                for(var category:fixture.path("rankings").properties()) {
                    String key=category.getKey().equals("tg")?"telegram":category.getKey();
                    assertThat(actual.rankings().get(key)).hasSize(category.getValue().size());
                    for(var expected:category.getValue().properties()) {
                        var rating=actual.rankings().get(key).get(expected.getKey());
                        assertThat(rating.rank()).as(key+"/"+expected.getKey()).isEqualTo(expected.getValue().get(0).asInt());
                        assertThat(rating.score().doubleValue()).isEqualTo(expected.getValue().get(1).doubleValue());
                    }
                }
                assertThat(actual.sourceSha256()).isEqualTo(java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(payload)));
            }
        }
    }
    @Test void rejectsInvalidOrUnboundedDataAndDoesNotPreserveUnknownProviderFields() {
        for(String body:java.util.List.of("{}","{\"months\":[]}","{\"months\":[{\"items\":[{\"scores\":{\"tg\":\"NaN\"}}]}]}"))
            assertThatThrownBy(()->OfficialRatingParser.parse(body.getBytes(StandardCharsets.UTF_8),2026,"https://www.m-rating.ru/data.json",Instant.now())).isInstanceOf(RuntimeException.class);
        var actual=OfficialRatingParser.parse("{\"secret\":\"never-copy\",\"months\":[{\"items\":[{\"code\":\"19\",\"name\":\"MEPHI\",\"token\":\"never-copy\",\"scores\":{\"tg\":1,\"credential\":\"never-copy\"}}]}]}".getBytes(StandardCharsets.UTF_8),2026,"https://www.m-rating.ru/data.json",Instant.now());
        assertThat(json.writeValueAsString(actual.evidence())).doesNotContain("never-copy","token","credential","secret");
        assertThat(OfficialRatingParser.year("const conf={year:2026,ratingsJson:'ratings.json'}")).isEqualTo(2026);
        assertThat(OfficialRatingParser.ratingsPath("const conf={year:2026,ratingsJson:'ratings.json'}")).isEqualTo("ratings.json");
    }
}
