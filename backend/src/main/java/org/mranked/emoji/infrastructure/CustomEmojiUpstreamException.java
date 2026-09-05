package org.mranked.emoji.infrastructure;

final class CustomEmojiUpstreamException extends RuntimeException {
    CustomEmojiUpstreamException(String message, Throwable cause) {
        super(message, cause);
    }

    CustomEmojiUpstreamException(String message) {
        super(message);
    }
}
