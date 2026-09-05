package org.mranked.emoji.application;

public interface TelegramEmojiGateway {
    CustomEmojiAsset fetch(String emojiId);
}
