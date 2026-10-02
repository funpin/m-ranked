-- 0053 — уникальные посетители сайта без cookie
--
-- Страница шлёт маячок при открытии и раз в минуту, пока вкладка видна.
-- Посетитель — хеш BLAKE2b от суточной соли, адреса и браузера (схема
-- Plausible): сам адрес не хранится нигде, а соль живёт одни сутки и затем
-- удаляется, после чего хеш уже нельзя связать ни с адресом, ни с хешем
-- соседних суток. Поэтому посетители считаются за сутки; неделя и месяц —
-- ряд суточных значений.
--
--   * visit_salt — соль текущих суток, одна на все процессы API;
--   * site_visitor — посетители текущих суток: время первого и последнего
--     сигнала и число просмотров. По last_seen считается «сейчас на сайте»;
--   * site_visit_daily — итог закрытых суток. Строки site_visitor прошлых суток
--     API переносит сюда и удаляет вместе с солью.
--
-- Откат: DROP TABLE ops_and_admin.site_visit_daily, ops_and_admin.site_visitor,
--        ops_and_admin.visit_salt;
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS ops_and_admin.visit_salt (
    day date NOT NULL,
    salt bytea NOT NULL,
    CONSTRAINT visit_salt_pkey PRIMARY KEY (day),
    CONSTRAINT visit_salt_length_check CHECK (length(salt) = 32)
);

CREATE TABLE IF NOT EXISTS ops_and_admin.site_visitor (
    day date NOT NULL,
    visitor bytea NOT NULL,
    first_seen timestamp with time zone NOT NULL,
    last_seen timestamp with time zone NOT NULL,
    views integer NOT NULL,
    CONSTRAINT site_visitor_pkey PRIMARY KEY (day, visitor),
    CONSTRAINT site_visitor_visitor_check CHECK (length(visitor) = 16),
    CONSTRAINT site_visitor_views_check CHECK (views >= 0),
    CONSTRAINT site_visitor_seen_check CHECK (last_seen >= first_seen)
);
CREATE INDEX IF NOT EXISTS site_visitor_last_seen_idx ON ops_and_admin.site_visitor (last_seen);

CREATE TABLE IF NOT EXISTS ops_and_admin.site_visit_daily (
    day date NOT NULL,
    visitors integer NOT NULL,
    views integer NOT NULL,
    CONSTRAINT site_visit_daily_pkey PRIMARY KEY (day),
    CONSTRAINT site_visit_daily_counts_check CHECK (visitors >= 0 AND views >= 0)
);

GRANT SELECT, INSERT, DELETE ON TABLE ops_and_admin.visit_salt TO api_write_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops_and_admin.site_visitor TO api_write_admin;
GRANT SELECT, INSERT, UPDATE ON TABLE ops_and_admin.site_visit_daily TO api_write_admin;

COMMIT;
