package org.mranked.emoji.application;

import java.util.Objects;

public record CustomEmojiAsset(byte[] content, String mediaType) {
    public CustomEmojiAsset {
        Objects.requireNonNull(content, "content");
        Objects.requireNonNull(mediaType, "mediaType");
        content = content.clone();
    }

    @Override
    public byte[] content() {
        return content.clone();
    }
}
