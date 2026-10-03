-- 0057 — серверы, размещение резервных копий и архивов, политики, поколения
-- холодного архива (ADR-016).
--
-- server_node — реестр серверов. Имя узла совпадает с именем в mTLS-сертификате
-- его отправителя (server-1 → производитель server-1/<partition>). Агент узла
-- раз в минуту присылает отчёт (диски, память, файлы хранилища) и получает
-- задания на копирование.
--
-- storage_object / storage_replica — неизменяемые файлы (дампы базы, полные и
-- просмотровые файлы холодного архива) и их копии по серверам. Где файлам
-- быть, решает политика storage; копию удаляют, только когда все нужные копии
-- подтверждены по SHA-256 на месте назначения.
--
-- runtime_policy — политики сбора, хранения и анализа, которые панель меняет
-- без перезапуска: агенты разносят их по серверам, службы перечитывают.
--
-- cold_archive_generation — выгрузки месяца. Месяц закрывается для записи
-- только на время выгрузки, копирования и удаления партиции; после удаления
-- снова открыт, и поздние замеры уходят в следующее поколение.
--
-- Откат: функции и таблицы этой миграции удаляются; drop_v22 не вызывался —
-- данные не тронуты. Если вызывался, месяц читается из архива, а восстановление
-- — operations/runbooks/COLD_ARCHIVE.md.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS ops_and_admin.server_node (
    id text PRIMARY KEY,
    display_name text NOT NULL,
    role text NOT NULL,
    platforms text[] NOT NULL DEFAULT '{}',
    state text NOT NULL DEFAULT 'pending',
    stores_objects boolean NOT NULL DEFAULT true,
    reserve_bytes bigint NOT NULL DEFAULT 3221225472,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_by text,
    last_seen_at timestamptz,
    agent_version text,
    report jsonb NOT NULL DEFAULT '{}',
    CONSTRAINT server_node_id_check CHECK (id ~ '^[a-z][a-z0-9-]{1,39}$'),
    CONSTRAINT server_node_name_check CHECK (btrim(display_name) <> '' AND length(display_name) <= 80),
    CONSTRAINT server_node_role_check CHECK (role IN ('main', 'collector', 'storage')),
    CONSTRAINT server_node_state_check CHECK (state IN ('pending', 'active', 'draining', 'disabled')),
    CONSTRAINT server_node_platforms_check CHECK (platforms <@ ARRAY['telegram', 'vk', 'max', 'rutube']::text[]),
    CONSTRAINT server_node_reserve_check CHECK (reserve_bytes >= 0),
    CONSTRAINT server_node_report_check CHECK (jsonb_typeof(report) = 'object')
);
CREATE UNIQUE INDEX IF NOT EXISTS server_node_single_main ON ops_and_admin.server_node (role) WHERE role = 'main';

CREATE TABLE IF NOT EXISTS ops_and_admin.server_node_sample (
    node_id text NOT NULL REFERENCES ops_and_admin.server_node(id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    disk_total_bytes bigint,
    disk_free_bytes bigint,
    store_bytes bigint,
    memory_total_bytes bigint,
    memory_available_bytes bigint,
    load1 real,
    PRIMARY KEY (node_id, observed_at)
);

CREATE TABLE IF NOT EXISTS ops_and_admin.storage_object (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL,
    name text NOT NULL UNIQUE,
    size_bytes bigint NOT NULL,
    sha256 text NOT NULL,
    published_month date,
    generation integer,
    manifest_id uuid REFERENCES ops_and_admin.archive_manifest(id),
    origin_node text NOT NULL REFERENCES ops_and_admin.server_node(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    retired_at timestamptz,
    CONSTRAINT storage_object_kind_check CHECK (kind IN ('backup', 'archive_full', 'archive_browse')),
    CONSTRAINT storage_object_name_check CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$'),
    CONSTRAINT storage_object_sha_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT storage_object_size_check CHECK (size_bytes >= 0),
    CONSTRAINT storage_object_archive_check CHECK (
        kind = 'backup' OR (published_month IS NOT NULL AND generation IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ops_and_admin.storage_replica (
    object_id uuid NOT NULL REFERENCES ops_and_admin.storage_object(id) ON DELETE CASCADE,
    node_id text NOT NULL REFERENCES ops_and_admin.server_node(id),
    state text NOT NULL,
    bytes_done bigint NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    error text,
    verified_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (object_id, node_id),
    CONSTRAINT storage_replica_state_check CHECK (
        state IN ('wanted', 'transferring', 'verified', 'deleting', 'deleted', 'failed'))
);
CREATE INDEX IF NOT EXISTS storage_replica_node_state ON ops_and_admin.storage_replica (node_id, state);

CREATE TABLE IF NOT EXISTS ops_and_admin.runtime_policy (
    name text PRIMARY KEY,
    value jsonb NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_by text,
    CONSTRAINT runtime_policy_name_check CHECK (name IN ('collection', 'storage', 'analysis')),
    CONSTRAINT runtime_policy_object_check CHECK (jsonb_typeof(value) = 'object')
);

CREATE TABLE IF NOT EXISTS ops_and_admin.cold_archive_generation (
    published_month date NOT NULL,
    generation integer NOT NULL,
    state text NOT NULL,
    manifest_id uuid REFERENCES ops_and_admin.archive_manifest(id),
    full_object_id uuid REFERENCES ops_and_admin.storage_object(id),
    browse_object_id uuid REFERENCES ops_and_admin.storage_object(id),
    row_count bigint,
    publications integer,
    hot_bytes bigint,
    error text,
    started_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    finished_at timestamptz,
    PRIMARY KEY (published_month, generation),
    CONSTRAINT cold_archive_generation_month_check CHECK (published_month = date_trunc('month', published_month)::date),
    CONSTRAINT cold_archive_generation_number_check CHECK (generation >= 1),
    CONSTRAINT cold_archive_generation_state_check CHECK (
        state IN ('preparing', 'exporting', 'replicating', 'dropping', 'cold', 'failed'))
);

CREATE TABLE IF NOT EXISTS ops_and_admin.admin_job (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL,
    params jsonb NOT NULL DEFAULT '{}',
    state text NOT NULL DEFAULT 'queued',
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    started_at timestamptz,
    finished_at timestamptz,
    progress jsonb NOT NULL DEFAULT '{}',
    result jsonb,
    error text,
    CONSTRAINT admin_job_kind_check CHECK (kind IN ('archive_analysis', 'archive_now')),
    CONSTRAINT admin_job_state_check CHECK (state IN ('queued', 'running', 'done', 'failed', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS admin_job_queue ON ops_and_admin.admin_job (kind, state, requested_at);

-- Текущая схема: Сервер 2 показывает и хранит, Сервер 1 собирает все площадки.
INSERT INTO ops_and_admin.server_node (id, display_name, role, platforms, state)
VALUES ('server-2', 'Сервер 2 · основной', 'main', '{}', 'active'),
       ('server-1', 'Сервер 1 · сбор', 'collector', ARRAY['telegram', 'vk', 'max', 'rutube'], 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops_and_admin.runtime_policy (name, value) VALUES
('collection', '{"trackPostDays": 30, "snapshotHeartbeatHours": 24, "heartbeatMaxAgeDays": null}'),
('storage', '{"coldAfterDays": 30, "backupCopies": 1, "backupNodes": ["server-2", "server-1"],
              "archiveNodes": ["server-2", "server-1"], "browseCacheBytes": 2147483648}'),
('analysis', '{"finalAnalysisDays": 30}')
ON CONFLICT (name) DO NOTHING;

-- Порог горячего хранения задаёт политика storage; таблица остаётся источником
-- для функции удаления, панель обновляет обе в одной транзакции.
UPDATE ops_and_admin.retention_policy SET hot_days = 30, updated_at = transaction_timestamp()
 WHERE data_class = 'publication_metric_snapshot';
INSERT INTO ops_and_admin.retention_policy (data_class, hot_days, retention_months, archive_required, notes)
SELECT 'publication_metric_snapshot', 30, NULL, true, 'ADR-016: месяц уходит в холодный архив через coldAfterDays после конца'
WHERE NOT EXISTS (SELECT 1 FROM ops_and_admin.retention_policy WHERE data_class = 'publication_metric_snapshot');

-- Копия на другом сервере проекта — такой же независимый домен отказа, как
-- объектное хранилище: подтверждение пишет только функция ниже, по копии,
-- которую агент узла сам прочитал и сверил.
ALTER TABLE ops_and_admin.archive_object_attestation
    DROP CONSTRAINT IF EXISTS archive_object_attestation_object_uri_check;
ALTER TABLE ops_and_admin.archive_object_attestation
    ADD CONSTRAINT archive_object_attestation_object_uri_check
    CHECK (object_uri ~ '^(s3|gs|https|mranked-node)://');

CREATE OR REPLACE FUNCTION ops_and_admin.attest_node_replica(p_manifest uuid, p_object uuid, p_node text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog', 'ops_and_admin'
AS $$
DECLARE manifest ops_and_admin.archive_manifest%ROWTYPE; object ops_and_admin.storage_object%ROWTYPE;
 node ops_and_admin.server_node%ROWTYPE; replica ops_and_admin.storage_replica%ROWTYPE;
BEGIN
 SELECT * INTO manifest FROM ops_and_admin.archive_manifest WHERE id = p_manifest;
 SELECT * INTO object FROM ops_and_admin.storage_object WHERE id = p_object;
 SELECT * INTO node FROM ops_and_admin.server_node WHERE id = p_node;
 SELECT * INTO replica FROM ops_and_admin.storage_replica WHERE object_id = p_object AND node_id = p_node;
 IF manifest.id IS NULL OR manifest.status <> 'verified' OR object.id IS NULL OR object.kind <> 'archive_full'
    OR object.manifest_id IS DISTINCT FROM p_manifest OR object.sha256 <> manifest.sha256 THEN
   RAISE EXCEPTION 'archive object does not match the verified manifest';
 END IF;
 IF node.id IS NULL OR node.role = 'main' OR replica.state IS DISTINCT FROM 'verified' THEN
   RAISE EXCEPTION 'a verified replica on a non-main server is required';
 END IF;
 INSERT INTO ops_and_admin.archive_object_attestation (
   manifest_id, object_uri, object_version, sha256, canonical_sha256, row_count,
   failure_domain, immutable_until, verifier_subject)
 VALUES (p_manifest, 'mranked-node://' || p_node || '/archive/' || object.name, object.sha256,
         manifest.sha256, manifest.canonical_sha256, manifest.row_count, p_node,
         transaction_timestamp() + interval '30 days', 'node-agent:' || p_node)
 ON CONFLICT (manifest_id) DO NOTHING;
END $$;

-- Удаление партиции после выгрузки поколения. В отличие от v21: порог горячего
-- хранения от тридцати дней, и месяц после удаления снова открыт для записи —
-- поздние замеры ложатся в заново созданную партицию и уходят в следующее
-- поколение, а не упираются в закрытый месяц и не держат перенос.
CREATE OR REPLACE FUNCTION ops_and_admin.drop_publication_metric_partition_v22(p_month date, p_manifest_id uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
SET lock_timeout TO '10s'
SET "TimeZone" TO 'UTC'
AS $$
DECLARE month_end date := (p_month + interval '1 month')::date;
 manifest ops_and_admin.archive_manifest%ROWTYPE; attestation ops_and_admin.archive_object_attestation%ROWTYPE;
 actual record; hot_days integer; fence text;
BEGIN
 IF p_month IS NULL OR p_month <> date_trunc('month', p_month)::date THEN RAISE EXCEPTION 'canonical month required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:' || p_month::text, 0));
 SELECT state INTO fence FROM ops_and_admin.publication_partition_fence WHERE published_month = p_month FOR UPDATE;
 IF fence IS DISTINCT FROM 'archiving' THEN RAISE EXCEPTION 'archive fence required' USING ERRCODE = '55000'; END IF;
 SELECT * INTO manifest FROM ops_and_admin.archive_manifest WHERE id = p_manifest_id FOR UPDATE;
 SELECT * INTO attestation FROM ops_and_admin.archive_object_attestation WHERE manifest_id = p_manifest_id;
 SELECT rp.hot_days INTO hot_days FROM ops_and_admin.retention_policy rp WHERE rp.data_class = 'publication_metric_snapshot';
 IF hot_days IS NULL OR hot_days < 30 OR current_date < month_end + hot_days THEN RAISE EXCEPTION 'hot retention gate failed'; END IF;
 IF manifest.id IS NULL OR manifest.dataset_type <> 'publication_metric_snapshot' OR manifest.schema_version <> 3
    OR manifest.partition_start IS DISTINCT FROM p_month::timestamp AT TIME ZONE 'UTC'
    OR manifest.partition_end IS DISTINCT FROM month_end::timestamp AT TIME ZONE 'UTC'
    OR manifest.status <> 'verified' OR manifest.verified_at IS NULL OR manifest.canonical_sha256 IS NULL THEN
   RAISE EXCEPTION 'exact verified v3 manifest required';
 END IF;
 IF attestation.manifest_id IS NULL OR attestation.sha256 <> manifest.sha256
    OR attestation.canonical_sha256 <> manifest.canonical_sha256 OR attestation.row_count <> manifest.row_count
    OR attestation.immutable_until <= transaction_timestamp() THEN
   RAISE EXCEPTION 'off-primary immutable object attestation required';
 END IF;
 LOCK TABLE ingest.publication_metric_snapshot, ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
 LOCK TABLE ingest.publication, catalog.platform_account IN SHARE MODE;
 SELECT * INTO actual FROM ops_and_admin.publication_partition_digest(p_month);
 IF ROW(actual.row_count, actual.min_observed_at, actual.max_observed_at, actual.canonical_sha256)
    IS DISTINCT FROM ROW(manifest.row_count, manifest.min_observed_at, manifest.max_observed_at, manifest.canonical_sha256)
 THEN RAISE EXCEPTION 'partition content changed since verified export'; END IF;
 EXECUTE format('DROP TABLE ingest.%I', 'reaction_breakdown_' || to_char(p_month, 'YYYY_MM'));
 EXECUTE format('ALTER TABLE ingest.publication_metric_snapshot DETACH PARTITION ingest.%I',
                'publication_metric_snapshot_' || to_char(p_month, 'YYYY_MM'));
 EXECUTE format('DROP TABLE ingest.%I', 'publication_metric_snapshot_' || to_char(p_month, 'YYYY_MM'));
 UPDATE ops_and_admin.archive_manifest SET status = 'hot_dropped', hot_dropped_at = transaction_timestamp()
  WHERE id = p_manifest_id;
 UPDATE ops_and_admin.publication_partition_fence
    SET state = 'active', manifest_id = p_manifest_id, changed_at = transaction_timestamp()
  WHERE published_month = p_month;
 -- Пустая партиция сразу: следующая вставка не должна ждать её создания под
 -- блокировкой, а строки месяца не должны попасть в партицию по умолчанию.
 PERFORM ops_and_admin.ensure_publication_metric_partition(p_month);
END $$;

REVOKE ALL ON FUNCTION ops_and_admin.attest_node_replica(uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.drop_publication_metric_partition_v22(date, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.attest_node_replica(uuid, uuid, text) TO maintenance;
GRANT EXECUTE ON FUNCTION ops_and_admin.drop_publication_metric_partition_v22(date, uuid) TO maintenance;

GRANT SELECT, INSERT, UPDATE ON ops_and_admin.server_node TO maintenance, api_write_admin;
GRANT SELECT, UPDATE ON ops_and_admin.server_node TO collector_ingest;
GRANT SELECT, INSERT, DELETE ON ops_and_admin.server_node_sample TO maintenance, collector_ingest;
GRANT SELECT ON ops_and_admin.server_node_sample TO api_write_admin;
GRANT SELECT, INSERT, UPDATE ON ops_and_admin.storage_object TO maintenance;
GRANT SELECT ON ops_and_admin.storage_object TO api_write_admin, collector_ingest, api_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON ops_and_admin.storage_replica TO maintenance;
GRANT SELECT, UPDATE ON ops_and_admin.storage_replica TO collector_ingest;
GRANT SELECT ON ops_and_admin.storage_replica TO api_write_admin, api_read;
GRANT SELECT ON ops_and_admin.runtime_policy TO maintenance, collector_ingest, analytics_worker, api_read;
GRANT SELECT, UPDATE ON ops_and_admin.runtime_policy TO api_write_admin;
GRANT SELECT, INSERT, UPDATE ON ops_and_admin.cold_archive_generation TO maintenance;
GRANT SELECT ON ops_and_admin.cold_archive_generation TO api_write_admin, api_read, analytics_worker;
GRANT SELECT, INSERT, UPDATE ON ops_and_admin.admin_job TO api_write_admin;
GRANT SELECT, UPDATE ON ops_and_admin.admin_job TO maintenance, analytics_worker;
GRANT SELECT, UPDATE ON ops_and_admin.retention_policy TO api_write_admin;
GRANT SELECT ON ops_and_admin.publication_partition_fence TO api_read, api_write_admin;

COMMIT;
