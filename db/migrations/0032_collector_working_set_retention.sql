-- 0032 — обрезка рабочего набора на сборочном хосте (профиль B)
--
-- Причина: в профиле B Сервер 1 держит только то, что нужно адаптерам для
-- планирования следующего цикла; полная история живёт на Сервере 2.
--
-- Почему дроп партиции, а не удаление строк. Наблюдения append-only: триггер
-- ingest.observation_immutable отвергает DELETE с ERRCODE 55000, и это
-- намеренный инвариант, а не помеха. Поэтому глубина обрезается тем же
-- способом, что и в холодном архиве, — целой месячной партицией.
--
-- Почему нельзя переиспользовать drop_publication_metric_partition_v21.
-- Та функция требует верифицированный архивный манифест и attestation
-- неизменяемого объекта вне основного узла: доказательством сохранности служит
-- выгрузка. На сборочном хосте доказательство другое — Сервер 2 подтвердил
-- приём батчей, покрывающих этот месяц. Подменять одно доказательство другим
-- внутри существующей функции нельзя: её гарантии нужны холодному архиву
-- ровно в прежнем виде.
--
-- Гарантии этой функции:
--   * только профиль B. В профиле A эта база и есть продукт;
--   * месяц целиком вне окна отслеживания публикаций;
--   * существует подтверждённый батч, созданный не раньше самой новой строки
--     месяца, и ни одного неподтверждённого батча до неё. Требуется именно
--     положительное доказательство: пустая очередь ничего не подтверждает, на
--     свежем хосте она тоже пуста. Обратная сторона — если purge_acknowledged
--     вычистит все подтверждённые записи, обрезка замрёт. Это безопасное
--     направление отказа: она откажется работать, а не удалит лишнее;
--   * те же advisory- и ACCESS EXCLUSIVE-блокировки, что и у холодного архива.
--
-- Откат: DROP FUNCTION. Функция ничего не меняет, пока её не вызвали, поэтому
-- до первого запуска откат чисто конфигурационный. После запуска вернуть
-- удалённый месяц можно только восстановлением с Сервера 2 или из копии.

CREATE OR REPLACE FUNCTION ops_and_admin.collector_working_set_month_releasable(
    p_month date,
    p_track_hours integer
) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    AS $$
DECLARE
    month_end timestamptz;
    newest timestamptz;
    acknowledged timestamptz;
    pending timestamptz;
BEGIN
    IF p_month IS NULL OR p_month <> date_trunc('month', p_month)::date THEN
        RAISE EXCEPTION 'canonical month required';
    END IF;
    IF p_track_hours IS NULL OR p_track_hours < 1 THEN
        RAISE EXCEPTION 'tracking window must be positive';
    END IF;

    month_end := ((p_month + interval '1 month')::date)::timestamptz;
    -- Последняя публикация месяца обязана выйти из окна отслеживания целиком.
    IF transaction_timestamp() < month_end + make_interval(hours => p_track_hours) THEN
        RETURN false;
    END IF;

    SELECT max(created_at) INTO newest
      FROM ingest.publication_metric_snapshot
     WHERE published_month = p_month;
    IF newest IS NULL THEN
        RETURN true;
    END IF;

    -- Нужно положительное доказательство, а не отсутствие возражений. Пустая
    -- очередь не значит, что Сервер 2 что-то получил: на свежем хосте она тоже
    -- пуста. Поэтому требуется подтверждённый батч, созданный не раньше самой
    -- новой строки месяца.
    SELECT max(created_at) INTO acknowledged
      FROM ops_and_admin.transfer_outbox
     WHERE state = 'acknowledged';
    IF acknowledged IS NULL OR acknowledged < newest THEN
        RETURN false;
    END IF;

    -- И ничто из неподтверждённого не относится к этим строкам.
    SELECT min(created_at) INTO pending
      FROM ops_and_admin.transfer_outbox
     WHERE state <> 'acknowledged';
    RETURN pending IS NULL OR pending > newest;
END $$;

CREATE OR REPLACE FUNCTION ops_and_admin.drop_collector_working_set_month(
    p_month date,
    p_track_hours integer
) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    SET lock_timeout TO '10s'
    SET "TimeZone" TO 'UTC'
    AS $$
DECLARE
    fence text;
    suffix text := to_char(p_month, 'YYYY_MM');
BEGIN
    IF coalesce(nullif(current_setting('mranked.deployment_profile', true), ''), 'a') <> 'b' THEN
        RAISE EXCEPTION 'collector working set retention requires deployment profile b'
            USING ERRCODE = '55000';
    END IF;
    IF NOT ops_and_admin.collector_working_set_month_releasable(p_month, p_track_hours) THEN
        RAISE EXCEPTION 'month is still tracked or not fully acknowledged'
            USING ERRCODE = '55000';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('observation-partition:' || p_month::text, 0)
    );
    -- Архивируемый месяц принадлежит холодному архиву; не пересекаемся.
    SELECT state INTO fence
      FROM ops_and_admin.publication_partition_fence
     WHERE published_month = p_month
       FOR UPDATE;
    IF fence IS NOT NULL AND fence <> 'active' THEN
        RAISE EXCEPTION 'partition is owned by the cold archive' USING ERRCODE = '55000';
    END IF;

    IF to_regclass('ingest.publication_metric_snapshot_' || suffix) IS NULL THEN
        RETURN false;
    END IF;

    LOCK TABLE ingest.publication_metric_snapshot, ingest.reaction_breakdown
        IN ACCESS EXCLUSIVE MODE;
    IF to_regclass('ingest.reaction_breakdown_' || suffix) IS NOT NULL THEN
        EXECUTE format('DROP TABLE ingest.%I', 'reaction_breakdown_' || suffix);
    END IF;
    EXECUTE format(
        'ALTER TABLE ingest.publication_metric_snapshot DETACH PARTITION ingest.%I',
        'publication_metric_snapshot_' || suffix
    );
    EXECUTE format('DROP TABLE ingest.%I', 'publication_metric_snapshot_' || suffix);
    RETURN true;
END $$;

REVOKE ALL ON FUNCTION ops_and_admin.collector_working_set_month_releasable(date, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.drop_collector_working_set_month(date, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.collector_working_set_month_releasable(date, integer) TO collector_ingest;
GRANT EXECUTE ON FUNCTION ops_and_admin.drop_collector_working_set_month(date, integer) TO collector_ingest;

COMMENT ON FUNCTION ops_and_admin.drop_collector_working_set_month(date, integer) IS
  'Профиль B: освобождает месяц наблюдений на сборочном хосте, когда он вышел из окна отслеживания и полностью подтверждён Сервером 2.';
