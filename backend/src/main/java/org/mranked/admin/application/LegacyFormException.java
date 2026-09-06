package org.mranked.admin.application;

import java.util.Set;

/** Fixed public form errors only; upstream messages and submitted values are never exposed. */
public final class LegacyFormException extends IllegalArgumentException {
    private static final Set<String> SAFE = Set.of(
        "Укажите название вуза", "Укажите сокращение", "Institution name and short name are required",
        "Укажите хотя бы один аккаунт", "Укажите аккаунт или ссылку", "Не удалось определить аккаунт",
        "Не удалось определить сообщество ВКонтакте", "Telegram-каналы добавляются через основную форму мониторинга",
        "MAX chat_id должен быть числом", "Некорректная ссылка max", "Некорректная ссылка rutube",
        "Не удалось определить max", "Не удалось определить rutube", "Invalid Telegram channel username",
        "Аккаунт должен использовать HTTP(S)-ссылку без учётных данных");

    private LegacyFormException(String message) { super(message); }

    public static LegacyFormException safe(String message) {
        return new LegacyFormException(message != null && SAFE.contains(message)
            ? message : "One or more request parameters are invalid");
    }
}
