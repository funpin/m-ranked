-- 0030 — окно попыток доставки для transfer outbox
-- Причина: в профиле A потребитель живёт в том же процессе, поэтому плоская
-- секундная пауза между попытками была незаметна. В профиле B недоступный
-- Сервер 2 превращает её в непрерывный долбёж соседнего хоста. Протокол
-- (docs/architecture/raw-data-transfer.md) требует экспоненциальный backoff
-- 1 с – 5 мин с полным jitter и не более 20 попыток в час на батч.
-- Считать попытки по publish_attempts нельзя: этот счётчик растёт за всё время
-- жизни записи, а ограничение задано на скользящий час.
-- Откат: колонки аддитивные и имеют значения по умолчанию, поэтому прежний код
-- продолжает работать без них. Достаточно вернуть код отправителя; колонки
-- можно снять отдельным ALTER ... DROP COLUMN позже.

ALTER TABLE ops_and_admin.transfer_outbox
    ADD COLUMN IF NOT EXISTS attempt_window_started_at timestamptz,
    ADD COLUMN IF NOT EXISTS attempt_window_count integer NOT NULL DEFAULT 0;

-- Отрицательное значение означало бы потерянный учёт попыток, а не паузу.
ALTER TABLE ops_and_admin.transfer_outbox
    DROP CONSTRAINT IF EXISTS transfer_outbox_attempt_window_count_check;
ALTER TABLE ops_and_admin.transfer_outbox
    ADD CONSTRAINT transfer_outbox_attempt_window_count_check
    CHECK (attempt_window_count >= 0);

-- Дренаж идёт по (state, available_at, cursor); окно попыток читается той же
-- строкой, поэтому отдельный индекс не нужен.

COMMENT ON COLUMN ops_and_admin.transfer_outbox.attempt_window_started_at IS
  'Начало скользящего часа, в котором считаются попытки доставки этого батча.';
COMMENT ON COLUMN ops_and_admin.transfer_outbox.attempt_window_count IS
  'Попыток доставки внутри текущего часового окна; исчерпание не делает запись terminal.';
