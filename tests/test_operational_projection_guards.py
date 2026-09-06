"""Execute operational SQL guards against transaction-local PostgreSQL fixtures.

The configured connection creates TEMP tables only and rolls back on close.
No migrations, canonical data, service routing, or writer processes are changed.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from migration.release_manifest import flyway_manifest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'operations/scripts'
NAMES = sorted([
    'publication_latest', 'publication_hourly', 'institution_daily_metrics',
    'institution_monthly_metrics', 'institution_period_metrics', 'comparison',
    'publication_history', 'publication_content', 'legacy_exports',
])
DSN = os.getenv('MRANKED_TEST_POSTGRES_ADMIN_DSN')


def _blocks(name):
    return re.findall(r"<<'SQL'\n(.*?)\nSQL", (SCRIPTS / name).read_text(), re.S)


def _guard_sql(kind):
    if kind == 'inspect':
        statement = _blocks('projection-publisher.sh')[0]
    elif kind == 'publish':
        statement = re.search(r'WITH latest_revision AS .*?\\gset',
                              _blocks('projection-publisher.sh')[1], re.S)[0]
        statement = statement.removesuffix('\\gset').replace(":'revision'", '42')
    elif kind in ('preflight', 'writer'):
        name = 'cutover-preflight.sh' if kind == 'preflight' else 'writer-cutover.sh'
        statement = next(block for block in _blocks(name) if '), core(name)' in block)
    else:
        statement = re.search(r'DO \$assertions\$.*?\$assertions\$;',
                              _blocks('restore-verify.sh')[0], re.S)[0]
    return re.sub(r'\b(?:analytics|ops_and_admin|flyway)\.', 'pg_temp.', statement)


@pytest.fixture
def guard_db():
    if not DSN:
        pytest.skip('requires MRANKED_TEST_POSTGRES_ADMIN_DSN; TEMP-only isolated SQL fixtures')
    import psycopg
    with psycopg.connect(DSN) as connection:
        try:
            connection.execute('CREATE TEMP TABLE dataset_revision(id bigint, committed_at timestamptz)')
            connection.execute('INSERT INTO dataset_revision VALUES (42,now())')
            connection.execute('CREATE TEMP TABLE projection_state(projection_name text PRIMARY KEY, dataset_revision_id bigint, status text)')
            connection.execute('CREATE TEMP TABLE outbox_event(event_type text, published_at timestamptz, dataset_revision_id bigint)')
            connection.execute('CREATE TEMP TABLE flyway_schema_history(installed_rank integer, version text, description text, type text, script text, checksum integer, success boolean)')
            connection.execute('INSERT INTO flyway_schema_history VALUES (0,NULL,%s,%s,%s,NULL,true)',
                               ('<< Flyway Schema Creation >>', 'SCHEMA', '"flyway"'))
            for migration in flyway_manifest():
                connection.execute('INSERT INTO flyway_schema_history VALUES (%s,%s,%s,%s,%s,%s,true)',
                                   (int(migration['version']), migration['version'], 'fixture', 'SQL',
                                    migration['script'], migration['checksum']))
            for name in NAMES:
                connection.execute('INSERT INTO projection_state VALUES (%s,42,%s)', (name, 'ready'))
            yield connection
        finally:
            connection.rollback()


@pytest.mark.parametrize('kind', ['inspect', 'publish', 'preflight', 'writer', 'restore'])
@pytest.mark.parametrize('fault', [
    'none', 'missing_history', 'missing_content', 'missing_exports', 'six_only',
    'extra', 'wrong_name', 'stale', 'future', 'null_status', 'null_revision',
    'rebuilding', 'failed', 'no_revision', 'advanced_revision',
])
def test_exact_nine_state_and_revision_guards_execute_in_postgres(guard_db, kind, fault):
    connection = guard_db
    if fault.startswith('missing_'):
        name = {'missing_history': 'publication_history', 'missing_content': 'publication_content',
                'missing_exports': 'legacy_exports'}[fault]
        connection.execute('DELETE FROM projection_state WHERE projection_name=%s', (name,))
    elif fault == 'six_only':
        connection.execute("DELETE FROM projection_state WHERE projection_name IN ('publication_history','publication_content','legacy_exports')")
    elif fault == 'extra':
        connection.execute("INSERT INTO projection_state VALUES ('unexpected',42,'ready')")
    elif fault == 'wrong_name':
        connection.execute("UPDATE projection_state SET projection_name='account_latest' WHERE projection_name='publication_history'")
    elif fault in ('stale', 'future', 'null_revision'):
        value = {'stale': 41, 'future': 43, 'null_revision': None}[fault]
        connection.execute("UPDATE projection_state SET dataset_revision_id=%s WHERE projection_name='legacy_exports'", (value,))
    elif fault in ('null_status', 'rebuilding', 'failed'):
        connection.execute("UPDATE projection_state SET status=%s WHERE projection_name='publication_content'",
                           (None if fault == 'null_status' else fault,))
    elif fault == 'no_revision':
        connection.execute('DELETE FROM dataset_revision')
    elif fault == 'advanced_revision':
        connection.execute('INSERT INTO dataset_revision VALUES (43,now())')

    statement = _guard_sql(kind)
    if kind == 'restore':
        import psycopg
        if fault == 'none':
            connection.execute(statement)
        else:
            with pytest.raises(psycopg.errors.RaiseException):
                connection.execute(statement)
        return
    row = connection.execute(statement).fetchone()
    if kind == 'inspect':
        accepted = row[0] in ('ready', 'finalize')
    elif kind == 'publish':
        accepted = row[0] is True
    elif kind == 'preflight':
        accepted = row[0] == 42 and row[1:] == (9, 0, 9)
    else:
        accepted = row == (42, 9, 9)
    assert accepted == (fault == 'none'), (kind, fault, row)


def test_publisher_finalizes_only_complete_revision_with_pending_requests(guard_db):
    guard_db.execute("INSERT INTO outbox_event VALUES ('projection.rebuild.requested',NULL,42)")
    assert guard_db.execute(_guard_sql('inspect')).fetchone() == ('finalize', 42, 9, 1)
    guard_db.execute("UPDATE projection_state SET status='rebuilding' WHERE projection_name='legacy_exports'")
    assert guard_db.execute(_guard_sql('inspect')).fetchone() == ('publish', 42, 8, 1)


def test_writer_accepts_immutable_correction_but_rejects_exact_replay_duplicates(guard_db):
    guard_db.execute('CREATE TEMP TABLE publication_metric_snapshot(published_month date,publication_id bigint,sampling_bucket text,source_fingerprint text)')
    statement = next(block for block in _blocks('writer-cutover.sh') if ') AS duplicates;' in block)
    statement = statement.replace('ingest.', 'pg_temp.')
    guard_db.execute("INSERT INTO publication_metric_snapshot VALUES ('2026-08-01',1,'bucket','original'),('2026-08-01',1,'bucket','correction')")
    assert guard_db.execute(statement).fetchone() == (0,)
    guard_db.execute("INSERT INTO publication_metric_snapshot VALUES ('2026-08-01',1,'bucket','correction')")
    assert guard_db.execute(statement).fetchone() == (1,)


def _restore_filter():
    script = (SCRIPTS / 'cutover-preflight.sh').read_text()
    return script.split('check_sha256_sidecar "$RESTORE_VERIFICATION_REPORT" "restore verification report"', 1)[1].split("if jq -e '\n", 1)[1].split("\n  ' \\\n", 1)[0]


def _restore_report():
    manifest = flyway_manifest()
    return {'status': 'pass', 'rtoMet': True,
            'checks': {'pageChecksums': True, 'databaseAssertions': True, 'pgAmcheck': True},
            'database': {'datasetRevision': 42, 'coreReadyProjections': 9,
                         'projectionStates': [{'name': name, 'status': 'ready', 'datasetRevision': 42} for name in NAMES],
                         'flywaySchemaVersion': int(manifest[-1]['version']), 'flywayMigrationCount': len(manifest),
                         'flywayMigrations': [{key: row[key] for key in ('version', 'script', 'checksum')}
                                              for row in manifest]}}


@pytest.mark.parametrize('fault', ['none', 'absent', 'six', 'duplicate', 'extra', 'stale', 'failed', 'false_count', 'fractional_revision'])
def test_restore_report_gate_requires_exact_names_and_coherent_revision(fault):
    report = deepcopy(_restore_report())
    database = report['database']
    states = database['projectionStates']
    if fault == 'absent': del database['projectionStates']
    elif fault == 'six': database['projectionStates'] = states[:6]
    elif fault == 'duplicate': states[-1] = states[0]
    elif fault == 'extra': states.append({'name': 'unexpected', 'status': 'ready', 'datasetRevision': 42})
    elif fault == 'stale': states[0]['datasetRevision'] = 41
    elif fault == 'failed': states[0]['status'] = 'failed'
    elif fault == 'false_count': database['coreReadyProjections'] = 6
    elif fault == 'fractional_revision': database['datasetRevision'] = 42.5
    result = subprocess.run(['jq', '-e', _restore_filter()], input=json.dumps(report), text=True, capture_output=True)
    assert (result.returncode == 0) == (fault == 'none'), result.stderr


@pytest.mark.parametrize('envelope,expected', [('ready|42|9|0', 0), ('ready|42|6|0', 70), ('finalize|42|6|1', 70), ('ready|42|10|0', 70)])
def test_publisher_shell_rejects_incomplete_ready_envelopes(tmp_path, envelope, expected):
    fake = tmp_path / 'psql'
    fake.write_text('#!/bin/sh\ncat >/dev/null\nprintf "%s\\n" "$TEST_ENVELOPE"\n')
    fake.chmod(0o700)
    password = tmp_path / 'pgpass'
    password.write_text('fixture-only\n')
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH'],
               PROJECTION_DATABASE_URL='unused', PGPASSFILE=str(password), TEST_ENVELOPE=envelope)
    result = subprocess.run(['bash', str(SCRIPTS / 'projection-publisher.sh'), '--once'],
                            env=env, text=True, capture_output=True, timeout=5)
    assert result.returncode == expected, result.stderr


def test_restore_assertions_and_report_share_repeatable_read_snapshot():
    block = _blocks('restore-verify.sh')[0]
    assert block.startswith('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;')
    assert block.rstrip().endswith('COMMIT;')
    assert block.index('DO $assertions$') < block.index("'projectionStates'") < block.index('COMMIT;')
