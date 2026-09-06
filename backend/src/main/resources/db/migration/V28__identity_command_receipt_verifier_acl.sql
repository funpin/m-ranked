-- Original command values live in the durable private source-artifact store.
-- The bridge reads only committed acceptance/digest records to bind those inputs;
-- no public or collector role receives administrative receipt access.
SET ROLE migration_owner;
GRANT SELECT ON ops_and_admin.catalog_command_receipt TO migration_bridge;
RESET ROLE;
