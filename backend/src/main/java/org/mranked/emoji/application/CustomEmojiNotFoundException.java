package org.mranked.emoji.application;

public final class CustomEmojiNotFoundException extends RuntimeException {
    public static final String LEGACY_DETAIL = "Реакция не найдена";

    public CustomEmojiNotFoundException() {
        super(LEGACY_DETAIL);
    }
}
