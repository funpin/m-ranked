-- 0058 — каноническая запись снимка для холодного архива одним представлением.
--
-- Две поломки одного места и блокировка, которая без них не всплывала.
--
-- 1. Расхождение. На проде publication_archive_record давно берёт разбивку
--    реакций сначала из metric_evidence->'reaction_breakdown' (так сборщик
--    r4 хранил её в сентябре без строк в ingest.reaction_breakdown), а
--    metric_evidence отдаёт без неё. В миграциях это не попало, и выгрузка
--    архива собирала разбивку только из таблицы: у таких снимков в файле
--    оказывался «{}», проверка падала на «archive canonical field mismatch:
--    reaction_breakdown_json», и июль с августом 2026 не уходили в архив.
--
-- 2. Цена. Функция вызывалась на каждую строку месяца — в выгрузке и ещё
--    дважды в дайджесте партиции. SECURITY DEFINER с SET не встраивается, и
--    вызов стоил ~5–13 мс против ~0,1 мс у того же выражения в запросе:
--    август (3,75 млн снимков) считался бы десятки часов, и каждую ночь база
--    до таймаута грузила процессор сервера.
--
-- Теперь выражение одно — в представлении. Выгрузка соединяется с ним в том
-- же запросе, дайджест читает его одним проходом, а функция одной строки
-- оставлена для прежних вызовов и берёт строку оттуда же. Текст записи
-- зависит от часового пояса сеанса: функции держат UTC сами, выгрузка
-- ставит его в своей транзакции.
--
-- 3. Блокировка. drop_publication_metric_partition_v22 пересчитывала дайджест
--    под ACCESS EXCLUSIVE на всей таблице снимков: на время подсчёта месяца
--    вставали API и приём по всем месяцам. Теперь сверка идёт под SHARE на
--    партициях этого месяца, а эксклюзивная блокировка — только на DROP.
--
-- Откат: вернуть определения функций из 0013 (с поправкой на разбивку из
-- metric_evidence), 0011 и 0057 и удалить представление; данные не меняются.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE VIEW ops_and_admin.publication_archive_canonical AS
SELECT s.published_month,
       s.id,
       s.observed_at,
       ((to_jsonb(s) - 'metric_evidence') || jsonb_build_object(
           'metric_evidence', s.metric_evidence - 'reaction_breakdown',
           'primary_account_id', p.primary_account_id,
           'platform', a.platform,
           'published_at', p.published_at,
           'reaction_breakdown', coalesce(s.metric_evidence -> 'reaction_breakdown', reactions.breakdown, '{}'::jsonb)
       ))::text AS canonical_record
  FROM ingest.publication_metric_snapshot_resolved s
  JOIN ingest.publication p ON p.id = s.publication_id
  JOIN catalog.platform_account a ON a.id = p.primary_account_id
  LEFT JOIN LATERAL (
      SELECT jsonb_object_agg(r.reaction_key, r.reaction_count ORDER BY r.reaction_key) AS breakdown
        FROM ingest.reaction_breakdown r
       WHERE r.snapshot_published_month = s.published_month
         AND r.snapshot_id = s.id
  ) AS reactions ON true;

CREATE OR REPLACE FUNCTION ops_and_admin.publication_archive_record(p_month date, p_id bigint) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'catalog'
    SET "TimeZone" TO 'UTC'
    AS $$
 SELECT canonical_record FROM ops_and_admin.publication_archive_canonical
  WHERE published_month = p_month AND id = p_id
$$;

CREATE OR REPLACE FUNCTION ops_and_admin.publication_partition_digest(p_month date) RETURNS TABLE(row_count bigint, min_observed_at timestamp with time zone, max_observed_at timestamp with time zone, canonical_sha256 text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    SET "TimeZone" TO 'UTC'
    AS $$
DECLARE item record; chain bytea:=sha256(''::bytea);
BEGIN
 row_count:=0;
 FOR item IN SELECT id,observed_at,canonical_record FROM ops_and_admin.publication_archive_canonical
              WHERE published_month=p_month ORDER BY id LOOP
   chain:=sha256(chain||sha256(convert_to(item.canonical_record,'UTF8')));
   row_count:=row_count+1;
   min_observed_at:=least(min_observed_at,item.observed_at);
   max_observed_at:=greatest(max_observed_at,item.observed_at);
 END LOOP;
 canonical_sha256:=encode(chain,'hex');
 RETURN NEXT;
END $$;

-- Удаление партиции сверяло дайджест под эксклюзивной блокировкой всей
-- таблицы снимков: пока месяц считается, API и приём стоят по всем месяцам.
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
 -- Сверка — под SHARE только на партициях месяца: запись в них стоит до
 -- конца транзакции, а чтение и остальные месяцы работают. Дайджест — один
 -- запрос с одним снимком данных, поэтому публикации и аккаунты не
 -- блокируются: их правка после сверки не меняет удаляемые строки.
 -- Эксклюзивная блокировка родителя — только на отсоединение и удаление.
 EXECUTE format('LOCK TABLE ingest.%I, ingest.%I IN SHARE MODE',
                'publication_metric_snapshot_' || to_char(p_month, 'YYYY_MM'),
                'reaction_breakdown_' || to_char(p_month, 'YYYY_MM'));
 SELECT * INTO actual FROM ops_and_admin.publication_partition_digest(p_month);
 IF ROW(actual.row_count, actual.min_observed_at, actual.max_observed_at, actual.canonical_sha256)
    IS DISTINCT FROM ROW(manifest.row_count, manifest.min_observed_at, manifest.max_observed_at, manifest.canonical_sha256)
 THEN RAISE EXCEPTION 'partition content changed since verified export'; END IF;
 LOCK TABLE ingest.publication_metric_snapshot, ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
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

REVOKE ALL ON ops_and_admin.publication_archive_canonical FROM PUBLIC;
GRANT SELECT ON ops_and_admin.publication_archive_canonical TO maintenance;

COMMIT;
