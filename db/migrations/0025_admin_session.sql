-- 0025 — серверные административные сессии и одноразовость TOTP
--
-- До этой миграции второй фактор проверялся на каждом запросе, а список
-- использованных кодов жил в памяти процесса. Из этого следовало сразу два
-- изъяна: обычный многозапросный сценарий администратора ломался на втором
-- запросе, а перезапуск или второй воркер обнуляли защиту от повтора.
--
-- Теперь код тратится ровно один раз — при создании сессии, — и обе таблицы
-- лежат в базе, то есть переживают перезапуск и общие для всех воркеров.

-- Учёт кодов TOTP. Строка на пару «субъект и номер тридцатисекундного шага»:
-- consumed_at помечает потраченный код, failures считает неудачные попытки в
-- том же шаге. Когда попыток слишком много, шаг сгорает целиком, но следующий
-- шаг остаётся доступным — блокировки учётной записи здесь нет.
CREATE TABLE ops_and_admin.admin_totp_use (
    subject text NOT NULL,
    totp_counter bigint NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT admin_totp_use_pkey PRIMARY KEY (subject, totp_counter),
    CONSTRAINT admin_totp_use_subject_check CHECK ((length(subject) >= 1) AND (length(subject) <= 200)),
    CONSTRAINT admin_totp_use_failures_check CHECK ((failures >= 0) AND (failures <= 1000)),
    CONSTRAINT admin_totp_use_counter_check CHECK (totp_counter > 0)
);
CREATE INDEX admin_totp_use_created_at_idx ON ops_and_admin.admin_totp_use (created_at);

COMMENT ON TABLE ops_and_admin.admin_totp_use IS
  'Одноразовость TOTP: потраченные коды и сгоревшие от перебора шаги. Секрет здесь не хранится.';

-- Сессии администратора. Хранится только дайджест случайного токена: сам токен
-- существует лишь в куке браузера, поэтому чтение таблицы не даёт входа.
CREATE TABLE ops_and_admin.admin_session (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    token_digest text NOT NULL,
    subject text NOT NULL,
    roles text[] NOT NULL,
    auth_strength text NOT NULL,
    source_digest text,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    idle_expires_at timestamp with time zone NOT NULL,
    absolute_expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_reason text,
    CONSTRAINT admin_session_pkey PRIMARY KEY (id),
    CONSTRAINT admin_session_token_digest_key UNIQUE (token_digest),
    CONSTRAINT admin_session_token_digest_check CHECK (token_digest ~ '^[0-9a-f]{64}$'::text),
    CONSTRAINT admin_session_subject_check CHECK ((length(subject) >= 1) AND (length(subject) <= 200)),
    -- password_only допустим только на стенде с выключенным вторым фактором.
    CONSTRAINT admin_session_auth_strength_check CHECK (auth_strength = ANY (ARRAY['password_totp'::text, 'password_only'::text])),
    CONSTRAINT admin_session_roles_check CHECK ((cardinality(roles) >= 1) AND (cardinality(roles) <= 3)
        AND (roles <@ ARRAY['VIEWER'::text, 'EDITOR'::text, 'ADMIN'::text])),
    CONSTRAINT admin_session_window_check CHECK ((absolute_expires_at > created_at)
        AND (idle_expires_at <= absolute_expires_at)),
    CONSTRAINT admin_session_source_digest_check CHECK ((source_digest IS NULL) OR (source_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT admin_session_revoked_reason_check CHECK ((revoked_reason IS NULL) OR (revoked_reason ~ '^[a-z_]{1,32}$'::text)),
    CONSTRAINT admin_session_revoked_check CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
);
CREATE INDEX admin_session_subject_idx ON ops_and_admin.admin_session (subject) WHERE revoked_at IS NULL;
CREATE INDEX admin_session_absolute_expires_at_idx ON ops_and_admin.admin_session (absolute_expires_at);

COMMENT ON TABLE ops_and_admin.admin_session IS
  'Серверные сессии админки: дайджест токена, роли на момент входа, границы простоя и жизни, отзыв.';
COMMENT ON COLUMN ops_and_admin.admin_session.token_digest IS
  'SHA-256 от случайного токена в 256 бит. Сам токен уходит только в куку __Host-.';
COMMENT ON COLUMN ops_and_admin.admin_session.source_digest IS
  'Отпечаток адреса источника для расследования, не сам адрес.';

-- Счётчик неудачных входов по адресу источника. Именно адрес, а не учётная
-- запись: блокировка по имени позволяла бы чужому перебору закрыть вход
-- законному администратору.
CREATE TABLE ops_and_admin.admin_login_failure (
    source_digest text NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    window_started_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    last_failure_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT admin_login_failure_pkey PRIMARY KEY (source_digest),
    CONSTRAINT admin_login_failure_source_digest_check CHECK (source_digest ~ '^[0-9a-f]{64}$'::text),
    CONSTRAINT admin_login_failure_failures_check CHECK ((failures >= 0) AND (failures <= 1000000))
);
CREATE INDEX admin_login_failure_window_idx ON ops_and_admin.admin_login_failure (window_started_at);

COMMENT ON TABLE ops_and_admin.admin_login_failure IS
  'Замедление перебора по адресу источника. Учётная запись здесь не блокируется.';

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops_and_admin.admin_session TO api_write_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops_and_admin.admin_totp_use TO api_write_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops_and_admin.admin_login_failure TO api_write_admin;
