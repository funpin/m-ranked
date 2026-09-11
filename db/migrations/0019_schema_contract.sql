-- 0019 — идентификатор контракта схемы
-- Написана вручную; переопределяет представление из прежней схемы.

-- Контракт фиксирует live-read схему без материализованных почасовых проекций;
-- source_fingerprint хранится как bytea.
CREATE OR REPLACE VIEW ops_and_admin.schema_contract AS
    SELECT 'live-read-2026-09-13'::text AS contract_id;

COMMENT ON VIEW ops_and_admin.schema_contract IS
  'Идентификатор формы схемы. Меняется при любом несовместимом изменении; проверяется на старте API и коллекторов.';
