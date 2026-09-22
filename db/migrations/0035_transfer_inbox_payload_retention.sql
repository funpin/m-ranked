-- 0035 — освобождать полезную нагрузку применённых конвертов
--
-- Причина: приёмник хранит тело каждого принятого конверта бессрочно. За
-- половину суток работы ops_and_admin.transfer_inbox набрал 43 тысячи
-- конвертов и 1.1 ГиБ, из которых 1.05 ГиБ — полезная нагрузка. Рост идёт со
-- скоростью поступления данных и сам не останавливается.
--
-- Строку удалять нельзя: по ней приёмник узнаёт повторную доставку и
-- возвращает ту же квитанцию вместо повторного применения. Удалив её, мы
-- превратили бы каждый повтор в новую работу и потеряли бы след о том, что
-- батч уже принят.
--
-- Но тело нужно ровно до тех пор, пока конверт может потребоваться применить.
-- После перехода в состояние applied данные уже лежат в рабочих таблицах, и
-- байты держит только прежнее ограничение: оно требовало payload у всего, что
-- не изолировано в карантин. Теперь исключение распространяется и на
-- применённые. Само тело обнуляет служба приёмника по окну хранения —
-- задержка нужна на случай, если применение придётся разбирать вручную.
--
-- Квитанция, счётчики, контрольная сумма и отметки времени остаются: аудит
-- того, что и когда было принято, от наличия тела не зависит.
--
-- Прежнее ограничение создавалось без имени, и PostgreSQL присвоил ему своё.
-- Ищем его по определению, а не по имени: номер зависит от порядка объявления
-- и на другой установке будет другим.
--
-- Откат: вернуть прежнее ограничение можно только после того, как у всех
-- применённых конвертов снова окажется payload, то есть практически никогда.
-- Совместимость при этом не страдает: старое ограничение строже нового, и
-- данные, проходившие его, проходят и новое.

DO $$
DECLARE
    victim text;
BEGIN
    SELECT conname INTO victim
      FROM pg_constraint
     WHERE conrelid = 'ops_and_admin.transfer_inbox'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%payload IS NOT NULL%'
       AND pg_get_constraintdef(oid) NOT LIKE '%applied%'
     LIMIT 1;
    IF victim IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE ops_and_admin.transfer_inbox DROP CONSTRAINT %I', victim
        );
    END IF;
END
$$;

ALTER TABLE ops_and_admin.transfer_inbox
    DROP CONSTRAINT IF EXISTS transfer_inbox_payload_present_check;

ALTER TABLE ops_and_admin.transfer_inbox
    ADD CONSTRAINT transfer_inbox_payload_present_check
    CHECK (state IN ('quarantined', 'applied') OR payload IS NOT NULL);

-- Обход идёт от самых старых применённых конвертов, у которых тело ещё есть.
CREATE INDEX IF NOT EXISTS transfer_inbox_applied_payload_idx
    ON ops_and_admin.transfer_inbox (applied_at)
    WHERE state = 'applied' AND payload IS NOT NULL;
