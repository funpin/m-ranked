package org.mranked.emoji.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.Flow;
import org.junit.jupiter.api.Test;
import org.mranked.emoji.application.CustomEmojiNotFoundException;
import tools.jackson.databind.json.JsonMapper;

class TelegramEmojiHttpGatewayTest {
    @Test
    void returnsTelegramBytesAndPreservesAnAllowedContentType() {
        RecordingTransport transport = new RecordingTransport(
                response(200, null, "application/json", """
                        {"type":"webp","emoji":"https://cdn1.telegram.org/emoji/42.webp"}
                        """.getBytes(StandardCharsets.UTF_8)),
                response(200, null, "image/png; charset=binary", new byte[]{3, 1, 4})
        );
        var gateway = new TelegramEmojiHttpGateway(new JsonMapper(), transport);

        var asset = gateway.fetch("42");

        assertThat(asset.content()).containsExactly(3, 1, 4);
        assertThat(asset.mediaType()).isEqualTo("image/png");
        assertThat(transport.uris).containsExactly(
                URI.create("https://t.me/i/emoji/42.json"),
                URI.create("https://cdn1.telegram.org/emoji/42.webp")
        );
    }

    @Test
    void usesStaticFallbacksForAnimatedAssetsAndWebpForUnknownMime() {
        RecordingTransport transport = new RecordingTransport(
                response(200, null, "application/json", """
                        {"type":"tgs","emoji":"https://t.me/animated.tgs",
                         "emoji_static":"https://media.telesco.pe/static.webp"}
                        """.getBytes(StandardCharsets.UTF_8)),
                response(200, null, "application/octet-stream", new byte[]{7})
        );
        var gateway = new TelegramEmojiHttpGateway(new JsonMapper(), transport);

        var asset = gateway.fetch("7");

        assertThat(asset.mediaType()).isEqualTo("image/webp");
        assertThat(transport.uris.get(1))
                .isEqualTo(URI.create("https://media.telesco.pe/static.webp"));
    }

    @Test
    void followsOnlyAllowlistedHttpsRedirects() {
        RecordingTransport allowed = new RecordingTransport(
                response(302, "/i/emoji/42-v2.json", null, new byte[0]),
                response(200, null, "application/json", """
                        {"type":"webm","thumb":"https://cdn.telegram.org/thumb.png"}
                        """.getBytes(StandardCharsets.UTF_8)),
                response(307, "https://edge.telesco.pe/thumb.png", null, new byte[0]),
                response(200, null, "image/png", new byte[]{1})
        );
        var gateway = new TelegramEmojiHttpGateway(new JsonMapper(), allowed);

        assertThat(gateway.fetch("42").content()).containsExactly(1);
        assertThat(allowed.uris).containsExactly(
                URI.create("https://t.me/i/emoji/42.json"),
                URI.create("https://t.me/i/emoji/42-v2.json"),
                URI.create("https://cdn.telegram.org/thumb.png"),
                URI.create("https://edge.telesco.pe/thumb.png")
        );

        RecordingTransport blocked = new RecordingTransport(
                response(200, null, "application/json", """
                        {"type":"png","emoji":"https://cdn.telegram.org/thumb.png"}
                        """.getBytes(StandardCharsets.UTF_8)),
                response(302, "https://attacker.example/private", null, new byte[0])
        );
        var blockedGateway = new TelegramEmojiHttpGateway(new JsonMapper(), blocked);

        assertThatThrownBy(() -> blockedGateway.fetch("42"))
                .isInstanceOf(CustomEmojiNotFoundException.class);
        assertThat(blocked.uris).hasSize(2);
    }

    @Test
    void rejectsNonAllowlistedAssetsNonSuccessesAndBodiesOverTwoMegabytes() {
        for (String target : List.of(
                "http://t.me/a.webp",
                "https://telegram.org/a.webp",
                "https://telesco.pe/a.webp",
                "https://nottelegram.org/a.webp",
                "https://telegram.org.attacker.example/a.webp"
        )) {
            RecordingTransport transport = new RecordingTransport(response(
                    200, null, "application/json",
                    ("{\"type\":\"webp\",\"emoji\":\"" + target + "\"}")
                            .getBytes(StandardCharsets.UTF_8)
            ));
            var gateway = new TelegramEmojiHttpGateway(new JsonMapper(), transport);
            assertThatThrownBy(() -> gateway.fetch("42"))
                    .as(target)
                    .isInstanceOf(CustomEmojiNotFoundException.class);
            assertThat(transport.uris).hasSize(1);
        }

        var missing = new TelegramEmojiHttpGateway(new JsonMapper(),
                new RecordingTransport(response(404, null, "text/html", new byte[0])));
        assertThatThrownBy(() -> missing.fetch("42"))
                .isInstanceOf(CustomEmojiNotFoundException.class);

        var redirectWithoutLocation = new TelegramEmojiHttpGateway(new JsonMapper(),
                new RecordingTransport(response(302, null, "text/html", new byte[0])));
        assertThatThrownBy(() -> redirectWithoutLocation.fetch("42"))
                .isInstanceOf(CustomEmojiNotFoundException.class);

        byte[] tooLarge = new byte[TelegramEmojiHttpGateway.MAX_ASSET_BYTES + 1];
        var oversized = new TelegramEmojiHttpGateway(new JsonMapper(), new RecordingTransport(
                response(200, null, "application/json", """
                        {"type":"png","emoji":"https://cdn.telegram.org/a.png"}
                        """.getBytes(StandardCharsets.UTF_8)),
                response(200, null, "image/png", tooLarge)
        ));
        assertThatThrownBy(() -> oversized.fetch("42"))
                .isInstanceOf(CustomEmojiNotFoundException.class);
    }

    @Test
    void exposesTheExactLegacyAssetAndMimeRules() throws Exception {
        JsonMapper json = new JsonMapper();
        assertThat(TelegramEmojiHttpGateway.selectBrowserAsset(json.readTree(
                "{\"type\":\"GIF\",\"emoji\":\"https://t.me/a.gif\",\"thumb\":\"fallback\"}"
        ))).isEqualTo("https://t.me/a.gif");
        assertThat(TelegramEmojiHttpGateway.selectBrowserAsset(json.readTree(
                "{\"type\":\"webm\",\"emoji\":\"animated\",\"thumb\":\"static\"}"
        ))).isEqualTo("static");
        assertThat(TelegramEmojiHttpGateway.normalizeMediaType("image/jpeg;foo=bar"))
                .isEqualTo("image/jpeg");
        assertThat(TelegramEmojiHttpGateway.normalizeMediaType("Image/PNG"))
                .isEqualTo("image/webp");
    }

    @Test
    void treatsMalformedOrNonObjectMetadataAsAnUpstreamFailure() {
        for (byte[] body : List.of(
                "not-json".getBytes(StandardCharsets.UTF_8),
                "null".getBytes(StandardCharsets.UTF_8),
                "[]".getBytes(StandardCharsets.UTF_8)
        )) {
            var gateway = new TelegramEmojiHttpGateway(
                    new JsonMapper(),
                    new RecordingTransport(response(200, null, "application/json", body))
            );
            assertThatThrownBy(() -> gateway.fetch("42"))
                    .isInstanceOf(CustomEmojiUpstreamException.class);
        }
    }

    @Test
    void treatsMalformedRedirectLocationsAsAnUpstreamFailure() {
        var gateway = new TelegramEmojiHttpGateway(new JsonMapper(), new RecordingTransport(
                response(200, null, "application/json", """
                        {"type":"png","emoji":"https://t.me/a.png"}
                        """.getBytes(StandardCharsets.UTF_8)),
                response(302, "http://[::1", null, new byte[0])
        ));

        assertThatThrownBy(() -> gateway.fetch("42"))
                .isInstanceOf(CustomEmojiUpstreamException.class);
    }

    @Test
    void boundedSubscriberCancelsImmediatelyAfterLimitPlusOneBytes() {
        var subscription = new RecordingSubscription();
        var subscriber = new TelegramEmojiHttpGateway.BoundedBodySubscriber(3);
        subscriber.onSubscribe(subscription);

        subscriber.onNext(List.of(ByteBuffer.wrap(new byte[]{1, 2}), ByteBuffer.wrap(
                new byte[]{3, 4, 5, 6}
        )));

        assertThat(subscriber.getBody().toCompletableFuture().join())
                .containsExactly(1, 2, 3, 4);
        assertThat(subscription.cancelled).isTrue();
        assertThat(subscription.requests).isEqualTo(1);
    }

    @Test
    void boundedSubscriberCompletesBodiesAtTheExactLimit() {
        var subscription = new RecordingSubscription();
        var subscriber = new TelegramEmojiHttpGateway.BoundedBodySubscriber(3);
        subscriber.onSubscribe(subscription);
        subscriber.onNext(List.of(ByteBuffer.wrap(new byte[]{1, 2, 3})));
        subscriber.onComplete();

        assertThat(subscriber.getBody().toCompletableFuture().join())
                .containsExactly(1, 2, 3);
        assertThat(subscription.cancelled).isFalse();
        assertThat(subscription.requests).isEqualTo(2);
    }

    private static TelegramEmojiHttpGateway.UpstreamResponse response(
            int status,
            String location,
            String contentType,
            byte[] body
    ) {
        return new TelegramEmojiHttpGateway.UpstreamResponse(status, location, contentType, body);
    }

    private static final class RecordingTransport implements TelegramEmojiHttpGateway.Transport {
        private final Queue<TelegramEmojiHttpGateway.UpstreamResponse> responses;
        private final List<URI> uris = new ArrayList<>();

        private RecordingTransport(TelegramEmojiHttpGateway.UpstreamResponse... responses) {
            this.responses = new ArrayDeque<>(Arrays.asList(responses));
        }

        @Override
        public TelegramEmojiHttpGateway.UpstreamResponse get(URI uri, int maximumBytes) {
            uris.add(uri);
            TelegramEmojiHttpGateway.UpstreamResponse response = responses.poll();
            if (response == null) {
                throw new AssertionError("unexpected request to " + uri);
            }
            return response;
        }
    }

    private static final class RecordingSubscription implements Flow.Subscription {
        private long requests;
        private boolean cancelled;

        @Override
        public void request(long count) {
            requests += count;
        }

        @Override
        public void cancel() {
            cancelled = true;
        }
    }
}
