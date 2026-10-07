-- 0064 — какая резервная копия проверена восстановлением.
--
-- На Сервере 2 остаётся только самая новая копия, на Сервере 1 — она и
-- последняя проверенная восстановлением (политика verifiedBackupNodes).
-- Чтобы сверщик размещения различал их, агент отмечает копию по квитанции
-- проверки (*.restore-verified.json рядом с дампом, SHA-256 совпадает).
--
-- Откат: удалить колонку; размещение вернётся к «последние backupCopies».
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE ops_and_admin.storage_object ADD COLUMN IF NOT EXISTS restore_verified_at timestamptz;
COMMIT;
