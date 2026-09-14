-- 0018 — уведомление об инвалидации кэша
-- Порождается вручную; частью прежней схемы не является.

-- Кэш публичных ответов живёт в памяти процесса API, а не в Redis. Сбрасывать
-- его по номеру ревизии нельзя: ревизия штампуется в пиковом режиме раз в
-- 3.5 секунды, и такой кэш обесценивается целиком при каждой записи. Поэтому
-- ключ от ревизии не зависит, а сброс идёт по факту записи: запись в outbox
-- превращается в NOTIFY со списком затронутых областей данных.
--
-- Тип события в уведомлении не влияет на сброс: слушатель ключуется по
-- affected_tags. Поэтому эмитенты продолжают писать dataset.revision.changed,
-- как они уже делают на проде, и переименовывать их не нужно.
--
-- Доставка уведомления не гарантирована: процесс, отключённый в этот момент,
-- его не получит. Страховкой служит TTL записи кэша и сброс кэша целиком при
-- восстановлении соединения слушателем.
CREATE FUNCTION ops_and_admin.notify_cache_invalidation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
BEGIN
    PERFORM pg_notify('mranked_cache', jsonb_build_object(
        'id', NEW.id,
        'event', NEW.event_type,
        'tags', to_jsonb(NEW.affected_tags)
    )::text);
    RETURN NULL;
END
$$;

COMMENT ON FUNCTION ops_and_admin.notify_cache_invalidation() IS
  'Превращает запись в outbox_event в NOTIFY mranked_cache со списком затронутых областей данных.';

CREATE TRIGGER outbox_event_notify
    AFTER INSERT ON ops_and_admin.outbox_event
    FOR EACH ROW EXECUTE FUNCTION ops_and_admin.notify_cache_invalidation();

REVOKE ALL ON FUNCTION ops_and_admin.notify_cache_invalidation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.notify_cache_invalidation() TO collector_ingest, api_write_admin, maintenance;

-- Очередь outbox не чистится ничем: на срезе прода в ней 67 448 строк и 78 МБ.
-- Доставленные события старше суток удерживать незачем.
CREATE FUNCTION ops_and_admin.purge_delivered_outbox(p_older_than interval DEFAULT interval '1 day',
                                                     p_batch_size integer DEFAULT 10000)
    RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
DECLARE deleted bigint;
BEGIN
    IF p_batch_size < 1 OR p_batch_size > 100000 THEN
        RAISE EXCEPTION 'batch size out of range' USING ERRCODE='22023';
    END IF;
    WITH doomed AS (
        SELECT id FROM ops_and_admin.outbox_event
         WHERE (published_at IS NOT NULL AND published_at < now() - p_older_than)
            OR (terminal_at IS NOT NULL AND terminal_at < now() - p_older_than)
         ORDER BY id
         LIMIT p_batch_size
         FOR UPDATE SKIP LOCKED
    )
    DELETE FROM ops_and_admin.outbox_event victim USING doomed WHERE victim.id = doomed.id;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RETURN deleted;
END
$$;

COMMENT ON FUNCTION ops_and_admin.purge_delivered_outbox(interval, integer) IS
  'Удаляет доставленные и терминальные события outbox старше указанного возраста.';

REVOKE ALL ON FUNCTION ops_and_admin.purge_delivered_outbox(interval, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.purge_delivered_outbox(interval, integer) TO maintenance;
