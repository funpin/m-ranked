package org.mranked.emoji.infrastructure;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Flow;
import org.mranked.emoji.application.CustomEmojiAsset;
import org.mranked.emoji.application.CustomEmojiNotFoundException;
import org.mranked.emoji.application.TelegramEmojiGateway;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
public final class TelegramEmojiHttpGateway implements TelegramEmojiGateway {
    static final int MAX_ASSET_BYTES = 2_000_000;
    private static final int MAX_METADATA_BYTES = 64 * 1024;
    private static final int MAX_REDIRECTS = 20;
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(10);
    private static final Set<String> BROWSER_IMAGE_TYPES = Set.of(
            "webp", "png", "gif", "jpg", "jpeg"
    );
    private static final Set<String> ALLOWED_MEDIA_TYPES = Set.of(
            "image/webp", "image/png", "image/gif", "image/jpeg"
    );

    private final ObjectMapper objectMapper;
    private final Transport transport;

    @Autowired
    public TelegramEmojiHttpGateway(ObjectMapper objectMapper) {
        this(objectMapper, new PinnedEmojiTransport());
    }

    TelegramEmojiHttpGateway(ObjectMapper objectMapper, Transport transport) {
        this.objectMapper = objectMapper;
        this.transport = transport;
    }

    @Override
    public CustomEmojiAsset fetch(String emojiId) {
        long deadline = System.nanoTime() + REQUEST_TIMEOUT.toNanos();
        URI metadataUri = URI.create("https://t.me/i/emoji/" + emojiId + ".json");
        UpstreamResponse metadata = getFollowingAllowedRedirects(
                metadataUri, MAX_METADATA_BYTES, deadline
        );
        if (metadata.statusCode() != 200 || metadata.body().length > MAX_METADATA_BYTES) {
            throw new CustomEmojiNotFoundException();
        }

        String target;
        try {
            JsonNode payload = objectMapper.readTree(metadata.body());
            if (payload == null || !payload.isObject()) {
                throw new IllegalArgumentException("metadata root must be an object");
            }
            target = selectBrowserAsset(payload);
        } catch (RuntimeException exception) {
            throw new CustomEmojiUpstreamException("Telegram emoji metadata is invalid", exception);
        }
        URI assetUri = allowedUri(target);
        if (assetUri == null) {
            throw new CustomEmojiNotFoundException();
        }

        UpstreamResponse image = getFollowingAllowedRedirects(assetUri, MAX_ASSET_BYTES, deadline);
        if (image.statusCode() != 200 || image.body().length > MAX_ASSET_BYTES) {
            throw new CustomEmojiNotFoundException();
        }
        String mediaType = normalizeMediaType(image.contentType());
        return new CustomEmojiAsset(image.body(), mediaType);
    }

    private UpstreamResponse getFollowingAllowedRedirects(URI initialUri, int maximumBytes, long deadline) {
        URI current = initialUri;
        for (int redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount++) {
            if (!isAllowedUri(current)) {
                throw new CustomEmojiNotFoundException();
            }
            UpstreamResponse response;
            try {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) throw new IOException("emoji total deadline expired");
                response = transport.get(current, maximumBytes, remaining);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new CustomEmojiUpstreamException("Telegram emoji request was interrupted", exception);
            } catch (IOException exception) {
                throw new CustomEmojiUpstreamException("Telegram emoji request failed", exception);
            }
            if (!isRedirect(response.statusCode())) {
                return response;
            }
            if (response.location() == null) {
                return response;
            }
            if (redirectCount == MAX_REDIRECTS) {
                throw new CustomEmojiUpstreamException("Telegram emoji redirect limit was exceeded");
            }
            try {
                current = current.resolve(new URI(response.location()));
            } catch (IllegalArgumentException | URISyntaxException exception) {
                throw new CustomEmojiUpstreamException(
                        "Telegram emoji redirect location is invalid", exception
                );
            }
        }
        throw new CustomEmojiUpstreamException("Telegram emoji redirect limit was exceeded");
    }

    static String selectBrowserAsset(JsonNode payload) {
        String type = text(payload, "type").toLowerCase(Locale.ROOT);
        if (BROWSER_IMAGE_TYPES.contains(type)) {
            return firstNonEmpty(text(payload, "emoji"), text(payload, "thumb"));
        }
        return firstNonEmpty(text(payload, "thumb"), text(payload, "emoji_static"));
    }

    static boolean isAllowedUri(URI uri) {
        if (uri == null || !"https".equals(uri.getScheme()) || uri.getHost() == null
                || uri.getRawUserInfo() != null || uri.getPort() != -1 && uri.getPort() != 443
                || uri.getRawFragment() != null) {
            return false;
        }
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        return host.equals("t.me")
                || host.endsWith(".telegram.org")
                || host.endsWith(".telesco.pe");
    }

    static String normalizeMediaType(String contentType) {
        String candidate = contentType == null ? "" : contentType.split(";", 2)[0];
        return ALLOWED_MEDIA_TYPES.contains(candidate) ? candidate : "image/webp";
    }

    private static URI allowedUri(String target) {
        if (target == null || !target.startsWith("https://")) {
            return null;
        }
        try {
            URI uri = new URI(target);
            return isAllowedUri(uri) ? uri : null;
        } catch (URISyntaxException exception) {
            return null;
        }
    }

    private static String text(JsonNode payload, String field) {
        JsonNode value = payload == null ? null : payload.get(field);
        if (value == null || value.isNull()) {
            return "";
        }
        return value.asText("");
    }

    private static String firstNonEmpty(String first, String second) {
        if (first != null && !first.isEmpty()) {
            return first;
        }
        return second == null || second.isEmpty() ? "" : second;
    }

    private static boolean isRedirect(int statusCode) {
        return statusCode == 301 || statusCode == 302 || statusCode == 303
                || statusCode == 307 || statusCode == 308;
    }

    @FunctionalInterface
    interface Transport {
        UpstreamResponse get(URI uri, int maximumBytes) throws IOException, InterruptedException;
        default UpstreamResponse get(URI uri, int maximumBytes, long remainingNanos) throws IOException, InterruptedException {
            return get(uri, maximumBytes);
        }
    }

    @jakarta.annotation.PreDestroy
    public void close() throws Exception {
        if (transport instanceof AutoCloseable closeable) closeable.close();
    }

    record UpstreamResponse(
            int statusCode,
            String location,
            String contentType,
            byte[] body
    ) {
    }

    static final class BoundedBodySubscriber implements HttpResponse.BodySubscriber<byte[]> {
        private final int maximumBytes;
        private final ByteArrayOutputStream output;
        private final CompletableFuture<byte[]> body = new CompletableFuture<>();
        private Flow.Subscription subscription;
        private boolean completed;

        BoundedBodySubscriber(int maximumBytes) {
            if (maximumBytes < 0 || maximumBytes == Integer.MAX_VALUE) {
                throw new IllegalArgumentException("maximumBytes is outside the supported range");
            }
            this.maximumBytes = maximumBytes;
            this.output = new ByteArrayOutputStream(Math.min(maximumBytes + 1, 8 * 1024));
        }

        @Override
        public CompletionStage<byte[]> getBody() {
            return body;
        }

        @Override
        public void onSubscribe(Flow.Subscription incoming) {
            if (subscription != null) {
                incoming.cancel();
                return;
            }
            subscription = incoming;
            incoming.request(1);
        }

        @Override
        public void onNext(List<ByteBuffer> buffers) {
            if (completed) {
                return;
            }
            for (ByteBuffer buffer : buffers) {
                int remainingCapacity = maximumBytes + 1 - output.size();
                if (remainingCapacity <= 0) {
                    completeOversized();
                    return;
                }
                int bytesToCopy = Math.min(remainingCapacity, buffer.remaining());
                byte[] chunk = new byte[bytesToCopy];
                buffer.get(chunk);
                output.writeBytes(chunk);
                if (output.size() > maximumBytes) {
                    completeOversized();
                    return;
                }
            }
            subscription.request(1);
        }

        @Override
        public void onError(Throwable throwable) {
            if (!completed) {
                completed = true;
                body.completeExceptionally(throwable);
            }
        }

        @Override
        public void onComplete() {
            if (!completed) {
                completed = true;
                body.complete(output.toByteArray());
            }
        }

        private void completeOversized() {
            completed = true;
            subscription.cancel();
            body.complete(output.toByteArray());
        }
    }
}
