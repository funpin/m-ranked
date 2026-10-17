-- 0087 — Telegram-бот: настройки, получатели, учёт отправленного и задержанные тревоги.
-- План: docs/superpowers/plans/2026-10-17-telegram-bot.md.
--
-- Семь таблиц bot_* в ops_and_admin и права роли telegram_bot. Бот хранит здесь
-- только своё состояние: тексты постов и данные площадок в них не попадают.
-- Читать из чужих таблиц бот может одну: host_sample (ресурсы Сервера 2, как
-- читает панель управления). Ничего другого роли не выдаётся.
--
-- Роль создаётся заранее: у migration_owner нет CREATEROLE. Перед миграцией, от
-- mranked_bootstrap: CREATE ROLE telegram_bot NOLOGIN; GRANT CONNECT ON DATABASE
-- <база> TO telegram_bot. LOGIN и пароль даёт только включение бота.
--
-- Откат:
--   DROP TABLE ops_and_admin.bot_job, ops_and_admin.bot_week_snapshot, ops_and_admin.bot_held_alert,
--     ops_and_admin.bot_alert_mute, ops_and_admin.bot_announced, ops_and_admin.bot_recipient,
--     ops_and_admin.bot_setting;
--   REVOKE SELECT ON ops_and_admin.host_sample FROM telegram_bot;
--   (роль снимает DROP ROLE telegram_bot от mranked_bootstrap, когда бот не нужен.)
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE ops_and_admin.bot_setting (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_by bigint
);

CREATE TABLE ops_and_admin.bot_recipient (
    chat_id bigint PRIMARY KEY,
    kind text NOT NULL,
    title text NOT NULL DEFAULT '',
    is_admin boolean NOT NULL DEFAULT false,
    alerts boolean NOT NULL DEFAULT false,
    digest boolean NOT NULL DEFAULT false,
    spike boolean NOT NULL DEFAULT false,
    anomaly boolean NOT NULL DEFAULT false,
    added_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    added_by bigint,
    CONSTRAINT bot_recipient_kind_check CHECK (kind IN ('person', 'chat')),
    -- Тревоги и права администратора — только человеку: в чат их не шлют.
    CONSTRAINT bot_recipient_alerts_person CHECK (kind = 'person' OR (alerts = false AND is_admin = false))
);

CREATE TABLE ops_and_admin.bot_announced (
    kind text NOT NULL,
    publication_id uuid NOT NULL,
    level smallint NOT NULL,
    announced_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (kind, publication_id)
);

CREATE TABLE ops_and_admin.bot_alert_mute (
    key text PRIMARY KEY,
    until timestamptz NOT NULL,
    muted_by bigint
);

CREATE TABLE ops_and_admin.bot_held_alert (
    id bigserial PRIMARY KEY,
    event jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE ops_and_admin.bot_week_snapshot (
    day date PRIMARY KEY,
    stats jsonb NOT NULL
);

CREATE TABLE ops_and_admin.bot_job (
    name text PRIMARY KEY,
    last_run_at timestamptz NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    ops_and_admin.bot_setting, ops_and_admin.bot_recipient, ops_and_admin.bot_announced,
    ops_and_admin.bot_alert_mute, ops_and_admin.bot_held_alert, ops_and_admin.bot_week_snapshot,
    ops_and_admin.bot_job
    TO telegram_bot;
GRANT USAGE ON SEQUENCE ops_and_admin.bot_held_alert_id_seq TO telegram_bot;
GRANT SELECT ON TABLE ops_and_admin.host_sample TO telegram_bot;

COMMIT;
