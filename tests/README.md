# Tests

`make test-python` runs unit tests, OpenAPI response validation, repository
hygiene and PostgreSQL integration tests. Tests that require a real database
read DSNs from `.env.test` and skip when it is absent.

`make test-frontend` runs lint, TypeScript, generated OpenAPI checks, unit and
Playwright tests, production build and bundle budget.

The clean-database CI job starts PostgreSQL from `db/migrations/*.sql` and
checks `ops_and_admin.schema_contract`. Legacy SQLite, Java, Redis, migration
bridge and cutover test suites were removed with those runtimes.
