package org.mranked.emoji.infrastructure;

import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.Set;
import org.mranked.operations.infrastructure.PinnedHttpsClient;

final class PinnedEmojiTransport implements TelegramEmojiHttpGateway.Transport, AutoCloseable {
    private final PinnedHttpsClient client = new PinnedHttpsClient();
    @Override public TelegramEmojiHttpGateway.UpstreamResponse get(URI uri, int maximumBytes) throws IOException {
        return get(uri, maximumBytes, Duration.ofSeconds(10).toNanos());
    }
    @Override public TelegramEmojiHttpGateway.UpstreamResponse get(URI uri, int maximumBytes, long remainingNanos) throws IOException {
        if (!TelegramEmojiHttpGateway.isAllowedUri(uri)) throw new IOException("emoji target is prohibited");
        var response = client.fetch(uri, maximumBytes, Duration.ofNanos(remainingNanos),
                                    Set.of(uri.getHost().toLowerCase(java.util.Locale.ROOT)));
        return new TelegramEmojiHttpGateway.UpstreamResponse(response.statusCode(), response.location(),
                                                            response.contentType(), response.body());
    }
    @Override public void close() throws IOException { client.close(); }
}
