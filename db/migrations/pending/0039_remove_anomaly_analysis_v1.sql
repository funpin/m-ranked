-- 0039 — удаление модели анализа v1
--
-- ПРИМЕНЯТЬ ТОЛЬКО ПОСЛЕ ПРОВЕРКИ V2 НА РЕАЛЬНЫХ ДАННЫХ.
--
-- Файл лежит в db/migrations/pending/ намеренно: стенд и выкатка применяют
-- db/migrations/*.sql подряд, и удаление не должно случиться само собой.
-- Когда проверка пройдена (operations/runbooks/ANOMALY.md, шаг 8), файл
-- переносится в db/migrations/ тем же релизом, что и изменения ниже.
--
-- Причина: анализ v2 (0036) хранит строку вывода на пост и журнал смен; модель
-- v1 писала ревизию на каждый прогон и больше никем не читается. Её очередь
-- кандидатов при этом обновляется триггером на каждой вставке замера — лишняя
-- запись на самом горячем пути сборщиков.
--
-- Что удаляется:
--   * триггер anomaly_candidate_after_effective_snapshot на замерах;
--   * функции работника v1, проверки ввода, метрик и админских команд;
--   * представления publication_analysis_state_public и
--     publication_anomaly_finding_public;
--   * восемь таблиц анализа v1 в analytics и две таблицы его обвязки в
--     ops_and_admin — очередь кандидатов и квитанции админских команд.
--
-- Тем же релизом обязательно:
--   * убрать POST /api/v1/admin/publications/{id}/anomaly-signals и
--     POST /api/v1/admin/anomaly-signals/{id}/reviews с их SQL в
--     api/sql/analysis.py — они вызывают удаляемые функции. Ручной проверки
--     в v2 пока нет; её поле — analytics.post_anomaly_state.review_status;
--   * убрать упоминания удалённых объектов из db/tools/emit.py.
--
-- Не затрагивается: ops_and_admin.schema_contract (идентификатор прежний —
-- сборщики и API не читают удаляемых объектов), таблицы v2, платформенные
-- возможности метрик analytics.platform_metric_capability.
--
-- Откат: только восстановлением из дампа, снятого перед применением. Данные v1
-- не переносились в v2 и после удаления не восстанавливаются.

DROP TRIGGER IF EXISTS anomaly_candidate_after_effective_snapshot ON ingest.publication_metric_snapshot;

DROP FUNCTION IF EXISTS ops_and_admin.mark_anomaly_candidate();
DROP FUNCTION IF EXISTS ops_and_admin.claim_anomaly_candidates(integer, integer, uuid);
DROP FUNCTION IF EXISTS ops_and_admin.complete_anomaly_noop(uuid, uuid, bigint);
DROP FUNCTION IF EXISTS ops_and_admin.pin_latest_anomaly_source_revision();
DROP FUNCTION IF EXISTS ops_and_admin.record_anomaly_attempt_tombstone(uuid, uuid, text);
DROP FUNCTION IF EXISTS ops_and_admin.seed_anomaly_backfill(integer, text);
DROP FUNCTION IF EXISTS analytics.anomaly_input_is_unchanged(uuid, text, text);
DROP FUNCTION IF EXISTS analytics.anomaly_operational_metrics();
DROP FUNCTION IF EXISTS analytics.extract_publication_history_as_of(uuid[], bigint, integer);
DROP FUNCTION IF EXISTS analytics.publish_anomaly_success(
    uuid, uuid, bigint, uuid, bigint, text, text, text, text, integer, integer,
    timestamp with time zone, text, numeric, text, jsonb);
DROP FUNCTION IF EXISTS analytics.publish_anomaly_failure(
    uuid, uuid, bigint, uuid, bigint, text, text, text, integer, integer,
    timestamp with time zone, text, integer);
DROP FUNCTION IF EXISTS analytics.create_manual_anomaly_signal(
    uuid, text, text, text, timestamp with time zone, timestamp with time zone, jsonb, text, uuid, uuid, text);
DROP FUNCTION IF EXISTS analytics.append_anomaly_review(uuid, text, text, text, uuid, uuid, text);

DROP VIEW IF EXISTS analytics.publication_anomaly_finding_public;
DROP VIEW IF EXISTS analytics.publication_analysis_state_public;

-- Порядок — от зависимых к тем, на кого они ссылаются: без CASCADE, чтобы
-- неучтённая зависимость остановила миграцию, а не исчезла молча.
DROP TABLE IF EXISTS analytics.publication_anomaly_review;
DROP TABLE IF EXISTS analytics.publication_anomaly_finding;
DROP TABLE IF EXISTS analytics.publication_analysis_state;
DROP TABLE IF EXISTS analytics.publication_analysis_attempt;
DROP TABLE IF EXISTS analytics.anomaly_review;
DROP TABLE IF EXISTS analytics.anomaly_event;
DROP TABLE IF EXISTS analytics.anomaly_analysis_revision;
DROP TABLE IF EXISTS analytics.anomaly_source_revision;
DROP TABLE IF EXISTS ops_and_admin.anomaly_analysis_candidate;
DROP TABLE IF EXISTS ops_and_admin.anomaly_command_receipt;
