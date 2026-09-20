-- 0029 — durable transfer outbox/inbox для канонических account batch
-- Причина: outbox_event содержит только уведомления инвалидации и ссылается
-- на dataset_revision; он не хранит payload, необходимый для replay после P2.
-- Откат: сначала выключить COLLECTOR_TRANSFER_MODE, затем удалить новые таблицы
-- и их последовательности. Существующие таблицы, функции и данные не меняются.

CREATE TABLE ops_and_admin.transfer_outbox (
    cursor bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id uuid NOT NULL,
    producer_id text NOT NULL,
    schema_version integer NOT NULL DEFAULT 1,
    payload bytea NOT NULL,
    payload_sha256 text NOT NULL,
    record_count integer NOT NULL,
    uncompressed_bytes bigint NOT NULL,
    state text NOT NULL DEFAULT 'pending',
    publish_attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    sealed_at timestamptz,
    sent_at timestamptz,
    acknowledged_at timestamptz,
    ack_receipt_id uuid,
    ack_checksum text,
    last_error_code text,
    terminal_at timestamptz,
    terminal_reason text,
    UNIQUE (producer_id, batch_id),
    CHECK (btrim(producer_id) <> '' AND length(producer_id) <= 128),
    CHECK (schema_version > 0),
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (record_count BETWEEN 1 AND 500),
    CHECK (octet_length(payload) BETWEEN 1 AND 8388608),
    CHECK (uncompressed_bytes BETWEEN 1 AND 33554432),
    CHECK (publish_attempts >= 0),
    CHECK (state IN ('pending','sealed','sent','acknowledged','terminal')),
    CHECK ((state <> 'acknowledged') OR
           (ack_receipt_id IS NOT NULL AND ack_checksum IS NOT NULL AND acknowledged_at IS NOT NULL)),
    CHECK (ack_checksum IS NULL OR ack_checksum ~ '^[0-9a-f]{64}$'),
    CHECK ((state = 'terminal') =
           (terminal_at IS NOT NULL AND terminal_reason IS NOT NULL AND btrim(terminal_reason) <> ''))
);

CREATE INDEX transfer_outbox_delivery_idx
    ON ops_and_admin.transfer_outbox (available_at, cursor)
    WHERE state IN ('sealed','sent');
CREATE INDEX transfer_outbox_backlog_idx
    ON ops_and_admin.transfer_outbox (producer_id, cursor)
    WHERE state <> 'acknowledged' AND state <> 'terminal';

CREATE TABLE ops_and_admin.transfer_inbox (
    receipt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    producer_id text NOT NULL,
    batch_id uuid NOT NULL,
    schema_version integer NOT NULL,
    first_cursor bigint NOT NULL,
    last_cursor bigint NOT NULL,
    payload bytea,
    checksum text NOT NULL,
    record_count integer NOT NULL,
    uncompressed_bytes bigint NOT NULL,
    state text NOT NULL DEFAULT 'received',
    accepted_count integer NOT NULL DEFAULT 0,
    duplicate_count integer NOT NULL DEFAULT 0,
    deferred_count integer NOT NULL DEFAULT 0,
    rejected_count integer NOT NULL DEFAULT 0,
    reason_code text,
    received_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    verified_at timestamptz,
    applying_at timestamptz,
    applied_at timestamptz,
    applied_cursor bigint,
    UNIQUE (producer_id, batch_id),
    CHECK (btrim(producer_id) <> '' AND length(producer_id) <= 128),
    CHECK (schema_version > 0),
    CHECK (first_cursor > 0 AND last_cursor >= first_cursor),
    CHECK (checksum ~ '^[0-9a-f]{64}$'),
    CHECK (record_count BETWEEN 1 AND 500),
    CHECK (uncompressed_bytes BETWEEN 1 AND 33554432),
    CHECK (state IN ('received','verified','applying','applied','quarantined')),
    CHECK (accepted_count >= 0 AND duplicate_count >= 0 AND deferred_count >= 0 AND rejected_count >= 0),
    CHECK (accepted_count + duplicate_count + deferred_count + rejected_count <= record_count),
    CHECK ((state <> 'applied') OR
           (applied_cursor = last_cursor AND accepted_count + duplicate_count + deferred_count + rejected_count = record_count)),
    CHECK ((state <> 'quarantined') OR (reason_code IS NOT NULL AND applied_cursor IS NULL)),
    CHECK ((state = 'quarantined') OR payload IS NOT NULL),
    CHECK (reason_code IS NULL OR reason_code ~ '^[a-z0-9_]{1,64}$')
);

CREATE INDEX transfer_inbox_apply_idx
    ON ops_and_admin.transfer_inbox (producer_id, first_cursor)
    WHERE state IN ('received','verified','applying');

CREATE TABLE ops_and_admin.transfer_inbox_event (
    receipt_id uuid NOT NULL REFERENCES ops_and_admin.transfer_inbox(receipt_id),
    event_index smallint NOT NULL,
    event_id uuid NOT NULL UNIQUE,
    outcome text NOT NULL DEFAULT 'deferred',
    reason_code text,
    PRIMARY KEY (receipt_id, event_index),
    CHECK (event_index BETWEEN 0 AND 499),
    CHECK (outcome IN ('accepted','duplicate','deferred','rejected')),
    CHECK (reason_code IS NULL OR reason_code ~ '^[a-z0-9_]{1,64}$')
);

-- Профиль A использует collector_ingest и для локального DataAdapter. Права
-- ограничены только двумя транспортными таблицами и нужной sequence.
GRANT SELECT, INSERT, UPDATE ON TABLE ops_and_admin.transfer_outbox TO collector_ingest;
GRANT USAGE, SELECT ON SEQUENCE ops_and_admin.transfer_outbox_cursor_seq TO collector_ingest;
GRANT SELECT, INSERT, UPDATE ON TABLE ops_and_admin.transfer_inbox TO collector_ingest;
GRANT SELECT, INSERT, UPDATE ON TABLE ops_and_admin.transfer_inbox_event TO collector_ingest;

-- outbox_worker остаётся транспортной ролью профиля B: без прав на ingest.
GRANT SELECT, UPDATE ON TABLE ops_and_admin.transfer_outbox TO outbox_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE ops_and_admin.transfer_inbox TO outbox_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE ops_and_admin.transfer_inbox_event TO outbox_worker;

GRANT SELECT ON TABLE ops_and_admin.transfer_outbox, ops_and_admin.transfer_inbox TO maintenance;
GRANT SELECT ON TABLE ops_and_admin.transfer_inbox_event TO maintenance;
GRANT SELECT ON TABLE ops_and_admin.transfer_outbox, ops_and_admin.transfer_inbox TO storage_observer;
GRANT SELECT ON TABLE ops_and_admin.transfer_inbox_event TO storage_observer;
