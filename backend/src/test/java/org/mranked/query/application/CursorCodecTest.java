package org.mranked.query.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CursorCodecTest {
    private final CursorCodec codec = new CursorCodec();

    @Test
    void roundTripsOpaqueUuidCursor() {
        UUID id = UUID.fromString("00000000-0000-0000-0000-000000000123");

        String encoded = codec.encode(id);

        assertThat(encoded).doesNotContain(id.toString());
        assertThat(codec.decode(encoded)).contains(id);
        assertThat(codec.decode(null)).isEmpty();
        assertThat(codec.decode("   ")).isEmpty();
    }

    @Test
    void rejectsMalformedAndNonUuidCursors() {
        String shortValue = Base64.getUrlEncoder().withoutPadding()
                .encodeToString("not-a-uuid".getBytes(StandardCharsets.US_ASCII));

        assertThatThrownBy(() -> codec.decode("%%%"))
                .isInstanceOf(InvalidCursorException.class);
        assertThatThrownBy(() -> codec.decode(shortValue))
                .isInstanceOf(InvalidCursorException.class);
    }
}
